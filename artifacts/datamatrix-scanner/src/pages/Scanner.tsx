import { useEffect, useRef, useState, useCallback } from 'react';
import { BrowserDatamatrixCodeReader } from '@zxing/browser';
import { DecodeHintType, Result, ResultPoint } from '@zxing/library';
import { analyzeQuality, QualityResult, gradeColor, gradeLabel, Grade } from '@/lib/qualityAnalysis';
import { playGradeSound } from '@/lib/audioFeedback';
import GradeDisplay from '@/components/GradeDisplay';
import ParameterTable from '@/components/ParameterTable';
import HistoryLog from '@/components/HistoryLog';
import ScannerOverlay from '@/components/ScannerOverlay';

export interface ScanRecord {
  id: string;
  result: QualityResult;
}

// ── Параметры — точное соответствие Python-проекту ───────────────────────────
const DECODE_INTERVAL_MS = 150;   // _decode_interval = 0.15 сек
const SCAN_LOCK_MS       = 1500;  // _scan_lock_ms

// ── Препроцессинг кадра ───────────────────────────────────────────────────────
function makeGray(data: Uint8ClampedArray): Float32Array {
  const n = data.length / 4;
  const g = new Float32Array(n);
  for (let i = 0; i < n; i++)
    g[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
  return g;
}

function stretchContrast(data: Uint8ClampedArray, gray: Float32Array): void {
  let minV = 255, maxV = 0;
  for (let i = 0; i < gray.length; i++) {
    if (gray[i] < minV) minV = gray[i];
    if (gray[i] > maxV) maxV = gray[i];
  }
  const range = maxV - minV || 1;
  for (let i = 0; i < gray.length; i++) {
    const v = Math.round((gray[i] - minV) / range * 255);
    data[i * 4] = v; data[i * 4 + 1] = v; data[i * 4 + 2] = v; data[i * 4 + 3] = 255;
  }
}

function applyGray(data: Uint8ClampedArray, gray: Float32Array): void {
  for (let i = 0; i < gray.length; i++) {
    const v = Math.round(Math.max(0, Math.min(255, gray[i])));
    data[i * 4] = v; data[i * 4 + 1] = v; data[i * 4 + 2] = v; data[i * 4 + 3] = 255;
  }
}

function sharpen(gray: Float32Array, w: number, h: number): Float32Array {
  const out = new Float32Array(gray.length);
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      out[i] = Math.max(0, Math.min(255,
        5 * gray[i] - gray[(y-1)*w+x] - gray[(y+1)*w+x] - gray[y*w+x-1] - gray[y*w+x+1]
      ));
    }
  }
  return out;
}

/** Создать canvas с применённым препроцессингом */
function makeCanvas(data: Uint8ClampedArray, w: number, h: number): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const img = new ImageData(w, h);
  img.data.set(data);
  c.getContext('2d')!.putImageData(img, 0, 0);
  return c;
}

/** Вырезать прямоугольную область из canvas */
function cropCanvas(
  src: HTMLCanvasElement, x: number, y: number, w: number, h: number
): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  c.getContext('2d')!.drawImage(src, x, y, w, h, 0, 0, w, h);
  return c;
}

/** Масштабировать canvas */
function scaleCanvas(src: HTMLCanvasElement, scale: number): HTMLCanvasElement {
  const w = Math.round(src.width * scale), h = Math.round(src.height * scale);
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  c.getContext('2d')!.drawImage(src, 0, 0, w, h);
  return c;
}

// ── Тип результата декодирования ──────────────────────────────────────────────
interface DecodeHit {
  text:    string;
  pts:     readonly ResultPoint[] | null;
  offsetX: number;
  offsetY: number;
}

/** Попытка декодировать один canvas ZXing-ом */
async function tryDecodeCanvas(
  reader: BrowserDatamatrixCodeReader,
  canvas: HTMLCanvasElement,
  offsetX = 0,
  offsetY = 0
): Promise<DecodeHit | null> {
  try {
    const r: Result = await (reader as any).decodeFromCanvas(canvas);
    if (r) return { text: r.getText(), pts: r.getResultPoints(), offsetX, offsetY };
  } catch {}
  return null;
}

export default function Scanner() {
  const videoRef   = useRef<HTMLVideoElement>(null);
  const canvasRef  = useRef<HTMLCanvasElement>(null);
  const readerRef  = useRef<BrowserDatamatrixCodeReader | null>(null);
  const streamRef  = useRef<MediaStream | null>(null);

  // Флаги и дескрипторы циклов
  const runningRef      = useRef(false);
  const decodingRef     = useRef(false);
  const rafRef          = useRef<number | null>(null);
  const decodeTimerRef  = useRef<ReturnType<typeof setInterval> | null>(null);

  // Scan-lock (аналог Python _last_decoded / _last_decoded_t)
  const lastDecoded     = useRef<string>('');
  const lastDecodedTime = useRef<number>(0);

  const [cameras, setCameras]             = useState<MediaDeviceInfo[]>([]);
  const [selectedCamera, setSelectedCamera] = useState<string>('');
  const [scanning, setScanning]           = useState(false);
  const [currentResult, setCurrentResult] = useState<QualityResult | null>(null);
  const [history, setHistory]             = useState<ScanRecord[]>([]);
  const [cameraError, setCameraError]     = useState<string>('');
  const [soundEnabled, setSoundEnabled]   = useState(true);
  const [activeTab, setActiveTab]         = useState<'scan' | 'history'>('scan');
  const [fps, setFps]                     = useState(0);

  const fpsCounter = useRef({ frames: 0, last: Date.now() });

  useEffect(() => {
    BrowserDatamatrixCodeReader.listVideoInputDevices().then((devices) => {
      setCameras(devices);
      if (devices.length > 0) {
        const back = devices.find(d =>
          d.label.toLowerCase().includes('back') ||
          d.label.toLowerCase().includes('rear') ||
          d.label.toLowerCase().includes('environment')
        );
        // Последняя камера — обычно наилучшего качества
        setSelectedCamera(back?.deviceId ?? devices[devices.length - 1].deviceId);
      }
    }).catch(() => {
      setCameraError('Не удалось получить список камер. Разрешите доступ к камере в браузере.');
    });
  }, []);

  // ── ROI из result points (с учётом смещения кропа) ───────────────────────
  const computeRoi = useCallback((
    frame: HTMLCanvasElement,
    pts:   readonly ResultPoint[] | null,
    ox:    number,
    oy:    number
  ): { x: number; y: number; w: number; h: number } => {
    const fw = frame.width, fh = frame.height;
    if (pts && pts.length >= 2) {
      const xs = Array.from(pts).map(p => p.getX() + ox);
      const ys = Array.from(pts).map(p => p.getY() + oy);
      const minX = Math.min(...xs), maxX = Math.max(...xs);
      const minY = Math.min(...ys), maxY = Math.max(...ys);
      const sw = maxX - minX, sh = maxY - minY;
      if (sw > 4 && sh > 4) {
        const margin = Math.max(sw, sh) * 0.25;
        const rx = Math.max(0, Math.floor(minX - margin));
        const ry = Math.max(0, Math.floor(minY - margin));
        const rw = Math.min(fw - rx, Math.ceil(sw + 2 * margin));
        const rh = Math.min(fh - ry, Math.ceil(sh + 2 * margin));
        if (rw > 10 && rh > 10) return { x: rx, y: ry, w: rw, h: rh };
      }
    }
    // Fallback: центральные 50% кадра
    const mx = Math.floor(fw * 0.25), my = Math.floor(fh * 0.25);
    return { x: mx, y: my, w: fw - 2 * mx, h: fh - 2 * my };
  }, []);

  // ── Обработка успешного декодирования ────────────────────────────────────
  const handleDecoded = useCallback((hit: DecodeHit, frame: HTMLCanvasElement) => {
    const now = Date.now();
    // Scan-lock: тот же код в течение SCAN_LOCK_MS — пропускаем
    if (hit.text === lastDecoded.current && now - lastDecodedTime.current < SCAN_LOCK_MS) return;

    lastDecoded.current     = hit.text;
    lastDecodedTime.current = now;

    // Авто-сброс scan-lock через SCAN_LOCK_MS — сразу ищем следующий код
    setTimeout(() => {
      lastDecoded.current     = '';
      lastDecodedTime.current = 0;
    }, SCAN_LOCK_MS);

    const roi    = computeRoi(frame, hit.pts, hit.offsetX, hit.offsetY);
    const result = analyzeQuality(frame, hit.text, roi);
    if (soundEnabled) playGradeSound(result.overallGrade);
    setCurrentResult(result);
    setHistory(prev => [
      { id: `${now}-${Math.random().toString(36).slice(2)}`, result },
      ...prev.slice(0, 49),
    ]);
  }, [soundEnabled, computeRoi]);

  // ── Поток 1: захват кадров (requestAnimationFrame) ────────────────────────
  // Аналог Python _capture_loop
  const startCaptureLoop = useCallback(() => {
    const loop = () => {
      if (!runningRef.current) return;
      const video  = videoRef.current;
      const canvas = canvasRef.current;
      if (video && canvas && video.readyState >= 2) {
        canvas.width  = video.videoWidth  || 640;
        canvas.height = video.videoHeight || 480;
        canvas.getContext('2d')!.drawImage(video, 0, 0);

        const f = fpsCounter.current;
        f.frames++;
        const now = Date.now();
        if (now - f.last >= 1000) {
          setFps(f.frames);
          f.frames = 0;
          f.last   = now;
        }
      }
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
  }, []);

  // ── Поток 2: декодирование (setInterval 150ms) ────────────────────────────
  // Аналог Python _decode_loop с _decode_interval = 0.15
  // 3 шага: полный кадр → центральная зона → препроцессинг
  const startDecodeLoop = useCallback((reader: BrowserDatamatrixCodeReader) => {
    if (decodeTimerRef.current) clearInterval(decodeTimerRef.current);

    decodeTimerRef.current = setInterval(async () => {
      if (decodingRef.current || !runningRef.current) return;
      const canvas = canvasRef.current;
      if (!canvas || canvas.width === 0 || canvas.height === 0) return;

      decodingRef.current = true;
      try {
        const fw = canvas.width, fh = canvas.height;
        let hit: DecodeHit | null = null;

        // ── Шаг 1: полный кадр (аналог Python step 1) ──────────────────
        hit = await tryDecodeCanvas(reader, canvas);

        // ── Шаг 2: центральная зона 70% (аналог Python step 2, m=0.15) ─
        if (!hit) {
          const m  = 0.15;
          const cx = Math.floor(fw * m),       cy = Math.floor(fh * m);
          const cw = Math.floor(fw * (1-2*m)), ch = Math.floor(fh * (1-2*m));
          if (cw > 20 && ch > 20) {
            hit = await tryDecodeCanvas(reader, cropCanvas(canvas, cx, cy, cw, ch), cx, cy);
          }
        }

        // ── Шаг 3: препроцессинг (аналог Python try_decode_dmtx variants) ─
        // CLAHE-аппроксимация, резкость, инверсия, масштаб 1.5×
        if (!hit) {
          const ctx  = canvas.getContext('2d')!;
          const img  = ctx.getImageData(0, 0, fw, fh);
          const gray = makeGray(img.data);

          // 3a: контраст-стретч
          const d1 = new Uint8ClampedArray(img.data);
          stretchContrast(d1, gray);
          hit = await tryDecodeCanvas(reader, makeCanvas(d1, fw, fh));

          // 3b: контраст + инверсия (тёмный фон)
          if (!hit) {
            const d2 = new Uint8ClampedArray(d1);
            for (let i = 0; i < d2.length; i += 4) {
              d2[i] = 255 - d2[i]; d2[i+1] = 255 - d2[i+1]; d2[i+2] = 255 - d2[i+2];
            }
            hit = await tryDecodeCanvas(reader, makeCanvas(d2, fw, fh));
          }

          // 3c: резкость
          if (!hit) {
            const sg = sharpen(gray, fw, fh);
            const d3 = new Uint8ClampedArray(img.data);
            applyGray(d3, sg);
            hit = await tryDecodeCanvas(reader, makeCanvas(d3, fw, fh));
          }

          // 3d: масштаб 1.5× центрального кропа (маленький символ)
          if (!hit) {
            const m  = 0.20;
            const cx = Math.floor(fw * m),       cy = Math.floor(fh * m);
            const cw = Math.floor(fw * (1-2*m)), ch = Math.floor(fh * (1-2*m));
            if (cw > 20 && ch > 20) {
              hit = await tryDecodeCanvas(
                reader,
                scaleCanvas(cropCanvas(canvas, cx, cy, cw, ch), 1.5),
                cx, cy
              );
            }
          }
        }

        if (hit) handleDecoded(hit, canvas);
      } finally {
        decodingRef.current = false;
      }
    }, DECODE_INTERVAL_MS);
  }, [handleDecoded]);

  // ── Запуск/остановка сканирования ─────────────────────────────────────────
  const stopAllLoops = useCallback(() => {
    runningRef.current = false;
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    if (decodeTimerRef.current !== null) {
      clearInterval(decodeTimerRef.current);
      decodeTimerRef.current = null;
    }
  }, []);

  const stopScanning = useCallback(() => {
    stopAllLoops();
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) videoRef.current.srcObject = null;
    setScanning(false);
    setFps(0);
  }, [stopAllLoops]);

  const startScanning = useCallback(async () => {
    if (!selectedCamera) return;
    setCameraError('');
    stopAllLoops();

    try {
      // Получаем камеру (3 попытки с деградацией ограничений)
      let stream: MediaStream | null = null;
      try {
        const constraints: any = {
          deviceId: { exact: selectedCamera },
          width:     { ideal: 1920, min: 1280 },
          height:    { ideal: 1080, min: 720 },
          frameRate: { ideal: 60,   min: 30  },
          focusMode: 'continuous',
        };
        stream = await navigator.mediaDevices.getUserMedia({ video: constraints, audio: false });
      } catch {
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            video: { deviceId: { exact: selectedCamera }, width: { ideal: 1280 }, height: { ideal: 720 } },
            audio: false,
          });
        } catch {
          stream = await navigator.mediaDevices.getUserMedia({
            video: { deviceId: selectedCamera },
            audio: false,
          });
        }
      }

      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }

      // Создаём ZXing reader с TRY_HARDER
      const hints = new Map<DecodeHintType, any>();
      hints.set(DecodeHintType.TRY_HARDER, true);
      const reader = new BrowserDatamatrixCodeReader(hints);
      readerRef.current = reader;

      runningRef.current = true;
      startCaptureLoop();        // Поток 1: захват кадров
      startDecodeLoop(reader);   // Поток 2: декодирование

      setScanning(true);
    } catch (e: any) {
      setCameraError(`Ошибка запуска камеры: ${e?.message || e}`);
      setScanning(false);
    }
  }, [selectedCamera, stopAllLoops, startCaptureLoop, startDecodeLoop]);

  useEffect(() => () => { stopScanning(); }, []);

  useEffect(() => {
    if (scanning) { stopScanning(); startScanning(); }
  }, [selectedCamera]);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b border-border/50 bg-card/80 backdrop-blur sticky top-0 z-50 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary/20 flex items-center justify-center">
            <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.75 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 013.75 9.375v-4.5zM3.75 14.625c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5a1.125 1.125 0 01-1.125-1.125v-4.5zM13.5 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 0113.5 9.375v-4.5z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M6.75 6.75h.75v.75h-.75v-.75zM6.75 16.5h.75v.75h-.75v-.75zM16.5 6.75h.75v.75h-.75v-.75zM13.5 13.5h.75v.75h-.75v-.75zM13.5 19.5h.75v.75h-.75v-.75zM19.5 13.5h.75v.75h-.75v-.75zM19.5 19.5h.75v.75h-.75v-.75zM16.5 16.5h.75v.75h-.75v-.75z" />
            </svg>
          </div>
          <div>
            <h1 className="text-sm font-semibold text-foreground tracking-tight">DataMatrix Quality Scanner</h1>
            <p className="text-xs text-muted-foreground">ГОСТ Р 57302-2016 / ISO/IEC 15415</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground hidden sm:block">Свидович А. · Петляков А.</span>
          {scanning && (
            <span className="text-xs text-primary font-mono bg-primary/10 px-2 py-0.5 rounded">{fps} fps</span>
          )}
          <button
            onClick={() => setSoundEnabled(v => !v)}
            className={`w-8 h-8 rounded-lg flex items-center justify-center transition-colors ${soundEnabled ? 'bg-primary/20 text-primary' : 'bg-secondary text-muted-foreground'}`}
            title={soundEnabled ? 'Звук включен' : 'Звук выключен'}
          >
            {soundEnabled ? (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" clipRule="evenodd" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" />
              </svg>
            )}
          </button>
        </div>
      </header>

      <div className="flex-1 flex flex-col lg:flex-row gap-0 overflow-hidden">
        <div className="lg:w-[55%] flex flex-col bg-black">
          <div className="relative aspect-video bg-gray-950 flex-shrink-0">
            <video ref={videoRef} className="w-full h-full object-cover" muted playsInline autoPlay />
            <canvas ref={canvasRef} className="hidden" />
            {scanning && <ScannerOverlay active={scanning} />}
            {!scanning && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-gray-950/90">
                <div className="text-5xl opacity-30">◻</div>
                <p className="text-sm text-muted-foreground">Нажмите «Старт» для начала сканирования</p>
              </div>
            )}
          </div>

          <div className="p-4 bg-card border-t border-border/50 flex items-center gap-3 flex-wrap">
            <div className="flex-1 min-w-[180px]">
              <select
                className="w-full bg-secondary border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                value={selectedCamera}
                onChange={e => setSelectedCamera(e.target.value)}
                disabled={scanning}
              >
                {cameras.length === 0 && <option value="">Нет доступных камер</option>}
                {cameras.map(c => (
                  <option key={c.deviceId} value={c.deviceId}>
                    {c.label || `Камера ${c.deviceId.slice(0, 8)}`}
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={scanning ? stopScanning : startScanning}
              disabled={!selectedCamera && cameras.length > 0}
              className={`px-5 py-2 rounded-lg font-medium text-sm transition-all ${
                scanning
                  ? 'bg-destructive/20 text-destructive border border-destructive/40 hover:bg-destructive/30'
                  : 'bg-primary text-primary-foreground hover:bg-primary/90'
              }`}
            >
              {scanning ? 'Стоп' : 'Старт'}
            </button>
          </div>

          {cameraError && (
            <div className="mx-4 mb-4 p-3 bg-destructive/10 border border-destructive/30 rounded-lg text-xs text-destructive">
              {cameraError}
            </div>
          )}
        </div>

        <div className="lg:w-[45%] flex flex-col border-l border-border/50 overflow-hidden">
          <div className="flex border-b border-border/50">
            {(['scan', 'history'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`flex-1 py-3 text-sm font-medium transition-colors ${
                  activeTab === tab
                    ? 'text-primary border-b-2 border-primary bg-primary/5'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {tab === 'scan' ? 'Результат анализа' : `История (${history.length})`}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto">
            {activeTab === 'scan' ? (
              <div className="p-4 space-y-4">
                {currentResult ? (
                  <div className="result-enter space-y-4">
                    <GradeDisplay result={currentResult} />
                    <ParameterTable parameters={currentResult.parameters} />
                    <div className="bg-secondary/50 rounded-lg p-3">
                      <p className="text-xs text-muted-foreground mb-1 font-medium">Декодированные данные</p>
                      <p className="text-sm font-mono text-foreground break-all">{currentResult.decodedData}</p>
                    </div>
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>Время анализа: {currentResult.analysisTimeMs.toFixed(1)} мс</span>
                      <span>{currentResult.timestamp.toLocaleTimeString('ru')}</span>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
                    <div className="w-16 h-16 rounded-2xl bg-secondary flex items-center justify-center">
                      <svg className="w-8 h-8 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M3.75 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 013.75 9.375v-4.5zM3.75 14.625c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5a1.125 1.125 0 01-1.125-1.125v-4.5zM13.5 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 0113.5 9.375v-4.5z" />
                      </svg>
                    </div>
                    <p className="text-sm text-muted-foreground">Поднесите DataMatrix к камере</p>
                    <p className="text-xs text-muted-foreground/60">Качество будет оценено автоматически</p>
                  </div>
                )}
              </div>
            ) : (
              <HistoryLog history={history} />
            )}
          </div>
        </div>
      </div>

      <footer className="border-t border-border/50 py-2 px-6 flex items-center justify-between text-xs text-muted-foreground/60">
        <span>ГОСТ Р 57302-2016 · ISO/IEC 15415:2011</span>
        <span>Авторы: А. Свидович, А. Петляков</span>
      </footer>
    </div>
  );
}

import { useEffect, useRef, useState, useCallback } from 'react';
import { BrowserDatamatrixCodeReader } from '@zxing/browser';
import { DecodeHintType, ResultPoint } from '@zxing/library';
import { analyzeQuality, QualityResult } from '@/lib/qualityAnalysis';
import { playGradeSound } from '@/lib/audioFeedback';
import GradeDisplay from '@/components/GradeDisplay';
import ParameterTable from '@/components/ParameterTable';
import HistoryLog from '@/components/HistoryLog';
import ScannerOverlay from '@/components/ScannerOverlay';

export interface ScanRecord {
  id:       string;
  result:   QualityResult;
  photoUrl?: string; // Object-URL снимка; авто-удаляется через PHOTO_TTL_MS
}

// ── Константы ─────────────────────────────────────────────────────────────────
const DECODE_INTERVAL_MS  = 50;    // мс между попытками декодирования
const SCAN_LOCK_MS        = 1500;  // блокировка повтора одного кода
const HARD_SEARCH_AFTER_MS = 400;  // делать доп. шаги только если код был <400мс назад
const NULL_STREAK_RESET   = 2;     // сколько null подряд = «код ушёл из кадра»
const PHOTO_TTL_MS        = 8000;  // фото авто-удаляется через 8 сек

// Размер canvas для ZXing-детекции.
// В 9 раз меньше пикселей (vs 1080p) → ZXing в 9 раз быстрее.
// Для качественного анализа по-прежнему используется полный кадр.
const DECODE_W = 640;

// ── Определение GoPro ─────────────────────────────────────────────────────────
function isGoPro(label: string): boolean {
  return /gopro|hero\s*\d+/i.test(label);
}

// ── Препроцессинг ─────────────────────────────────────────────────────────────
function makeGray(data: Uint8ClampedArray): Float32Array {
  const n = data.length / 4;
  const g = new Float32Array(n);
  for (let i = 0; i < n; i++)
    g[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
  return g;
}

function stretchContrast(data: Uint8ClampedArray, gray: Float32Array): void {
  let lo = 255, hi = 0;
  for (const v of gray) { if (v < lo) lo = v; if (v > hi) hi = v; }
  const range = hi - lo || 1;
  for (let i = 0; i < gray.length; i++) {
    const v = Math.round((gray[i] - lo) / range * 255);
    data[i*4] = v; data[i*4+1] = v; data[i*4+2] = v; data[i*4+3] = 255;
  }
}

function sharpenGray(gray: Float32Array, w: number, h: number, data: Uint8ClampedArray): void {
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      const v = Math.max(0, Math.min(255,
        5*gray[i] - gray[(y-1)*w+x] - gray[(y+1)*w+x] - gray[y*w+x-1] - gray[y*w+x+1]
      ));
      data[i*4] = v; data[i*4+1] = v; data[i*4+2] = v; data[i*4+3] = 255;
    }
  }
}

function makeCanvas(data: Uint8ClampedArray, w: number, h: number): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const img = new ImageData(w, h);
  img.data.set(data);
  c.getContext('2d')!.putImageData(img, 0, 0);
  return c;
}

function cropCanvas(src: HTMLCanvasElement, x: number, y: number, w: number, h: number): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  c.getContext('2d')!.drawImage(src, x, y, w, h, 0, 0, w, h);
  return c;
}

function scaleCanvas(src: HTMLCanvasElement, scale: number): HTMLCanvasElement {
  const w = Math.round(src.width * scale), h = Math.round(src.height * scale);
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  c.getContext('2d')!.drawImage(src, 0, 0, w, h);
  return c;
}

// ── Результат декодирования ───────────────────────────────────────────────────
interface DecodeHit {
  text:    string;
  pts:     readonly ResultPoint[] | null;
  offsetX: number;
  offsetY: number;
}

// Простой вызов ZXing без искусственного таймаута.
// ZXing на маленьком canvas (640×360) завершается за 20-100ms,
// поэтому дополнительные ухищрения не нужны.
async function tryDecodeCanvas(
  reader: BrowserDatamatrixCodeReader,
  canvas: HTMLCanvasElement,
  offsetX = 0,
  offsetY = 0,
): Promise<DecodeHit | null> {
  try {
    const r = await (reader as any).decodeFromCanvas(canvas);
    if (r) return {
      text:    r.getText() as string,
      pts:     r.getResultPoints() as readonly ResultPoint[],
      offsetX,
      offsetY,
    };
  } catch {}
  return null;
}

// ── Компонент ─────────────────────────────────────────────────────────────────
export default function Scanner() {
  const videoRef       = useRef<HTMLVideoElement>(null);
  const canvasRef      = useRef<HTMLCanvasElement>(null);          // полный кадр (для анализа)
  const decodeCanvasRef = useRef<HTMLCanvasElement | null>(null);  // маленький (для ZXing)
  const streamRef      = useRef<MediaStream | null>(null);
  const readerRef      = useRef<BrowserDatamatrixCodeReader | null>(null);

  // Циклы (как потоки Python)
  const runningRef     = useRef(false);
  const decodingRef    = useRef(false);
  const rafRef         = useRef<number | null>(null);
  const decodeTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Scan-lock (_last_decoded / _last_decoded_t)
  const lastDecoded     = useRef('');
  const lastDecodedTime = useRef(0);

  // Ref для soundEnabled — чтобы изменение не пересоздавало замыкания
  const soundEnabledRef = useRef(true);

  const [cameras, setCameras]             = useState<MediaDeviceInfo[]>([]);
  const [selectedCamera, setSelectedCamera] = useState('');
  const [cameraLabels, setCameraLabels]   = useState<Record<string, string>>({});
  const [scanning, setScanning]           = useState(false);
  const [currentResult, setCurrentResult] = useState<QualityResult | null>(null);
  const [history, setHistory]             = useState<ScanRecord[]>([]);
  const [cameraError, setCameraError]     = useState('');
  const [soundEnabled, setSoundEnabled]   = useState(true);
  const [activeTab, setActiveTab]         = useState<'scan' | 'history'>('scan');
  const [fps, setFps]                     = useState(0);
  // Реальные параметры подключённой GoPro (null = GoPro не используется)
  const [goProInfo, setGoProInfo]         = useState<{ fps: number; width: number; height: number } | null>(null);
  // Последнее захваченное фото (data URL): хранится PHOTO_TTL_MS мс, затем удаляется
  const [currentPhoto, setCurrentPhoto]  = useState<{ url: string; ts: number } | null>(null);

  const fpsCounter = useRef({ frames: 0, last: Date.now() });

  // Синхронизируем ref с состоянием
  useEffect(() => { soundEnabledRef.current = soundEnabled; }, [soundEnabled]);

  // ── Перечисление камер ─────────────────────────────────────────────────────
  useEffect(() => {
    BrowserDatamatrixCodeReader.listVideoInputDevices().then((devices) => {
      setCameras(devices);
      const labels: Record<string, string> = {};
      devices.forEach(d => { labels[d.deviceId] = d.label || `Камера ${d.deviceId.slice(0, 8)}`; });
      setCameraLabels(labels);

      if (devices.length === 0) return;

      // Приоритет: GoPro → задняя камера → последняя в списке
      const gopro = devices.find(d => isGoPro(d.label));
      const back  = devices.find(d => /back|rear|environment/i.test(d.label));
      setSelectedCamera((gopro ?? back ?? devices[devices.length - 1]).deviceId);
    }).catch(() => {
      setCameraError('Не удалось получить список камер. Разрешите доступ к камере в браузере.');
    });
  }, []);

  // ── ROI из result points с учётом смещения кропа ──────────────────────────
  const computeRoi = useCallback((
    frame: HTMLCanvasElement,
    pts:   readonly ResultPoint[] | null,
    ox: number, oy: number,
  ) => {
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
    const mx = Math.floor(fw * 0.25), my = Math.floor(fh * 0.25);
    return { x: mx, y: my, w: fw - 2 * mx, h: fh - 2 * my };
  }, []);

  // ── Обработка декодирования ────────────────────────────────────────────────
  // decodeFrame — маленький canvas (640×360) из которого ZXing достал код.
  // hit.pts / offsetX / offsetY — в координатах decodeFrame.
  // Для анализа качества используется полный canvasRef (full-res).
  const handleDecoded = useCallback((hit: DecodeHit, decodeFrame: HTMLCanvasElement) => {
    const now = Date.now();
    if (hit.text === lastDecoded.current && now - lastDecodedTime.current < SCAN_LOCK_MS) return;

    lastDecoded.current     = hit.text;
    lastDecodedTime.current = now;
    setTimeout(() => { lastDecoded.current = ''; lastDecodedTime.current = 0; }, SCAN_LOCK_MS);

    const fullCanvas = canvasRef.current!;

    // ROI в координатах decode canvas → масштабируем в full-res
    const roi = computeRoi(decodeFrame, hit.pts, hit.offsetX, hit.offsetY);
    const sx = fullCanvas.width  / (decodeFrame.width  || 1);
    const sy = fullCanvas.height / (decodeFrame.height || 1);
    const fullRoi = {
      x: Math.floor(roi.x * sx),
      y: Math.floor(roi.y * sy),
      w: Math.ceil(roi.w  * sx),
      h: Math.ceil(roi.h  * sy),
    };

    const result = analyzeQuality(fullCanvas, hit.text, fullRoi);
    if (soundEnabledRef.current) playGradeSound(result.overallGrade);

    // Фото — с полного кадра (не с маленького decode canvas)
    let photoUrl: string | undefined;
    try { photoUrl = fullCanvas.toDataURL('image/jpeg', 0.85); } catch {}

    const id = `${now}-${Math.random().toString(36).slice(2)}`;
    setCurrentResult(result);
    setCurrentPhoto(photoUrl ? { url: photoUrl, ts: now } : null);
    setHistory(prev => [{ id, result, photoUrl }, ...prev.slice(0, 49)]);

    if (photoUrl) {
      setTimeout(() => {
        setCurrentPhoto(prev => (prev?.ts === now ? null : prev));
        setHistory(prev => prev.map(r => r.id === id ? { ...r, photoUrl: undefined } : r));
      }, PHOTO_TTL_MS);
    }
  }, [computeRoi]);

  // ── Поток 1: захват кадров (requestAnimationFrame = _capture_loop) ─────────
  // Каждый кадр рисуем в ДВА canvas:
  //   canvasRef      — полный размер видео (для анализа качества и фото)
  //   decodeCanvasRef — DECODE_W×* уменьшенная копия (для быстрого ZXing)
  const startCaptureLoop = useCallback(() => {
    const loop = () => {
      if (!runningRef.current) return;
      const video  = videoRef.current;
      const canvas = canvasRef.current;
      if (video && canvas && video.readyState >= 2) {
        const vw = video.videoWidth  || 640;
        const vh = video.videoHeight || 480;

        // Полный кадр
        canvas.width  = vw;
        canvas.height = vh;
        canvas.getContext('2d')!.drawImage(video, 0, 0);

        // Маленький decode canvas (масштаб сохраняет аспект)
        if (!decodeCanvasRef.current) {
          decodeCanvasRef.current = document.createElement('canvas');
        }
        const dc = decodeCanvasRef.current;
        const dw = DECODE_W;
        const dh = Math.round(vh * (DECODE_W / vw));
        if (dc.width !== dw || dc.height !== dh) {
          dc.width = dw; dc.height = dh;
        }
        dc.getContext('2d')!.drawImage(video, 0, 0, dw, dh);

        fpsCounter.current.frames++;
        const now = Date.now();
        if (now - fpsCounter.current.last >= 1000) {
          setFps(fpsCounter.current.frames);
          fpsCounter.current = { frames: 0, last: now };
        }
      }
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
  }, []);

  // ── Поток 2: декодирование ────────────────────────────────────────────────
  //
  // Ключевая идея — ZXing работает на маленьком canvas (640×360):
  //   • 640×360 = 230k пикселей vs 2M у 1080p → ZXing в ~9 раз быстрее
  //   • На маленьком canvas "fail fast" = 20-80ms (vs 200-500ms на полном)
  //   • Нет нужды в искусственных таймаутах / Promise.race
  //
  // Pipeline (все шаги — на decode canvas):
  //   Шаг 1: полный decode canvas                             (всегда)
  //   Шаг 2: центральная зона 70%                            (если код был недавно)
  //   Шаг 3: контраст-стретч + инверсия + резкость           (если код был недавно)
  //   Шаг 4: масштаб 1.5× центра (мелкий символ)             (если код был недавно)
  //
  // Мгновенный сброс scan-lock:
  //   NULL_STREAK_RESET пропусков подряд → код ушёл → lock снимается немедленно.
  //
  const startDecodeLoop = useCallback((reader: BrowserDatamatrixCodeReader) => {
    if (decodeTimerRef.current) clearInterval(decodeTimerRef.current);

    let nullStreak = 0;

    decodeTimerRef.current = setInterval(async () => {
      if (decodingRef.current || !runningRef.current) return;
      const dc = decodeCanvasRef.current;
      if (!dc || dc.width === 0 || dc.height === 0) return;

      decodingRef.current = true;
      try {
        const { width: dw, height: dh } = dc;
        const codeWasRecent = Date.now() - lastDecodedTime.current < HARD_SEARCH_AFTER_MS;
        let hit: DecodeHit | null = null;

        // Шаг 1: полный decode canvas
        hit = await tryDecodeCanvas(reader, dc);

        if (!hit && codeWasRecent) {
          // Шаг 2: центр 70%
          const m  = 0.15;
          const cx = Math.floor(dw * m),       cy = Math.floor(dh * m);
          const cw = Math.floor(dw * (1-2*m)), ch = Math.floor(dh * (1-2*m));
          if (cw > 20 && ch > 20) {
            hit = await tryDecodeCanvas(reader, cropCanvas(dc, cx, cy, cw, ch), cx, cy);
          }

          // Шаг 3: препроцессинг (маленький canvas = быстро)
          if (!hit) {
            const ctx  = dc.getContext('2d')!;
            const img  = ctx.getImageData(0, 0, dw, dh);
            const gray = makeGray(img.data);

            // 3a: контраст-стретч
            const d1 = new Uint8ClampedArray(img.data);
            stretchContrast(d1, gray);
            hit = await tryDecodeCanvas(reader, makeCanvas(d1, dw, dh));

            // 3b: инверсия (светлые модули на тёмном фоне)
            if (!hit) {
              const d2 = new Uint8ClampedArray(d1);
              for (let i = 0; i < d2.length; i += 4) {
                d2[i] = 255 - d2[i]; d2[i+1] = 255 - d2[i+1]; d2[i+2] = 255 - d2[i+2];
              }
              hit = await tryDecodeCanvas(reader, makeCanvas(d2, dw, dh));
            }

            // 3c: резкость
            if (!hit) {
              const d3 = new Uint8ClampedArray(img.data);
              sharpenGray(gray, dw, dh, d3);
              hit = await tryDecodeCanvas(reader, makeCanvas(d3, dw, dh));
            }
          }

          // Шаг 4: масштаб 1.5× центра (мелкий символ)
          if (!hit) {
            const sm  = 0.20;
            const scx = Math.floor(dw * sm),        scy = Math.floor(dh * sm);
            const scw = Math.floor(dw * (1-2*sm)),  sch = Math.floor(dh * (1-2*sm));
            if (scw > 20 && sch > 20) {
              hit = await tryDecodeCanvas(
                reader, scaleCanvas(cropCanvas(dc, scx, scy, scw, sch), 1.5), scx, scy,
              );
            }
          }
        }

        if (!hit) {
          nullStreak++;
          if (nullStreak >= NULL_STREAK_RESET && lastDecoded.current !== '') {
            lastDecoded.current     = '';
            lastDecodedTime.current = 0;
            nullStreak = 0;
          }
        } else {
          nullStreak = 0;
          handleDecoded(hit, dc);
        }
      } finally {
        decodingRef.current = false;
      }
    }, DECODE_INTERVAL_MS);
  }, [handleDecoded]);

  // ── Остановка всех циклов ──────────────────────────────────────────────────
  const stopAllLoops = useCallback(() => {
    runningRef.current = false;
    if (rafRef.current !== null)         { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    if (decodeTimerRef.current !== null) { clearInterval(decodeTimerRef.current); decodeTimerRef.current = null; }
  }, []);

  const stopScanning = useCallback(() => {
    stopAllLoops();
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setScanning(false);
    setFps(0);
    setGoProInfo(null);
  }, [stopAllLoops]);

  // ── Запуск сканирования ────────────────────────────────────────────────────
  const startScanning = useCallback(async () => {
    if (!selectedCamera) return;
    setCameraError('');
    stopAllLoops();

    try {
      const label  = cameraLabels[selectedCamera] ?? '';
      const goPro  = isGoPro(label);
      let stream: MediaStream | null = null;

      // ── Стратегия подключения ────────────────────────────────────────────
      // GoPro HERO 11 USB webcam: 1080p макс., поддерживает 60fps.
      // Запрашиваем ideal:60 min:30 — если 60 недоступно, получим 30.
      // Обычная веб-камера: 1080p ideal:60.
      // Три уровня fallback на случай ограниченного драйвера.

      const primaryConstraints: MediaTrackConstraints = {
        deviceId: { exact: selectedCamera },
        width:     { ideal: 1920, min: 1280 },
        height:    { ideal: 1080, min:  720 },
        frameRate: { ideal:   60, min:   30 },
      };

      // GoPro часто не сообщает capabilities до открытия потока.
      // Просто запрашиваем 60fps — браузер договорится с драйвером.
      const fallback720: MediaTrackConstraints = {
        deviceId: { exact: selectedCamera },
        width:    { ideal: 1280 },
        height:   { ideal:  720 },
        frameRate:{ ideal:   60, min: 1 },
      };

      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: primaryConstraints, audio: false });
      } catch {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ video: fallback720, audio: false });
        } catch {
          stream = await navigator.mediaDevices.getUserMedia({ video: { deviceId: selectedCamera }, audio: false });
        }
      }

      // Читаем реальные параметры после подключения (без попыток applyConstraints)
      if (goPro) {
        const s = stream.getVideoTracks()[0].getSettings();
        setGoProInfo({
          fps:    Math.round(s.frameRate ?? 30),
          width:  s.width  ?? 1920,
          height: s.height ?? 1080,
        });
      } else {
        setGoProInfo(null);
      }

      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }

      // ZXing reader с TRY_HARDER — создаём один раз, держим всё время
      if (!readerRef.current) {
        const hints = new Map<DecodeHintType, any>();
        hints.set(DecodeHintType.TRY_HARDER, true);
        readerRef.current = new BrowserDatamatrixCodeReader(hints);
      }

      runningRef.current = true;
      fpsCounter.current = { frames: 0, last: Date.now() };
      startCaptureLoop();
      startDecodeLoop(readerRef.current);

      setScanning(true);
    } catch (e: any) {
      setCameraError(`Ошибка запуска камеры: ${e?.message || e}`);
      setScanning(false);
    }
  }, [selectedCamera, cameraLabels, stopAllLoops, startCaptureLoop, startDecodeLoop]);

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
          {goProInfo && (
            <span className="text-xs font-semibold bg-blue-500/20 text-blue-400 border border-blue-500/30 px-2 py-0.5 rounded">
              GoPro {goProInfo.width}×{goProInfo.height}@{goProInfo.fps}fps
            </span>
          )}
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
                {cameras.length === 0 && <option key="none" value="">Нет доступных камер</option>}
                {cameras.map(c => (
                  <option key={c.deviceId} value={c.deviceId}>
                    {isGoPro(c.label) ? `📷 ${c.label}` : (c.label || `Камера ${c.deviceId.slice(0, 8)}`)}
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

                    {/* ── Фото снимка с countdown-баром ── */}
                    {currentPhoto && (
                      <div className="relative rounded-lg overflow-hidden border border-border/40">
                        <img
                          src={currentPhoto.url}
                          alt="Снимок DataMatrix"
                          className="w-full object-contain max-h-48 bg-black"
                        />
                        {/* Полупрозрачный оверлей "авто-удаление" */}
                        <div className="absolute top-1.5 right-1.5 bg-black/70 text-white/70 text-[10px] px-1.5 py-0.5 rounded">
                          авто-удаление
                        </div>
                        {/* Countdown: линия снизу съёживается слева направо */}
                        <div
                          key={currentPhoto.ts}
                          className="absolute bottom-0 left-0 w-full h-[3px] bg-primary photo-ttl-bar"
                          style={{ '--photo-ttl': `${PHOTO_TTL_MS}ms` } as React.CSSProperties}
                        />
                      </div>
                    )}

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

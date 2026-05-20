import { useEffect, useRef, useState, useCallback } from 'react';
import { BrowserDatamatrixCodeReader, IScannerControls } from '@zxing/browser';
import { DecodeHintType, Result } from '@zxing/library';
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

// ── Препроцессинг кадра на canvas ─────────────────────────────────────────────
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

function sharpen(gray: Float32Array, w: number, h: number): Float32Array {
  const out = new Float32Array(gray.length);
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      const v = 5 * gray[i]
        - gray[(y - 1) * w + x]
        - gray[(y + 1) * w + x]
        - gray[y * w + x - 1]
        - gray[y * w + x + 1];
      out[i] = Math.max(0, Math.min(255, v));
    }
  }
  return out;
}

function makeGray(data: Uint8ClampedArray): Float32Array {
  const n = data.length / 4;
  const g = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    g[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
  }
  return g;
}

function applyGray(data: Uint8ClampedArray, gray: Float32Array): void {
  for (let i = 0; i < gray.length; i++) {
    const v = gray[i];
    data[i * 4] = v; data[i * 4 + 1] = v; data[i * 4 + 2] = v; data[i * 4 + 3] = 255;
  }
}

function invert(data: Uint8ClampedArray): void {
  for (let i = 0; i < data.length; i += 4) {
    data[i] = 255 - data[i];
    data[i + 1] = 255 - data[i + 1];
    data[i + 2] = 255 - data[i + 2];
  }
}

// ── Создание вариантов для декодирования ──────────────────────────────────────
function makePreprocessedCanvases(
  src: HTMLCanvasElement
): HTMLCanvasElement[] {
  const w = src.width, h = src.height;
  if (w === 0 || h === 0) return [];

  const srcCtx = src.getContext('2d')!;
  const orig    = srcCtx.getImageData(0, 0, w, h);
  const gray    = makeGray(orig.data);

  const variants: { data: Uint8ClampedArray; width: number; height: number }[] = [];

  // 1. Контраст-стретч (серый)
  const d1 = new Uint8ClampedArray(orig.data);
  stretchContrast(d1, gray);
  variants.push({ data: d1, width: w, height: h });

  // 2. Контраст-стретч + инверсия
  const d2 = new Uint8ClampedArray(d1);
  invert(d2);
  variants.push({ data: d2, width: w, height: h });

  // 3. Резкость
  const sharpGray = sharpen(gray, w, h);
  const d3 = new Uint8ClampedArray(orig.data);
  applyGray(d3, sharpGray);
  variants.push({ data: d3, width: w, height: h });

  // 4. Центральный ROI (70%) с контраст-стретчем
  const cx = Math.floor(w * 0.15), cy = Math.floor(h * 0.15);
  const cw = w - 2 * cx,           ch = h - 2 * cy;
  const roiCtx = document.createElement('canvas');
  roiCtx.width = cw; roiCtx.height = ch;
  const rc = roiCtx.getContext('2d')!;
  rc.drawImage(src, cx, cy, cw, ch, 0, 0, cw, ch);
  const roiImg = rc.getImageData(0, 0, cw, ch);
  const roiGray = makeGray(roiImg.data);
  const d4 = new Uint8ClampedArray(roiImg.data);
  stretchContrast(d4, roiGray);
  variants.push({ data: d4, width: cw, height: ch });

  // 5. Масштаб 1.5× оригинала
  const sw = Math.round(w * 1.5), sh = Math.round(h * 1.5);
  const sc = document.createElement('canvas');
  sc.width = sw; sc.height = sh;
  const scc = sc.getContext('2d')!;
  scc.drawImage(src, 0, 0, sw, sh);
  const si = scc.getImageData(0, 0, sw, sh);
  const sg = makeGray(si.data);
  stretchContrast(si.data, sg);
  variants.push({ data: si.data, width: sw, height: sh });

  return variants.map(({ data, width, height }) => {
    const c = document.createElement('canvas');
    c.width = width; c.height = height;
    const imgData = new ImageData(width, height);
    imgData.data.set(data);
    c.getContext('2d')!.putImageData(imgData, 0, 0);
    return c;
  });
}


export default function Scanner() {
  const videoRef    = useRef<HTMLVideoElement>(null);
  const canvasRef   = useRef<HTMLCanvasElement>(null);
  const readerRef   = useRef<BrowserDatamatrixCodeReader | null>(null);
  const controlsRef = useRef<IScannerControls | null>(null);
  const lastDecoded     = useRef<string>('');
  const lastDecodedTime = useRef<number>(0);
  const preprocessTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [cameras, setCameras]           = useState<MediaDeviceInfo[]>([]);
  const [selectedCamera, setSelectedCamera] = useState<string>('');
  const [scanning, setScanning]         = useState(false);
  const [currentResult, setCurrentResult] = useState<QualityResult | null>(null);
  const [history, setHistory]           = useState<ScanRecord[]>([]);
  const [cameraError, setCameraError]   = useState<string>('');
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [activeTab, setActiveTab]       = useState<'scan' | 'history'>('scan');
  const [fps, setFps]                   = useState(0);

  const fpsCounter = useRef({ frames: 0, last: Date.now() });

  useEffect(() => {
    BrowserDatamatrixCodeReader.listVideoInputDevices().then((devices) => {
      setCameras(devices);
      if (devices.length > 0) {
        const backCamera = devices.find(d =>
          d.label.toLowerCase().includes('back') ||
          d.label.toLowerCase().includes('rear') ||
          d.label.toLowerCase().includes('environment')
        );
        setSelectedCamera(backCamera ? backCamera.deviceId : devices[devices.length - 1].deviceId);
      }
    }).catch(() => {
      setCameraError('Не удалось получить список камер. Разрешите доступ к камере в браузере.');
    });
  }, []);

  const captureFrame = useCallback((): HTMLCanvasElement | null => {
    const video  = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || video.readyState < 2) return null;
    canvas.width  = video.videoWidth  || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0);

    const f = fpsCounter.current;
    f.frames++;
    const now = Date.now();
    if (now - f.last >= 1000) {
      setFps(f.frames);
      f.frames = 0;
      f.last   = now;
    }
    return canvas;
  }, []);

  const handleDecoded = useCallback((text: string, canvas?: HTMLCanvasElement | null) => {
    const now = Date.now();
    if (text === lastDecoded.current && now - lastDecodedTime.current < 1500) return;
    lastDecoded.current     = text;
    lastDecodedTime.current = now;

    // Сброс через 1.5 сек — сразу ищем следующий
    setTimeout(() => {
      lastDecoded.current     = '';
      lastDecodedTime.current = 0;
    }, 1500);

    const frame = canvas ?? captureFrame();
    if (!frame) return;

    const result = analyzeQuality(frame, text);
    if (soundEnabled) playGradeSound(result.overallGrade);
    setCurrentResult(result);
    setHistory(prev => [
      { id: `${now}-${Math.random().toString(36).slice(2)}`, result },
      ...prev.slice(0, 49),
    ]);
  }, [soundEnabled, captureFrame]);

  // ── Параллельный цикл препроцессинга ──────────────────────────────────────
  const startPreprocessLoop = useCallback((reader: BrowserDatamatrixCodeReader) => {
    if (preprocessTimerRef.current) clearInterval(preprocessTimerRef.current);

    preprocessTimerRef.current = setInterval(async () => {
      const canvas = captureFrame();
      if (!canvas) return;

      const variants = makePreprocessedCanvases(canvas);
      for (const variant of variants) {
        try {
          const result = await (reader as any).decodeFromCanvas(variant);
          if (result) {
            handleDecoded(result.getText(), canvas);
            break;
          }
        } catch {
          // нет кода — продолжаем
        }
      }
    }, 120);
  }, [captureFrame, handleDecoded]);

  const stopPreprocessLoop = useCallback(() => {
    if (preprocessTimerRef.current) {
      clearInterval(preprocessTimerRef.current);
      preprocessTimerRef.current = null;
    }
  }, []);

  const startScanning = useCallback(async () => {
    if (!selectedCamera) return;
    setCameraError('');
    try {
      if (controlsRef.current) {
        controlsRef.current.stop();
        controlsRef.current = null;
      }
      stopPreprocessLoop();

      // TRY_HARDER: ищет код в большем количестве позиций
      const hints = new Map<DecodeHintType, any>();
      hints.set(DecodeHintType.TRY_HARDER, true);

      const reader = new BrowserDatamatrixCodeReader(hints, {
        delayBetweenScanAttempts: 50,
        delayBetweenScanSuccess:  1500,
      });
      readerRef.current = reader;

      let stream: MediaStream | null = null;
      try {
        const constraints: any = {
          deviceId: { exact: selectedCamera },
          width:     { ideal: 1920, min: 1280 },
          height:    { ideal: 1080, min: 720 },
          frameRate: { ideal: 60, min: 30 },
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

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }

      // Основной цикл ZXing (оригинальный кадр)
      const controls = await reader.decodeFromStream(
        stream,
        videoRef.current ?? undefined,
        (result: Result | null | undefined) => {
          if (result) handleDecoded(result.getText());
        }
      );
      controlsRef.current = controls;

      // Параллельный цикл с препроцессингом
      startPreprocessLoop(reader);

      setScanning(true);
    } catch (e: any) {
      setCameraError(`Ошибка запуска камеры: ${e?.message || e}`);
      setScanning(false);
    }
  }, [selectedCamera, handleDecoded, startPreprocessLoop, stopPreprocessLoop]);

  const stopScanning = useCallback(() => {
    stopPreprocessLoop();
    if (controlsRef.current) {
      controlsRef.current.stop();
      controlsRef.current = null;
    }
    if (videoRef.current?.srcObject) {
      (videoRef.current.srcObject as MediaStream).getTracks().forEach(t => t.stop());
      videoRef.current.srcObject = null;
    }
    setScanning(false);
  }, [stopPreprocessLoop]);

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

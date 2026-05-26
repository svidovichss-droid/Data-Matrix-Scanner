import { useState, useRef, useCallback } from 'react';
import { BrowserDatamatrixCodeReader } from '@zxing/browser';
import { DecodeHintType } from '@zxing/library';
import { analyzeQuality, QualityResult, gradeColor, gradeLabel, Grade } from '@/lib/qualityAnalysis';

export interface DecodeResult extends QualityResult {
  imageWidth: number;
  imageHeight: number;
  fileName: string;
}

export default function OnlineDecoder() {
  const [result, setResult] = useState<DecodeResult | null>(null);
  const [error, setError] = useState<string>('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const decodeImage = useCallback(async (file: File) => {
    setIsProcessing(true);
    setError('');
    setResult(null);

    try {
      const start = performance.now();
      
      // Создаем reader с TRY_HARDER для лучшего качества декодирования
      const hints = new Map<DecodeHintType, any>();
      hints.set(DecodeHintType.TRY_HARDER, true);
      const reader = new BrowserDatamatrixCodeReader(hints);

      // Декодируем из файла
      const codeResult = await reader.decodeFromImageUrl(URL.createObjectURL(file));
      
      if (!codeResult) {
        throw new Error('DataMatrix код не найден на изображении');
      }

      const text = codeResult.getText();
      const points = codeResult.getResultPoints();

      // Создаем canvas для анализа качества
      const img = await new Promise<HTMLImageElement>((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = reject;
        image.src = URL.createObjectURL(file);
      });

      const canvas = document.createElement('canvas');
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Не удалось получить контекст canvas');
      
      ctx.drawImage(img, 0, 0);

      // Определяем ROI из точек
      let roi: { x: number; y: number; w: number; h: number } | undefined;
      if (points && points.length >= 2) {
        const xs = points.map(p => p.getX());
        const ys = points.map(p => p.getY());
        const minX = Math.min(...xs);
        const maxX = Math.max(...xs);
        const minY = Math.min(...ys);
        const maxY = Math.max(...ys);
        const sw = maxX - minX;
        const sh = maxY - minY;
        
        if (sw > 4 && sh > 4) {
          const margin = Math.max(sw, sh) * 0.25;
          roi = {
            x: Math.max(0, Math.floor(minX - margin)),
            y: Math.max(0, Math.floor(minY - margin)),
            w: Math.min(canvas.width - Math.max(0, Math.floor(minX - margin)), Math.ceil(sw + 2 * margin)),
            h: Math.min(canvas.height - Math.max(0, Math.floor(minY - margin)), Math.ceil(sh + 2 * margin)),
          };
        }
      }

      // Анализируем качество
      const qualityResult = analyzeQuality(canvas, text, roi);
      const analysisTime = performance.now() - start;

      setResult({
        ...qualityResult,
        analysisTimeMs: analysisTime,
        imageWidth: img.width,
        imageHeight: img.height,
        fileName: file.name,
      });

    } catch (e: any) {
      console.error('Ошибка декодирования:', e);
      setError(e?.message || 'Ошибка при декодировании изображения');
    } finally {
      setIsProcessing(false);
    }
  }, []);

  const handleFileSelect = useCallback((file: File) => {
    if (!file.type.startsWith('image/')) {
      setError('Пожалуйста, выберите изображение (PNG, JPG, JPEG, WEBP, GIF)');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError('Размер файла не должен превышать 10 МБ');
      return;
    }
    decodeImage(file);
  }, [decodeImage]);

  const onInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFileSelect(file);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [handleFileSelect]);

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  }, [handleFileSelect]);

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        const file = items[i].getAsFile();
        if (file) {
          handleFileSelect(file);
          break;
        }
      }
    }
  }, [handleFileSelect]);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b border-border/50 bg-card/80 backdrop-blur sticky top-0 z-50 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary/20 flex items-center justify-center">
            <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
            </svg>
          </div>
          <div>
            <h1 className="text-sm font-semibold text-foreground tracking-tight">Онлайн декодер DataMatrix</h1>
            <p className="text-xs text-muted-foreground">Загрузите изображение для декодирования</p>
          </div>
        </div>
      </header>

      <main className="flex-1 flex flex-col lg:flex-row gap-0 overflow-hidden">
        {/* Левая панель - загрузка */}
        <div className="lg:w-[55%] flex flex-col p-6 overflow-y-auto">
          <div
            className={`relative border-2 border-dashed rounded-xl p-8 transition-all cursor-pointer ${
              dragActive 
                ? 'border-primary bg-primary/5 scale-[1.02]' 
                : 'border-border/50 hover:border-primary/50 hover:bg-secondary/50'
            }`}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            onPaste={handlePaste}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                fileInputRef.current?.click();
              }
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={onInputChange}
              className="hidden"
            />
            
            <div className="flex flex-col items-center justify-center gap-4 text-center">
              {isProcessing ? (
                <>
                  <div className="w-16 h-16 rounded-2xl bg-primary/20 flex items-center justify-center animate-pulse">
                    <svg className="w-8 h-8 text-primary animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-foreground">Обработка изображения...</p>
                    <p className="text-xs text-muted-foreground mt-1">Декодирование и анализ качества</p>
                  </div>
                </>
              ) : (
                <>
                  <div className="w-16 h-16 rounded-2xl bg-secondary flex items-center justify-center">
                    <svg className="w-8 h-8 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
                    </svg>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-foreground">
                      Перетащите изображение сюда или нажмите для выбора
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Поддерживаются PNG, JPG, JPEG, WEBP, GIF до 10 МБ
                    </p>
                    <p className="text-xs text-muted-foreground mt-1 opacity-70">
                      Также можно вставить изображение из буфера обмена (Ctrl+V)
                    </p>
                  </div>
                </>
              )}
            </div>
          </div>

          {error && (
            <div className="mt-4 p-4 bg-destructive/10 border border-destructive/30 rounded-lg">
              <div className="flex items-start gap-3">
                <svg className="w-5 h-5 text-destructive flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <div>
                  <p className="text-sm font-medium text-destructive">Ошибка декодирования</p>
                  <p className="text-xs text-destructive/80 mt-1">{error}</p>
                </div>
              </div>
            </div>
          )}

          <canvas ref={canvasRef} className="hidden" />
        </div>

        {/* Правая панель - результат */}
        <div className="lg:w-[45%] flex flex-col border-l border-border/50 overflow-hidden">
          <div className="flex-1 overflow-y-auto p-4">
            {result ? (
              <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-300">
                {/* Общая оценка */}
                <div className="bg-card rounded-xl p-4 border border-border/50">
                  <div className="flex items-center justify-between mb-3">
                    <h2 className="text-sm font-semibold text-foreground">Результат анализа</h2>
                    <span className="text-xs text-muted-foreground">{result.fileName}</span>
                  </div>
                  
                  <div className="flex items-center gap-4">
                    <div 
                      className="w-20 h-20 rounded-2xl flex items-center justify-center text-3xl font-bold text-white shadow-lg"
                      style={{ backgroundColor: gradeColor(result.overallGrade) }}
                    >
                      {result.overallGrade}
                    </div>
                    <div className="flex-1">
                      <p className="text-lg font-semibold text-foreground">{gradeLabel(result.overallGrade)}</p>
                      <p className="text-sm text-muted-foreground">Средний балл: {result.overallScore.toFixed(2)} / 4.0</p>
                      <div className="mt-2 h-2 bg-secondary rounded-full overflow-hidden">
                        <div 
                          className="h-full rounded-full transition-all duration-500"
                          style={{ 
                            width: `${(result.overallScore / 4) * 100}%`,
                            backgroundColor: gradeColor(result.overallGrade)
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Параметры качества */}
                <div className="bg-card rounded-xl p-4 border border-border/50">
                  <h3 className="text-sm font-semibold text-foreground mb-3">Параметры качества</h3>
                  <div className="space-y-3">
                    {result.parameters.map((param, idx) => (
                      <div key={idx} className="flex items-center justify-between py-2 border-b border-border/30 last:border-0">
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono font-semibold text-primary">{param.name}</span>
                            <span className="text-xs text-muted-foreground">{param.nameRu}</span>
                          </div>
                          <div className="flex items-center gap-2 mt-1">
                            <div className="flex-1 h-1.5 bg-secondary rounded-full overflow-hidden">
                              <div 
                                className="h-full rounded-full"
                                style={{ 
                                  width: `${param.value * 100}%`,
                                  backgroundColor: gradeColor(param.grade)
                                }}
                              />
                            </div>
                            <span 
                              className="text-xs font-bold px-1.5 py-0.5 rounded"
                              style={{ 
                                backgroundColor: `${gradeColor(param.grade)}20`,
                                color: gradeColor(param.grade)
                              }}
                            >
                              {param.grade}
                            </span>
                          </div>
                        </div>
                        <div className="text-right ml-3 min-w-[60px]">
                          <span className="text-xs font-mono text-foreground">{(param.value * 100).toFixed(1)}%</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Декодированные данные */}
                <div className="bg-card rounded-xl p-4 border border-border/50">
                  <h3 className="text-sm font-semibold text-foreground mb-2">Декодированные данные</h3>
                  <div className="bg-secondary/50 rounded-lg p-3 break-all">
                    <p className="text-sm font-mono text-foreground">{result.decodedData}</p>
                  </div>
                  <button
                    onClick={() => navigator.clipboard.writeText(result.decodedData)}
                    className="mt-2 text-xs text-primary hover:text-primary/80 flex items-center gap-1 transition-colors"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                    Копировать
                  </button>
                </div>

                {/* Информация об изображении */}
                <div className="bg-secondary/50 rounded-xl p-3 flex items-center justify-between text-xs text-muted-foreground">
                  <span>Размер: {result.imageWidth} × {result.imageHeight} px</span>
                  <span>Время анализа: {result.analysisTimeMs.toFixed(1)} мс</span>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-center gap-3 h-full">
                <div className="w-16 h-16 rounded-2xl bg-secondary flex items-center justify-center">
                  <svg className="w-8 h-8 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5z" />
                  </svg>
                </div>
                <p className="text-sm text-muted-foreground">Результат появится здесь</p>
                <p className="text-xs text-muted-foreground/60">Загрузите изображение с DataMatrix кодом</p>
              </div>
            )}
          </div>
        </div>
      </main>

      <footer className="border-t border-border/50 py-2 px-6 flex items-center justify-between text-xs text-muted-foreground/60">
        <span>ГОСТ Р 57302-2016 · ISO/IEC 15415:2011</span>
        <span>Онлайн декодер DataMatrix</span>
      </footer>
    </div>
  );
}

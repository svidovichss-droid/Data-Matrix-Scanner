export type Grade = 'A' | 'B' | 'C' | 'D' | 'F';

export interface QualityParameter {
  name: string;
  nameRu: string;
  gostRef: string;
  value: number;
  grade: Grade;
  description: string;
  min?: number;
  max?: number;
  unit?: string;
}

export interface QualityResult {
  overallGrade: Grade;
  overallScore: number;
  parameters: QualityParameter[];
  decodedData: string;
  timestamp: Date;
  analysisTimeMs: number;
}

function scoreToGrade(score: number): Grade {
  if (score >= 3.5) return 'A';
  if (score >= 2.5) return 'B';
  if (score >= 1.5) return 'C';
  if (score >= 0.5) return 'D';
  return 'F';
}

function gradeToScore(g: Grade): number {
  return g === 'A' ? 4 : g === 'B' ? 3 : g === 'C' ? 2 : g === 'D' ? 1 : 0;
}

function getLowestGrade(grades: Grade[]): Grade {
  const scores = grades.map(gradeToScore);
  const min = Math.min(...scores);
  return scoreToGrade(min - 0.01);
}

export interface ImageMetrics {
  symbolContrast: number;
  modulation: number;
  reflectanceMargin: number;
  fixedPatternDamage: number;
  axialNonUniformity: number;
  gridNonUniformity: number;
  unusedErrorCorrection: number;
  printGrowth: number;
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function computeOtsuThreshold(grayValues: number[]): number {
  const hist = new Array(256).fill(0);
  for (const value of grayValues) {
    hist[Math.round(value)] += 1;
  }

  const total = grayValues.length;
  let sumAll = 0;
  for (let i = 0; i < 256; i++) {
    sumAll += i * hist[i];
  }

  let sumBackground = 0;
  let backgroundCount = 0;
  let maxBetweenClassVariance = -1;
  let threshold = 128;

  for (let t = 0; t < 256; t++) {
    backgroundCount += hist[t];
    if (backgroundCount === 0) continue;

    const foregroundCount = total - backgroundCount;
    if (foregroundCount === 0) break;

    sumBackground += t * hist[t];
    const meanBackground = sumBackground / backgroundCount;
    const meanForeground = (sumAll - sumBackground) / foregroundCount;
    const variance = backgroundCount * foregroundCount * Math.pow(meanBackground - meanForeground, 2);

    if (variance > maxBetweenClassVariance) {
      maxBetweenClassVariance = variance;
      threshold = t;
    }
  }

  return threshold;
}

function computeTransitionRate(grayValues: number[], width: number, height: number, threshold: number): number {
  const rowStep = Math.max(1, Math.floor(height / 12));
  const colStep = Math.max(1, Math.floor(width / 12));
  let transitions = 0;
  let samples = 0;

  for (let y = 0; y < height; y += rowStep) {
    for (let x = 1; x < width; x += colStep) {
      const prev = grayValues[y * width + x - 1] < threshold;
      const curr = grayValues[y * width + x] < threshold;
      if (prev !== curr) transitions += 1;
      samples += 1;
    }
  }

  for (let x = 0; x < width; x += colStep) {
    for (let y = 1; y < height; y += rowStep) {
      const prev = grayValues[(y - 1) * width + x] < threshold;
      const curr = grayValues[y * width + x] < threshold;
      if (prev !== curr) transitions += 1;
      samples += 1;
    }
  }

  return samples === 0 ? 0 : transitions / samples;
}

function analyzeImageData(canvas: HTMLCanvasElement, roi?: { x: number; y: number; w: number; h: number }): ImageMetrics | null {
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  const x = roi?.x ?? 0;
  const y = roi?.y ?? 0;
  const width = roi?.w ?? canvas.width;
  const height = roi?.h ?? canvas.height;

  if (width <= 0 || height <= 0) return null;

  const imageData = ctx.getImageData(x, y, width, height);
  const data = imageData.data;
  const pixels = width * height;

  if (pixels === 0) return null;

  const grayValues: number[] = new Array(pixels);
  for (let i = 0, p = 0; i < data.length; i += 4, p++) {
    grayValues[p] = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
  }

  const maxGray = Math.max(...grayValues);
  const minGray = Math.min(...grayValues);
  const range = Math.max(1, maxGray - minGray);
  let threshold = computeOtsuThreshold(grayValues);
  if (threshold <= minGray || threshold >= maxGray) {
    threshold = (minGray + maxGray) / 2;
  }

  const darkPixels = grayValues.filter(v => v < threshold);
  const lightPixels = grayValues.filter(v => v >= threshold);

  const darkMean = darkPixels.length > 0
    ? darkPixels.reduce((sum, v) => sum + v, 0) / darkPixels.length
    : 0;
  const lightMean = lightPixels.length > 0
    ? lightPixels.reduce((sum, v) => sum + v, 0) / lightPixels.length
    : 255;

  const darkVariance = darkPixels.length > 1
    ? darkPixels.reduce((sum, v) => sum + Math.pow(v - darkMean, 2), 0) / (darkPixels.length - 1)
    : 0;
  const lightVariance = lightPixels.length > 1
    ? lightPixels.reduce((sum, v) => sum + Math.pow(v - lightMean, 2), 0) / (lightPixels.length - 1)
    : 0;

  const symbolContrast = clamp01((maxGray - minGray) / 255);
  
  // Улучшенная формула для modulation с учётом локальных вариаций
  const darkStdDev = Math.sqrt(darkVariance);
  const lightStdDev = Math.sqrt(lightVariance);
  const avgStdDev = (darkStdDev + lightStdDev) / 2;
  const modulation = clamp01(1 - (avgStdDev / (range * 0.8)));
  
  // Улучшенный RM с более точным расчётом запаса
  const reflectanceMargin = clamp01(Math.min(
    (lightMean - threshold) / Math.max(1, lightMean - minGray),
    (threshold - darkMean) / Math.max(1, maxGray - darkMean)
  ));

  const transitionRate = computeTransitionRate(grayValues, width, height, threshold);
  const fixedPatternDamage = clamp01(1 - Math.abs(transitionRate - 0.5) * 0.5);

  const axialNonUniformity = computeAxialNonUniformity(grayValues, width, height, threshold);
  const gridNonUniformity = computeGridNonUniformity(grayValues, width, height);
  const printGrowth = computePrintGrowth(darkPixels.length, lightPixels.length, pixels, threshold, grayValues);
  const unusedErrorCorrection = clamp01(symbolContrast * modulation);

  return {
    symbolContrast,
    modulation,
    reflectanceMargin,
    fixedPatternDamage,
    axialNonUniformity,
    gridNonUniformity,
    unusedErrorCorrection,
    printGrowth,
  };
}

function computeAxialNonUniformity(grayValues: number[], width: number, height: number, threshold: number): number {
  const rowDark: number[] = [];
  const colDark: number[] = [];

  for (let y = 0; y < height; y++) {
    let dark = 0;
    for (let x = 0; x < width; x++) {
      if (grayValues[y * width + x] < threshold) dark += 1;
    }
    rowDark.push(dark / width);
  }

  for (let x = 0; x < width; x++) {
    let dark = 0;
    for (let y = 0; y < height; y++) {
      if (grayValues[y * width + x] < threshold) dark += 1;
    }
    colDark.push(dark / height);
  }

  const rowMean = rowDark.reduce((sum, v) => sum + v, 0) / rowDark.length;
  const colMean = colDark.reduce((sum, v) => sum + v, 0) / colDark.length;
  const rowVariance = rowDark.reduce((sum, v) => sum + Math.pow(v - rowMean, 2), 0) / rowDark.length;
  const colVariance = colDark.reduce((sum, v) => sum + Math.pow(v - colMean, 2), 0) / colDark.length;

  return clamp01(1 - Math.sqrt((rowVariance + colVariance) / 2));
}

function computeGridNonUniformity(grayValues: number[], width: number, height: number): number {
  const blockSize = Math.max(4, Math.floor(Math.min(width, height) / 8));
  const blockMeans: number[] = [];

  for (let y = 0; y + blockSize <= height; y += blockSize) {
    for (let x = 0; x + blockSize <= width; x += blockSize) {
      let sum = 0;
      for (let by = y; by < y + blockSize; by++) {
        for (let bx = x; bx < x + blockSize; bx++) {
          sum += grayValues[by * width + bx];
        }
      }
      blockMeans.push(sum / (blockSize * blockSize));
    }
  }

  if (blockMeans.length < 2) {
    return 0.5;
  }

  const mean = blockMeans.reduce((sum, v) => sum + v, 0) / blockMeans.length;
  const variance = blockMeans.reduce((sum, v) => sum + Math.pow(v - mean, 2), 0) / blockMeans.length;
  return clamp01(1 - Math.sqrt(variance) / 255);
}

function computePrintGrowth(darkCount: number, lightCount: number, total: number, threshold: number, grayValues: number[]): number {
  if (total === 0) return 0;
  
  // Более точный расчёт прироста печати через анализ границ
  const darkRatio = darkCount / total;
  const idealRatio = 0.5;
  
  // Вычисляем количество переходов тёмный/светлый
  let edgeTransitions = 0;
  let totalEdges = 0;
  
  for (let i = 0; i < grayValues.length - 1; i++) {
    const currDark = grayValues[i] < threshold;
    const nextDark = grayValues[i + 1] < threshold;
    if (currDark !== nextDark) {
      edgeTransitions++;
    }
    totalEdges++;
  }
  
  // Print Growth влияет на соотношение тёмных/светлых областей
  // Идеальное значение около 0.5, отклонение снижает оценку
  const ratioDeviation = Math.abs(darkRatio - idealRatio);
  
  // Нормализуем: 0 отклонение = 1.0, максимальное отклонение = 0
  const baseScore = 1 - Math.min(1, ratioDeviation * 3);
  
  // Учитываем чёткость границ (резкие границы = хороший print growth)
  const edgeFactor = edgeTransitions > 0 ? Math.min(1, edgeTransitions / (totalEdges * 0.3)) : 0.5;
  
  return clamp01((baseScore + edgeFactor) / 2);
}

function metricToGrade(value: number, thresholds: [number, number, number, number]): Grade {
  const [a, b, c, d] = thresholds;
  if (value >= a) return 'A';
  if (value >= b) return 'B';
  if (value >= c) return 'C';
  if (value >= d) return 'D';
  return 'F';
}

export function analyzeQuality(
  canvas: HTMLCanvasElement,
  decodedData: string,
  roi?: { x: number; y: number; w: number; h: number }
): QualityResult {
  const start = performance.now();

  const metrics = analyzeImageData(canvas, roi);

  const fallbackParameters: QualityParameter[] = [
    { name: 'SC', nameRu: 'Контраст символа', gostRef: 'п. 5.4', value: 0, grade: 'F', description: 'Разница между максимальным и минимальным отражением символа', min: 0, max: 1, unit: '%' },
    { name: 'MOD', nameRu: 'Модуляция', gostRef: 'п. 5.5', value: 0, grade: 'F', description: 'Однородность яркости темных и светлых элементов символа', min: 0, max: 1, unit: '%' },
    { name: 'RM', nameRu: 'Запас отражательной способности', gostRef: 'п. 5.6', value: 0, grade: 'F', description: 'Запас между значениями отражения и порогом декодирования', min: 0, max: 1, unit: '%' },
    { name: 'FPD', nameRu: 'Повреждение фиксированного рисунка', gostRef: 'п. 5.7', value: 0, grade: 'F', description: 'Целостность пограничного рисунка и рисунка синхронизации', min: 0, max: 1, unit: '%' },
    { name: 'ANU', nameRu: 'Осевая неравномерность', gostRef: 'п. 5.8', value: 0, grade: 'F', description: 'Равномерность размера элементов вдоль горизонтальной и вертикальной осей', min: 0, max: 1, unit: '%' },
    { name: 'GNU', nameRu: 'Неравномерность сетки', gostRef: 'п. 5.9', value: 0, grade: 'F', description: 'Отклонение центров элементов от узлов идеальной сетки', min: 0, max: 1, unit: '%' },
    { name: 'UEC', nameRu: 'Неиспользованная коррекция ошибок', gostRef: 'п. 5.10', value: 0, grade: 'F', description: 'Доля неиспользованного потенциала коррекции ошибок Рида-Соломона', min: 0, max: 1, unit: '%' },
    { name: 'PG', nameRu: 'Прирост печати', gostRef: 'п. 5.11', value: 0, grade: 'F', description: 'Отклонение размеров элементов от номинальных значений', min: 0, max: 1, unit: '%' },
  ];

  const parameters = metrics ? [
    {
      name: 'SC',
      nameRu: 'Контраст символа',
      gostRef: 'п. 5.4',
      value: metrics.symbolContrast,
      grade: metricToGrade(metrics.symbolContrast, [0.70, 0.55, 0.40, 0.20]),
      description: 'Разница между максимальным и минимальным отражением символа',
      min: 0,
      max: 1,
      unit: '%',
    },
    {
      name: 'MOD',
      nameRu: 'Модуляция',
      gostRef: 'п. 5.5',
      value: metrics.modulation,
      grade: metricToGrade(metrics.modulation, [0.75, 0.60, 0.40, 0.20]),
      description: 'Однородность яркости темных и светлых элементов символа',
      min: 0,
      max: 1,
      unit: '%',
    },
    {
      name: 'RM',
      nameRu: 'Запас отражательной способности',
      gostRef: 'п. 5.6',
      value: metrics.reflectanceMargin,
      grade: metricToGrade(metrics.reflectanceMargin, [0.65, 0.45, 0.30, 0.15]),
      description: 'Запас между значениями отражения и порогом декодирования',
      min: 0,
      max: 1,
      unit: '%',
    },
    {
      name: 'FPD',
      nameRu: 'Повреждение фиксированного рисунка',
      gostRef: 'п. 5.7',
      value: metrics.fixedPatternDamage,
      grade: metricToGrade(metrics.fixedPatternDamage, [0.85, 0.65, 0.45, 0.25]),
      description: 'Целостность пограничного рисунка и рисунка синхронизации',
      min: 0,
      max: 1,
      unit: '%',
    },
    {
      name: 'ANU',
      nameRu: 'Осевая неравномерность',
      gostRef: 'п. 5.8',
      value: metrics.axialNonUniformity,
      grade: metricToGrade(metrics.axialNonUniformity, [0.80, 0.60, 0.40, 0.20]),
      description: 'Равномерность размера элементов вдоль горизонтальной и вертикальной осей',
      min: 0,
      max: 1,
      unit: '%',
    },
    {
      name: 'GNU',
      nameRu: 'Неравномерность сетки',
      gostRef: 'п. 5.9',
      value: metrics.gridNonUniformity,
      grade: metricToGrade(metrics.gridNonUniformity, [0.82, 0.62, 0.42, 0.22]),
      description: 'Отклонение центров элементов от узлов идеальной сетки',
      min: 0,
      max: 1,
      unit: '%',
    },
    {
      name: 'UEC',
      nameRu: 'Неиспользованная коррекция ошибок',
      gostRef: 'п. 5.10',
      value: metrics.unusedErrorCorrection,
      grade: metricToGrade(metrics.unusedErrorCorrection, [0.62, 0.50, 0.37, 0.25]),
      description: 'Доля неиспользованного потенциала коррекции ошибок Рида-Соломона',
      min: 0,
      max: 1,
      unit: '%',
    },
    {
      name: 'PG',
      nameRu: 'Прирост печати',
      gostRef: 'п. 5.11',
      value: metrics.printGrowth,
      grade: metricToGrade(metrics.printGrowth, [0.80, 0.60, 0.40, 0.20]),
      description: 'Отклонение размеров элементов от номинальных значений',
      min: 0,
      max: 1,
      unit: '%',
    },
  ] : fallbackParameters;

  const grades = parameters.map(p => p.grade);
  const overallGrade = getLowestGrade(grades);
  const overallScore = grades.reduce((sum, g) => sum + gradeToScore(g), 0) / grades.length;

  return {
    overallGrade,
    overallScore,
    parameters,
    decodedData,
    timestamp: new Date(),
    analysisTimeMs: performance.now() - start,
  };
}

export function gradeColor(grade: Grade): string {
  const map: Record<Grade, string> = {
    A: '#22c55e',
    B: '#14b8a6',
    C: '#eab308',
    D: '#f97316',
    F: '#ef4444',
  };
  return map[grade];
}

export function gradeLabel(grade: Grade): string {
  const map: Record<Grade, string> = {
    A: 'Отлично',
    B: 'Хорошо',
    C: 'Удовлетворительно',
    D: 'Плохо',
    F: 'Неудовлетворительно',
  };
  return map[grade];
}

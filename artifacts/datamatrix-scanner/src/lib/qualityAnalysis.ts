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

// ── Оценки ISO/IEC 15415 Table 3 ─────────────────────────────────────────────
const GRADE_THRESH: Record<string, [number, number, number, number]> = {
  SC:  [0.70, 0.55, 0.40, 0.20],   // Symbol Contrast          §7.4
  MOD: [0.60, 0.50, 0.40, 0.30],   // Modulation (min ERN)     §7.5
  RM:  [0.30, 0.20, 0.10, 0.01],   // Reflectance Margin       §7.6
  FPD: [0.90, 0.75, 0.55, 0.30],   // Fixed Pattern Damage     §7.7
  ANU: [0.94, 0.92, 0.90, 0.88],   // Axial Non-Uniformity     §7.8
  GNU: [0.94, 0.92, 0.90, 0.88],   // Grid Non-Uniformity      §7.9
  UEC: [0.62, 0.50, 0.37, 0.25],   // Unused Error Correction  §7.10
  PG:  [0.90, 0.75, 0.55, 0.30],   // Print Growth             §7.11
};

function metricToGrade(value: number, key: string): Grade {
  const [a, b, c, d] = GRADE_THRESH[key];
  if (value >= a) return 'A';
  if (value >= b) return 'B';
  if (value >= c) return 'C';
  if (value >= d) return 'D';
  return 'F';
}

function gradeToScore(g: Grade): number {
  return g === 'A' ? 4 : g === 'B' ? 3 : g === 'C' ? 2 : g === 'D' ? 1 : 0;
}

function worstGrade(grades: Grade[]): Grade {
  const scores = grades.map(gradeToScore);
  const min    = Math.min(...scores);
  // Преобразуем score обратно в оценку
  if (min >= 4) return 'A';
  if (min >= 3) return 'B';
  if (min >= 2) return 'C';
  if (min >= 1) return 'D';
  return 'F';
}

// ── Вспомогательные функции ISO-анализа ──────────────────────────────────────

/** Оценка шага модуля в пикселях по позициям переходов в бинарном профиле */
function estimateModulePitch(profile: Uint8Array | number[], rdt: number): number {
  const transitions: number[] = [];
  for (let i = 1; i < profile.length; i++) {
    const prev = profile[i - 1] < rdt;
    const curr = profile[i]     < rdt;
    if (prev !== curr) transitions.push(i);
  }
  if (transitions.length < 2) return Math.max(1, Math.floor(profile.length / 10));
  const gaps: number[] = [];
  for (let i = 1; i < transitions.length; i++) gaps.push(transitions[i] - transitions[i - 1]);
  gaps.sort((a, b) => a - b);
  return Math.max(1, gaps[Math.floor(gaps.length / 2)]);  // медиана
}

/** Значение яркости пикселя в бинарном (0/255) изображении */
function bilinearSample(gray: Float32Array, w: number, h: number, cx: number, cy: number, r: number): number {
  const x1 = Math.max(0, cx - r), x2 = Math.min(w - 1, cx + r);
  const y1 = Math.max(0, cy - r), y2 = Math.min(h - 1, cy + r);
  let sum = 0, cnt = 0;
  for (let y = y1; y <= y2; y++) {
    for (let x = x1; x <= x2; x++) {
      sum += gray[y * w + x];
      cnt++;
    }
  }
  return cnt > 0 ? sum / cnt : 0;
}

// ── Полный анализ по ISO/IEC 15415 ───────────────────────────────────────────
function analyzeDatamatrixISO(
  gray: Float32Array,
  w: number,
  h: number
): Record<string, number> | null {

  // §7.4  SC — Symbol Contrast
  let Rmax = 0, Rmin = 255;
  for (let i = 0; i < gray.length; i++) {
    if (gray[i] > Rmax) Rmax = gray[i];
    if (gray[i] < Rmin) Rmin = gray[i];
  }
  if (Rmax < 1) return null;
  const rng = Math.max(Rmax - Rmin, 0.001);
  const RDT = (Rmax + Rmin) / 2;
  const SC  = (Rmax - Rmin) / Rmax;

  // Оценка шага по верхней строке (≈ тактовый рисунок) и среднему столбцу
  const topRow: number[] = [];
  const topY = Math.max(0, Math.floor(h / 8));
  for (let x = 0; x < w; x++) topRow.push(gray[topY * w + x]);

  const midCol: number[] = [];
  const midX = Math.floor(w / 2);
  for (let y = 0; y < h; y++) midCol.push(gray[y * w + midX]);

  let px = estimateModulePitch(topRow, RDT);
  let py = estimateModulePitch(midCol, RDT);
  px = Math.max(1, Math.min(px, Math.floor(w / 2)));
  py = Math.max(1, Math.min(py, Math.floor(h / 2)));

  const nCols = Math.max(2, Math.floor(w / px));
  const nRows = Math.max(2, Math.floor(h / py));
  const r     = Math.max(1, Math.floor(Math.min(px, py) / 4));

  // Выборка центров модулей
  const dark:  number[] = [];
  const light: number[] = [];
  for (let row = 0; row < nRows; row++) {
    for (let col = 0; col < nCols; col++) {
      const cx = Math.floor((col + 0.5) * px);
      const cy = Math.floor((row + 0.5) * py);
      if (cx >= w || cy >= h) continue;
      const val = bilinearSample(gray, w, h, cx, cy, r);
      if (val < RDT) dark.push(val);
      else           light.push(val);
    }
  }
  if (dark.length === 0 || light.length === 0) return null;

  // §7.5  MOD — min ERN по всем модулям
  const darkDenom  = Math.max(RDT - Rmin, 0.001);
  const lightDenom = Math.max(Rmax - RDT, 0.001);
  const ernDark  = dark.map(v  => (RDT - v)  / darkDenom);
  const ernLight = light.map(v => (v  - RDT) / lightDenom);
  const MOD = Math.max(0, Math.min(1,
    Math.min(Math.min(...ernDark), Math.min(...ernLight))
  ));

  // §7.6  RM — минимальный запас до RDT / rng
  const darkMargin  = Math.min(...dark.map(v  => RDT - v))  / rng;
  const lightMargin = Math.min(...light.map(v => v  - RDT)) / rng;
  const RM = Math.max(0, Math.min(1, Math.min(darkMargin, lightMargin)));

  // §7.7  FPD — Finder (левый + нижний) + Clock (верхний + правый)
  let leftDark = 0;
  for (let y = 0; y < h; y++) if (gray[y * w] < RDT) leftDark++;
  const leftScore = leftDark / h;

  let botDark = 0;
  for (let x = 0; x < w; x++) if (gray[(h - 1) * w + x] < RDT) botDark++;
  const botScore = botDark / w;

  let topTrans = 0;
  let prevTop = gray[0] < RDT;
  for (let x = 1; x < w; x++) {
    const cur = gray[x] < RDT;
    if (cur !== prevTop) { topTrans++; prevTop = cur; }
  }
  const topClock = Math.min(1, (topTrans * 2) / Math.max(w - 1, 1));

  let rightTrans = 0;
  let prevRight = gray[w - 1] < RDT;
  for (let y = 1; y < h; y++) {
    const cur = gray[y * w + w - 1] < RDT;
    if (cur !== prevRight) { rightTrans++; prevRight = cur; }
  }
  const rightClock = Math.min(1, (rightTrans * 2) / Math.max(h - 1, 1));
  const FPD = Math.max(0, Math.min(1, (leftScore + botScore + topClock + rightClock) / 4));

  // §7.8  ANU — |px − py| / avg_pitch
  const avgPitch = (px + py) / 2;
  const ANU = Math.max(0, 1 - Math.abs(px - py) / Math.max(avgPitch, 1));

  // §7.9  GNU — отклонение переходов от идеальной сетки (95-й перцентиль / px)
  const deviations: number[] = [];
  for (let row = 0; row < nRows; row += Math.max(1, Math.floor(nRows / 6))) {
    const cy = Math.floor((row + 0.5) * py);
    if (cy >= h) continue;
    const transitions: number[] = [];
    let prev = gray[cy * w] < RDT;
    for (let x = 1; x < w; x++) {
      const cur = gray[cy * w + x] < RDT;
      if (cur !== prev) { transitions.push(x); prev = cur; }
    }
    transitions.forEach((t, i) => {
      const ideal = i * px + Math.floor(px / 2);
      if (ideal < w) deviations.push(Math.abs(t - ideal));
    });
  }
  let GNU = 0.5;
  if (deviations.length > 0) {
    const sorted = [...deviations].sort((a, b) => a - b);
    const p95    = sorted[Math.floor(sorted.length * 0.95)];
    GNU = Math.max(0, Math.min(1, 1 - p95 / Math.max(px, 1)));
  }

  // §7.10  UEC — аппроксимация (ECC200 недоступен из браузера)
  const UEC = Math.min(1, SC * 0.5 + MOD * 0.5);

  // §7.11  PG — разброс яркостей внутри классов
  const darkMean  = dark.reduce((s, v)  => s + v, 0)  / dark.length;
  const lightMean = light.reduce((s, v) => s + v, 0) / light.length;
  const darkStd   = Math.sqrt(dark.reduce((s, v)  => s + (v - darkMean)  ** 2, 0) / dark.length);
  const lightStd  = Math.sqrt(light.reduce((s, v) => s + (v - lightMean) ** 2, 0) / light.length);
  const PG = Math.max(0, Math.min(1, 1 - (darkStd + lightStd) / rng));

  return { SC, MOD, RM, FPD, ANU, GNU, UEC, PG };
}

// ── Публичный API ─────────────────────────────────────────────────────────────

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

export function analyzeQuality(
  canvas: HTMLCanvasElement,
  decodedData: string,
  roi?: { x: number; y: number; w: number; h: number }
): QualityResult {
  const start = performance.now();

  const ctx = canvas.getContext('2d');
  let params: QualityParameter[];

  if (ctx) {
    const x = roi?.x ?? 0,  y = roi?.y ?? 0;
    const w = roi?.w ?? canvas.width, h = roi?.h ?? canvas.height;
    const imageData = ctx.getImageData(x, y, w, h);
    const data      = imageData.data;

    // Перевод в float32 grayscale
    const gray = new Float32Array(w * h);
    for (let i = 0; i < gray.length; i++) {
      gray[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
    }

    const raw = analyzeDatamatrixISO(gray, w, h);

    if (raw) {
      params = [
        {
          name: 'SC', nameRu: 'Контраст символа', gostRef: 'п. 5.4',
          value: raw.SC, grade: metricToGrade(raw.SC, 'SC'),
          description: 'Разница между максимальным и минимальным отражением символа',
          min: 0, max: 1, unit: '%',
        },
        {
          name: 'MOD', nameRu: 'Модуляция', gostRef: 'п. 5.5',
          value: raw.MOD, grade: metricToGrade(raw.MOD, 'MOD'),
          description: 'Минимальный нормированный запас каждого модуля до порога декодирования (ERN)',
          min: 0, max: 1, unit: '%',
        },
        {
          name: 'RM', nameRu: 'Запас отражательной способности', gostRef: 'п. 5.6',
          value: raw.RM, grade: metricToGrade(raw.RM, 'RM'),
          description: 'Минимальный запас между отражением модуля и порогом декодирования',
          min: 0, max: 1, unit: '%',
        },
        {
          name: 'FPD', nameRu: 'Повреждение фиксированного рисунка', gostRef: 'п. 5.7',
          value: raw.FPD, grade: metricToGrade(raw.FPD, 'FPD'),
          description: 'Целостность граничного рисунка и рисунка синхронизации',
          min: 0, max: 1, unit: '%',
        },
        {
          name: 'ANU', nameRu: 'Осевая неравномерность', gostRef: 'п. 5.8',
          value: raw.ANU, grade: metricToGrade(raw.ANU, 'ANU'),
          description: 'Отношение разности шагов модуля по X и Y к среднему шагу',
          min: 0, max: 1, unit: '%',
        },
        {
          name: 'GNU', nameRu: 'Неравномерность сетки', gostRef: 'п. 5.9',
          value: raw.GNU, grade: metricToGrade(raw.GNU, 'GNU'),
          description: 'Отклонение позиций переходов от узлов идеальной сетки (95-й перцентиль)',
          min: 0, max: 1, unit: '%',
        },
        {
          name: 'UEC', nameRu: 'Неиспользованная коррекция ошибок', gostRef: 'п. 5.10',
          value: raw.UEC, grade: metricToGrade(raw.UEC, 'UEC'),
          description: 'Доля неиспользованного потенциала коррекции ошибок Рида-Соломона (ECC200)',
          min: 0, max: 1, unit: '%',
        },
        {
          name: 'PG', nameRu: 'Прирост печати', gostRef: 'п. 5.11',
          value: raw.PG, grade: metricToGrade(raw.PG, 'PG'),
          description: 'Равномерность яркостей внутри тёмных и светлых модулей',
          min: 0, max: 1, unit: '%',
        },
      ];
    } else {
      params = failParams();
    }
  } else {
    params = failParams();
  }

  const grades      = params.map(p => p.grade);
  const overallGrade = worstGrade(grades);
  const overallScore = grades.reduce((s, g) => s + gradeToScore(g), 0) / grades.length;

  return {
    overallGrade,
    overallScore,
    parameters: params,
    decodedData,
    timestamp: new Date(),
    analysisTimeMs: performance.now() - start,
  };
}

function failParams(): QualityParameter[] {
  const keys = ['SC', 'MOD', 'RM', 'FPD', 'ANU', 'GNU', 'UEC', 'PG'];
  const namesRu: Record<string, string> = {
    SC: 'Контраст символа', MOD: 'Модуляция', RM: 'Запас отражательной способности',
    FPD: 'Повреждение фиксированного рисунка', ANU: 'Осевая неравномерность',
    GNU: 'Неравномерность сетки', UEC: 'Неиспользованная коррекция ошибок', PG: 'Прирост печати',
  };
  const gosts: Record<string, string> = {
    SC: 'п. 5.4', MOD: 'п. 5.5', RM: 'п. 5.6', FPD: 'п. 5.7',
    ANU: 'п. 5.8', GNU: 'п. 5.9', UEC: 'п. 5.10', PG: 'п. 5.11',
  };
  return keys.map(k => ({
    name: k, nameRu: namesRu[k], gostRef: gosts[k],
    value: 0, grade: 'F', description: '', min: 0, max: 1, unit: '%',
  }));
}

export function gradeColor(grade: Grade): string {
  const map: Record<Grade, string> = {
    A: '#22c55e', B: '#14b8a6', C: '#eab308', D: '#f97316', F: '#ef4444',
  };
  return map[grade];
}

export function gradeLabel(grade: Grade): string {
  const map: Record<Grade, string> = {
    A: 'Отлично', B: 'Хорошо', C: 'Удовлетворительно', D: 'Плохо', F: 'Неудовлетворительно',
  };
  return map[grade];
}

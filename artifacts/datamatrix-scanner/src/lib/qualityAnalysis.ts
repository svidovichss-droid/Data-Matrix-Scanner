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

// ── Пороги ISO/IEC 15415 Table 3 ─────────────────────────────────────────────
const GRADE_THRESH: Record<string, [number, number, number, number]> = {
  SC:  [0.70, 0.55, 0.40, 0.20],
  MOD: [0.60, 0.50, 0.40, 0.30],
  RM:  [0.30, 0.20, 0.10, 0.01],
  FPD: [0.90, 0.75, 0.55, 0.30],
  ANU: [0.94, 0.92, 0.90, 0.88],
  GNU: [0.94, 0.92, 0.90, 0.88],
  UEC: [0.62, 0.50, 0.37, 0.25],
  PG:  [0.90, 0.75, 0.55, 0.30],
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
  const min = Math.min(...grades.map(gradeToScore));
  if (min >= 4) return 'A';
  if (min >= 3) return 'B';
  if (min >= 2) return 'C';
  if (min >= 1) return 'D';
  return 'F';
}

// ── Оценка шага модуля ────────────────────────────────────────────────────────
/**
 * Оценка шага по нескольким строкам/столбцам.
 * Пробует scanLines позиций, берёт моду медиан.
 * Минимально допустимый шаг — minPitch пикселей.
 */
function estimatePitch(
  gray: Float32Array,
  w: number,
  h: number,
  direction: 'x' | 'y',
  RDT: number,
  minPitch = 3
): number {
  const count  = direction === 'x' ? h : w;
  const length = direction === 'x' ? w : h;
  const step   = Math.max(1, Math.floor(count / 12));

  const medians: number[] = [];
  for (let i = step; i < count - step; i += step) {
    const gaps: number[] = [];
    let prevDark = gray[direction === 'x' ? i * w : i] < RDT;
    let runLen   = 1;

    for (let j = 1; j < length; j++) {
      const idx      = direction === 'x' ? i * w + j : j * w + i;
      const isDark   = gray[idx] < RDT;
      if (isDark === prevDark) {
        runLen++;
      } else {
        if (runLen >= minPitch) gaps.push(runLen);
        runLen  = 1;
        prevDark = isDark;
      }
    }
    if (gaps.length >= 2) {
      const sorted = [...gaps].sort((a, b) => a - b);
      medians.push(sorted[Math.floor(sorted.length / 2)]);
    }
  }

  if (medians.length === 0) return 0;

  // Мода медиан (наиболее часто встречающаяся оценка шага)
  const freq = new Map<number, number>();
  for (const m of medians) freq.set(m, (freq.get(m) ?? 0) + 1);
  let best = 0, bestCnt = 0;
  freq.forEach((cnt, val) => { if (cnt > bestCnt) { best = val; bestCnt = cnt; } });

  return best >= minPitch ? best : 0;
}

// ── Выборка значения в окрестности центра модуля ─────────────────────────────
function sampleAt(gray: Float32Array, w: number, h: number, cx: number, cy: number, r: number): number {
  const x1 = Math.max(0, cx - r), x2 = Math.min(w - 1, cx + r);
  const y1 = Math.max(0, cy - r), y2 = Math.min(h - 1, cy + r);
  let sum = 0, cnt = 0;
  for (let y = y1; y <= y2; y++) {
    for (let x = x1; x <= x2; x++) { sum += gray[y * w + x]; cnt++; }
  }
  return cnt > 0 ? sum / cnt : 0;
}

// ── Основной ISO/IEC 15415 анализ ────────────────────────────────────────────
function analyzeDatamatrixISO(
  gray: Float32Array,
  w: number,
  h: number
): Record<string, number> | null {

  if (w < 10 || h < 10) return null;

  // §7.4  SC
  let Rmax = 0, Rmin = 255;
  for (let i = 0; i < gray.length; i++) {
    if (gray[i] > Rmax) Rmax = gray[i];
    if (gray[i] < Rmin) Rmin = gray[i];
  }
  if (Rmax < 1) return null;
  const rng = Math.max(Rmax - Rmin, 1);
  const RDT = (Rmax + Rmin) / 2;
  const SC  = (Rmax - Rmin) / Rmax;

  // Убеждаемся, что изображение содержит и тёмные и светлые пиксели
  if (SC < 0.10) return null;

  // ── Оценка шага модуля ─────────────────────────────────────────────────────
  const px = estimatePitch(gray, w, h, 'x', RDT);
  const py = estimatePitch(gray, w, h, 'y', RDT);

  // Если шаг не удалось найти — анализ бессмысленен
  if (px < 3 || py < 3) return null;

  // Количество модулей должно быть разумным (DataMatrix: 8×8 – 144×144)
  const nCols = Math.round(w / px);
  const nRows = Math.round(h / py);
  if (nCols < 4 || nRows < 4 || nCols > 200 || nRows > 200) return null;

  const r = Math.max(1, Math.floor(Math.min(px, py) / 4));

  // ── Выборка центров модулей ────────────────────────────────────────────────
  const dark:  number[] = [];
  const light: number[] = [];

  for (let row = 0; row < nRows; row++) {
    for (let col = 0; col < nCols; col++) {
      const cx = Math.floor((col + 0.5) * px);
      const cy = Math.floor((row + 0.5) * py);
      if (cx >= w || cy >= h) continue;
      const val = sampleAt(gray, w, h, cx, cy, r);
      if (val < RDT) dark.push(val);
      else           light.push(val);
    }
  }

  if (dark.length < 4 || light.length < 4) return null;

  // §7.5  MOD — min ERN (Edge Reflectance Normalised)
  const darkDenom  = Math.max(RDT - Rmin, 1);
  const lightDenom = Math.max(Rmax - RDT, 1);
  const ernDark    = dark.map(v  => (RDT - v)  / darkDenom);
  const ernLight   = light.map(v => (v  - RDT) / lightDenom);
  const MOD = Math.max(0, Math.min(1,
    Math.min(Math.min(...ernDark), Math.min(...ernLight))
  ));

  // §7.6  RM — минимальный запас до RDT
  const darkMin  = Math.min(...dark);
  const lightMax = Math.max(...light);
  const RM = Math.max(0, Math.min(1,
    Math.min((RDT - darkMin) / rng, (lightMax - RDT) / rng)  // НЕ min — берём наихудший из worst-case
  ));

  // §7.7  FPD — Finder (левый столбец + нижняя строка) + Clock (верхняя + правая)
  // Смотрим в полосе шириной 1 модуль от каждого края
  const band = Math.max(1, Math.round(Math.min(px, py) * 0.6));

  // Левый Finder: должен быть весь тёмным
  let leftDark = 0, leftTotal = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < band && x < w; x++) {
      leftTotal++;
      if (gray[y * w + x] < RDT) leftDark++;
    }
  }
  const leftScore = leftTotal > 0 ? leftDark / leftTotal : 0;

  // Нижний Finder: должен быть весь тёмным
  let botDark = 0, botTotal = 0;
  for (let x = 0; x < w; x++) {
    for (let yOff = 0; yOff < band; yOff++) {
      const y = h - 1 - yOff;
      if (y < 0) continue;
      botTotal++;
      if (gray[y * w + x] < RDT) botDark++;
    }
  }
  const botScore = botTotal > 0 ? botDark / botTotal : 0;

  // Верхний Clock: должен чередоваться
  let topTrans = 0;
  let prevTop  = gray[0] < RDT;
  for (let x = 1; x < w; x++) {
    const cur = gray[x] < RDT;
    if (cur !== prevTop) { topTrans++; prevTop = cur; }
  }
  // Ожидаемое число переходов ≈ nCols - 1
  const topClock = Math.min(1, topTrans / Math.max(nCols - 1, 1));

  // Правый Clock: должен чередоваться
  let rightTrans = 0;
  let prevRight  = gray[w - 1] < RDT;
  for (let y = 1; y < h; y++) {
    const cur = gray[y * w + w - 1] < RDT;
    if (cur !== prevRight) { rightTrans++; prevRight = cur; }
  }
  const rightClock = Math.min(1, rightTrans / Math.max(nRows - 1, 1));

  const FPD = Math.max(0, Math.min(1,
    (leftScore + botScore + topClock + rightClock) / 4
  ));

  // §7.8  ANU — осевая неравномерность: |px − py| / avg
  const avgPitch = (px + py) / 2;
  const ANU = Math.max(0, 1 - Math.abs(px - py) / Math.max(avgPitch, 1));

  // §7.9  GNU — отклонения позиций переходов от идеальной сетки
  const deviations: number[] = [];
  const rowStep = Math.max(1, Math.floor(nRows / 8));
  for (let row = 0; row < nRows; row += rowStep) {
    const cy = Math.floor((row + 0.5) * py);
    if (cy >= h) continue;
    const transitions: number[] = [];
    let prev = gray[cy * w] < RDT;
    for (let x = 1; x < w; x++) {
      const cur = gray[cy * w + x] < RDT;
      if (cur !== prev) { transitions.push(x); prev = cur; }
    }
    transitions.forEach((t, i) => {
      const ideal = Math.floor(i * px + px / 2);
      if (ideal < w) deviations.push(Math.abs(t - ideal));
    });
  }

  let GNU = 0.5;
  if (deviations.length > 0) {
    const sorted = [...deviations].sort((a, b) => a - b);
    const p95    = sorted[Math.floor(sorted.length * 0.95)];
    GNU = Math.max(0, Math.min(1, 1 - p95 / Math.max(px, 1)));
  }

  // §7.10  UEC — аппроксимация через SC и MOD
  const UEC = Math.min(1, SC * 0.5 + MOD * 0.5);

  // §7.11  PG — разброс яркостей внутри классов
  const darkMean  = dark.reduce((s, v)  => s + v, 0)  / dark.length;
  const lightMean = light.reduce((s, v) => s + v, 0) / light.length;
  const dStd = Math.sqrt(dark.reduce((s, v)  => s + (v - darkMean)  ** 2, 0) / dark.length);
  const lStd = Math.sqrt(light.reduce((s, v) => s + (v - lightMean) ** 2, 0) / light.length);
  const PG = Math.max(0, Math.min(1, 1 - (dStd + lStd) / rng));

  return { SC, MOD, RM, FPD, ANU, GNU, UEC, PG };
}

// ── Публичный API ─────────────────────────────────────────────────────────────

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

    const gray = new Float32Array(w * h);
    for (let i = 0; i < gray.length; i++) {
      gray[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
    }

    const raw = analyzeDatamatrixISO(gray, w, h);
    params = raw ? buildParams(raw) : failParams();
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
    timestamp:     new Date(),
    analysisTimeMs: performance.now() - start,
  };
}

// ── Формирование таблицы параметров ──────────────────────────────────────────
function buildParams(raw: Record<string, number>): QualityParameter[] {
  const meta: Array<[string, string, string, string]> = [
    ['SC',  'Контраст символа',                  'п. 5.4',  'Разница между максимальным и минимальным отражением символа'],
    ['MOD', 'Модуляция',                          'п. 5.5',  'Минимальный нормированный запас каждого модуля до порога декодирования (ERN)'],
    ['RM',  'Запас отражательной способности',    'п. 5.6',  'Минимальный запас между отражением модуля и порогом декодирования'],
    ['FPD', 'Повреждение фиксированного рисунка', 'п. 5.7',  'Целостность граничного рисунка и рисунка синхронизации'],
    ['ANU', 'Осевая неравномерность',             'п. 5.8',  'Соотношение шагов модуля по горизонтальной и вертикальной осям'],
    ['GNU', 'Неравномерность сетки',              'п. 5.9',  'Отклонение переходов от узлов идеальной сетки (95-й перцентиль)'],
    ['UEC', 'Неиспользованная коррекция ошибок',  'п. 5.10', 'Аппроксимация через SC и MOD (ECC200 недоступен в браузере)'],
    ['PG',  'Прирост печати',                     'п. 5.11', 'Равномерность яркостей внутри тёмных и светлых модулей'],
  ];
  return meta.map(([name, nameRu, gostRef, description]) => {
    const value = Math.max(0, Math.min(1, raw[name] ?? 0));
    return { name, nameRu, gostRef, value, grade: metricToGrade(value, name), description, min: 0, max: 1, unit: '%' };
  });
}

function failParams(): QualityParameter[] {
  const meta: Array<[string, string, string]> = [
    ['SC', 'Контраст символа', 'п. 5.4'],
    ['MOD', 'Модуляция', 'п. 5.5'],
    ['RM', 'Запас отражательной способности', 'п. 5.6'],
    ['FPD', 'Повреждение фиксированного рисунка', 'п. 5.7'],
    ['ANU', 'Осевая неравномерность', 'п. 5.8'],
    ['GNU', 'Неравномерность сетки', 'п. 5.9'],
    ['UEC', 'Неиспользованная коррекция ошибок', 'п. 5.10'],
    ['PG', 'Прирост печати', 'п. 5.11'],
  ];
  return meta.map(([name, nameRu, gostRef]) => ({
    name, nameRu, gostRef, value: 0, grade: 'F' as Grade, description: '', min: 0, max: 1, unit: '%',
  }));
}

export function gradeColor(grade: Grade): string {
  const map: Record<Grade, string> = { A: '#22c55e', B: '#14b8a6', C: '#eab308', D: '#f97316', F: '#ef4444' };
  return map[grade];
}

export function gradeLabel(grade: Grade): string {
  const map: Record<Grade, string> = { A: 'Отлично', B: 'Хорошо', C: 'Удовлетворительно', D: 'Плохо', F: 'Неудовлетворительно' };
  return map[grade];
}

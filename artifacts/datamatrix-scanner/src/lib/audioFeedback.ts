export type Grade = 'A' | 'B' | 'C' | 'D' | 'F';

let audioCtx: AudioContext | null = null;

function getAudioCtx(): AudioContext {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
  }
  if (audioCtx.state === 'suspended') {
    audioCtx.resume();
  }
  return audioCtx;
}

function beep(
  ctx: AudioContext,
  freq: number,
  t: number,
  dur: number,
  gain = 0.38,
  type: OscillatorType = 'sine',
  freqEnd?: number,
): void {
  const osc = ctx.createOscillator();
  const g   = ctx.createGain();
  osc.connect(g);
  g.connect(ctx.destination);

  osc.type = type;
  osc.frequency.setValueAtTime(freq, t);
  if (freqEnd !== undefined) {
    osc.frequency.linearRampToValueAtTime(freqEnd, t + dur);
  }

  // Быстрая атака, чёткое затухание
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(gain, t + 0.008);
  g.gain.setValueAtTime(gain, t + dur - 0.015);
  g.gain.linearRampToValueAtTime(0, t + dur);

  osc.start(t);
  osc.stop(t + dur + 0.002);
}

export function playGradeSound(grade: Grade): void {
  try {
    const ctx = getAudioCtx();
    const t   = ctx.currentTime;

    if (grade === 'A') {
      // Чистый двойной восходящий сигнал — «отлично»
      beep(ctx, 900,  t,        0.09, 0.38, 'sine');
      beep(ctx, 1320, t + 0.11, 0.13, 0.38, 'sine');

    } else if (grade === 'B') {
      // Хорошо — чуть ниже
      beep(ctx, 780,  t,        0.09, 0.35, 'sine');
      beep(ctx, 1050, t + 0.11, 0.12, 0.35, 'sine');

    } else if (grade === 'C') {
      // Нейтральный двойной — «удовлетворительно»
      beep(ctx, 660, t,        0.10, 0.32, 'triangle');
      beep(ctx, 660, t + 0.17, 0.10, 0.28, 'triangle');

    } else if (grade === 'D') {
      // Нисходящее предупреждение — три тона
      beep(ctx, 680, t,        0.13, 0.30, 'sawtooth');
      beep(ctx, 520, t + 0.17, 0.13, 0.28, 'sawtooth');
      beep(ctx, 380, t + 0.34, 0.16, 0.26, 'sawtooth');

    } else if (grade === 'F') {
      // Аварийная сирена — 4 импульса, по два тона каждый
      for (let i = 0; i < 4; i++) {
        const base = t + i * 0.22;
        beep(ctx, 440, base,        0.09, 0.30, 'sawtooth');
        beep(ctx, 280, base + 0.10, 0.09, 0.28, 'sawtooth');
      }
    }
  } catch {
    // AudioContext недоступен — игнорируем
  }
}

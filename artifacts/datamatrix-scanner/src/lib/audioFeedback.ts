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

function playBeep(ctx: AudioContext, freq: number, duration: number, startTime: number, type: OscillatorType = 'sine', gain = 0.4): void {
  const osc = ctx.createOscillator();
  const gainNode = ctx.createGain();
  osc.connect(gainNode);
  gainNode.connect(ctx.destination);
  osc.type = type;
  osc.frequency.setValueAtTime(freq, startTime);
  gainNode.gain.setValueAtTime(0, startTime);
  gainNode.gain.linearRampToValueAtTime(gain, startTime + 0.01);
  gainNode.gain.setValueAtTime(gain, startTime + duration - 0.02);
  gainNode.gain.linearRampToValueAtTime(0, startTime + duration);
  osc.start(startTime);
  osc.stop(startTime + duration);
}

export function playGradeSound(grade: Grade): void {
  try {
    const ctx = getAudioCtx();
    const now = ctx.currentTime;

    if (grade === 'A') {
      playBeep(ctx, 880, 0.12, now, 'sine', 0.35);
      playBeep(ctx, 1100, 0.15, now + 0.14, 'sine', 0.35);
    } else if (grade === 'B') {
      playBeep(ctx, 780, 0.12, now, 'sine', 0.3);
      playBeep(ctx, 980, 0.15, now + 0.14, 'sine', 0.3);
    } else if (grade === 'C') {
      playBeep(ctx, 660, 0.1, now, 'triangle', 0.3);
      playBeep(ctx, 660, 0.1, now + 0.18, 'triangle', 0.3);
    } else if (grade === 'D') {
      for (let i = 0; i < 4; i++) {
        const t = now + i * 0.25;
        const freq = i % 2 === 0 ? 440 : 380;
        playBeep(ctx, freq, 0.15, t, 'sawtooth', 0.25);
      }
    } else if (grade === 'F') {
      for (let i = 0; i < 8; i++) {
        const t = now + i * 0.18;
        const freq = i % 2 === 0 ? 320 : 200;
        playBeep(ctx, freq, 0.12, t, 'sawtooth', 0.3);
      }
    }
  } catch (e) {
    console.warn('Audio feedback error:', e);
  }
}

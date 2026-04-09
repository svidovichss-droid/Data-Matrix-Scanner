import { QualityResult, gradeColor, gradeLabel, Grade } from '@/lib/qualityAnalysis';

interface Props {
  result: QualityResult;
}

const gradeRing: Record<Grade, string> = {
  A: 'ring-green-500/60 bg-green-500/10',
  B: 'ring-teal-500/60 bg-teal-500/10',
  C: 'ring-yellow-400/60 bg-yellow-400/10',
  D: 'ring-orange-500/60 bg-orange-500/10',
  F: 'ring-red-500/60 bg-red-500/10',
};

const gradeText: Record<Grade, string> = {
  A: 'text-green-400',
  B: 'text-teal-400',
  C: 'text-yellow-400',
  D: 'text-orange-400',
  F: 'text-red-400',
};

export default function GradeDisplay({ result }: Props) {
  const { overallGrade, overallScore } = result;

  const percentage = (overallScore / 4) * 100;

  return (
    <div className={`rounded-xl ring-2 p-5 flex items-center gap-5 ${gradeRing[overallGrade]}`}>
      <div className="flex-shrink-0 flex flex-col items-center">
        <div className={`text-6xl font-black font-mono leading-none ${gradeText[overallGrade]}`}>
          {overallGrade}
        </div>
        <div className="text-xs text-muted-foreground mt-1 text-center">
          {gradeLabel(overallGrade)}
        </div>
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between mb-2">
          <span className="text-sm font-medium text-foreground">Итоговая оценка качества</span>
          <span className="text-sm font-mono text-muted-foreground">{overallScore.toFixed(2)} / 4.0</span>
        </div>
        <div className="h-2.5 bg-secondary rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{
              width: `${percentage}%`,
              background: gradeColor(overallGrade),
            }}
          />
        </div>
        <div className="flex justify-between text-xs text-muted-foreground mt-1">
          <span>F</span>
          <span>D</span>
          <span>C</span>
          <span>B</span>
          <span>A</span>
        </div>
      </div>
    </div>
  );
}

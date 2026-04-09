import { QualityParameter, Grade, gradeColor } from '@/lib/qualityAnalysis';

interface Props {
  parameters: QualityParameter[];
}

const gradeClass: Record<Grade, string> = {
  A: 'text-green-400 bg-green-500/10 border-green-500/30',
  B: 'text-teal-400 bg-teal-500/10 border-teal-500/30',
  C: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/30',
  D: 'text-orange-400 bg-orange-500/10 border-orange-500/30',
  F: 'text-red-400 bg-red-500/10 border-red-500/30',
};

export default function ParameterTable({ parameters }: Props) {
  return (
    <div className="space-y-1.5">
      <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-1">
        Параметры качества (ГОСТ Р 57302-2016)
      </h3>
      <div className="rounded-xl overflow-hidden border border-border/50">
        {parameters.map((param, idx) => (
          <div
            key={param.name}
            className={`flex items-center gap-3 px-3 py-2.5 ${idx !== parameters.length - 1 ? 'border-b border-border/30' : ''} ${idx % 2 === 0 ? 'bg-card' : 'bg-card/50'}`}
          >
            <div className="w-10 flex-shrink-0">
              <span className={`text-xs font-bold border rounded px-1 py-0.5 ${gradeClass[param.grade]}`}>
                {param.grade}
              </span>
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-2">
                <span className="text-xs font-mono font-semibold text-foreground">{param.name}</span>
                <span className="text-xs text-muted-foreground truncate">{param.nameRu}</span>
              </div>
              <div className="mt-1 h-1 bg-secondary rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${param.value * 100}%`,
                    background: gradeColor(param.grade),
                  }}
                />
              </div>
            </div>

            <div className="flex-shrink-0 text-right">
              <div className="text-xs font-mono text-foreground">
                {(param.value * 100).toFixed(1)}%
              </div>
              <div className="text-xs text-muted-foreground/60">{param.gostRef}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

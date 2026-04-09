import { ScanRecord } from '@/pages/Scanner';
import { gradeColor, Grade } from '@/lib/qualityAnalysis';

interface Props {
  history: ScanRecord[];
}

const gradeClass: Record<Grade, string> = {
  A: 'text-green-400',
  B: 'text-teal-400',
  C: 'text-yellow-400',
  D: 'text-orange-400',
  F: 'text-red-400',
};

export default function HistoryLog({ history }: Props) {
  if (history.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center gap-3 px-4">
        <div className="w-12 h-12 rounded-xl bg-secondary flex items-center justify-center">
          <svg className="w-6 h-6 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <p className="text-sm text-muted-foreground">История пуста</p>
        <p className="text-xs text-muted-foreground/60">Результаты сканирования будут здесь</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-border/30">
      {history.map((record) => {
        const { result } = record;
        const grade = result.overallGrade;

        return (
          <div key={record.id} className="px-4 py-3 flex items-center gap-3 hover:bg-secondary/30 transition-colors">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center font-black text-lg font-mono flex-shrink-0 border"
              style={{
                color: gradeColor(grade),
                backgroundColor: gradeColor(grade) + '20',
                borderColor: gradeColor(grade) + '50',
              }}
            >
              {grade}
            </div>

            <div className="flex-1 min-w-0">
              <p className="text-xs font-mono text-foreground truncate">{result.decodedData}</p>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xs text-muted-foreground">
                  {result.timestamp.toLocaleTimeString('ru')}
                </span>
                <span className="text-xs text-muted-foreground">·</span>
                <span className="text-xs text-muted-foreground">
                  {result.analysisTimeMs.toFixed(0)} мс
                </span>
              </div>
            </div>

            <div className="flex-shrink-0 text-right">
              <div className="text-xs font-mono text-muted-foreground">
                {result.overallScore.toFixed(2)}
              </div>
              <div className="flex gap-1 mt-1 justify-end">
                {result.parameters.map(p => (
                  <div
                    key={p.name}
                    className="w-1.5 h-4 rounded-sm"
                    style={{ background: gradeColor(p.grade) }}
                    title={`${p.name}: ${p.grade}`}
                  />
                ))}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

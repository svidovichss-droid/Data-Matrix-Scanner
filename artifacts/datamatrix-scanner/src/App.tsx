import { useState } from 'react';
import Scanner from '@/pages/Scanner';
import OnlineDecoder from '@/pages/OnlineDecoder';

export default function App() {
  const [mode, setMode] = useState<'scanner' | 'decoder'>('scanner');

  return (
    <div className="min-h-screen bg-background">
      {/* Переключатель режимов */}
      <div className="fixed top-4 right-4 z-[100] flex items-center gap-2 bg-card/90 backdrop-blur rounded-lg p-1 shadow-lg border border-border/50">
        <button
          onClick={() => setMode('scanner')}
          className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
            mode === 'scanner'
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          📷 Сканер
        </button>
        <button
          onClick={() => setMode('decoder')}
          className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
            mode === 'decoder'
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          🖼️ Декодер
        </button>
      </div>

      {mode === 'scanner' ? <Scanner /> : <OnlineDecoder />}
    </div>
  );
}

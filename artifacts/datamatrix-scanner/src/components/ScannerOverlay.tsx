interface Props {
  active: boolean;
}

export default function ScannerOverlay({ active }: Props) {
  if (!active) return null;

  return (
    <div className="absolute inset-0 pointer-events-none">
      <div className="absolute inset-[15%] border border-white/10 rounded-sm">
        <div className="crosshair-corner tl" />
        <div className="crosshair-corner tr" />
        <div className="crosshair-corner bl" />
        <div className="crosshair-corner br" />
        <div className="scan-line" />
      </div>

      <div className="absolute bottom-4 left-0 right-0 flex justify-center">
        <div className="flex items-center gap-2 bg-black/60 backdrop-blur rounded-full px-3 py-1.5">
          <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
          <span className="text-xs text-primary font-medium">Сканирование...</span>
        </div>
      </div>
    </div>
  );
}

export default function Spinner() {
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400">
      <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-cyan-400/40 border-t-cyan-300" />
      loading…
    </div>
  );
}
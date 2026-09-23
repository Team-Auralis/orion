import type { ReactNode } from 'react';

const TONES = {
  default: 'text-slate-100',
  good: 'text-emerald-300',
  bad: 'text-rose-300',
  warn: 'text-amber-300',
  cyan: 'text-cyan-300',
} as const;

export default function StatCard({
  label,
  value,
  sub,
  tone = 'default',
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: keyof typeof TONES;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur p-4">
      <div className="text-[11px] uppercase tracking-widest text-slate-400">{label}</div>
      <div className={`mono-num mt-1 text-2xl font-semibold ${TONES[tone]}`}>{value}</div>
      {sub != null && <div className="mt-1 text-xs text-slate-400">{sub}</div>}
    </div>
  );
}
import type { ReactNode } from 'react';

const TONES = {
  slate: 'bg-slate-500/15 text-slate-300',
  cyan: 'bg-cyan-400/15 text-cyan-300',
  blue: 'bg-blue-400/15 text-blue-300',
  green: 'bg-emerald-400/15 text-emerald-300',
  red: 'bg-rose-400/15 text-rose-300',
  amber: 'bg-amber-400/15 text-amber-300',
} as const;

export default function Badge({
  children,
  tone = 'slate',
}: {
  children: ReactNode;
  tone?: keyof typeof TONES;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}
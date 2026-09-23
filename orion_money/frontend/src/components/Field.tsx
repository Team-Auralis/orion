import type { InputHTMLAttributes } from 'react';

export default function Field({
  label,
  hint,
  ...props
}: { label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] uppercase tracking-widest text-slate-400">
        {label}
      </span>
      <input
        className="w-full rounded-lg border border-white/10 bg-deep px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-cyan-400/60"
        {...props}
      />
      {hint != null && <span className="mt-1 block text-[11px] text-slate-500">{hint}</span>}
    </label>
  );
}
import type { ReactNode } from 'react';

/** Shared glass card: rounded-2xl, translucent white, backdrop blur. */
export default function Panel({
  title,
  actions,
  children,
  className = '',
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-2xl border border-white/10 bg-white/5 backdrop-blur p-4 shadow-glow ${className}`}
    >
      {title != null && (
        <header className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-cyan-300/90">
            {title}
          </h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      {children}
    </section>
  );
}
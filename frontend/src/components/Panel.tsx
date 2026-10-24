import type { ReactNode } from "react";

interface PanelProps {
  title: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  testId?: string;
}

/** Bordered terminal panel with a compact title bar. */
export function Panel({ title, right, children, className = "", bodyClassName = "", testId }: PanelProps) {
  return (
    <section
      data-testid={testId}
      className={`flex min-h-0 min-w-0 flex-col overflow-hidden rounded-sm border border-line bg-bg-panel ${className}`}
    >
      <header className="flex h-7 shrink-0 items-center justify-between gap-2 border-b border-line bg-bg-raised/60 px-2.5">
        <h2 className="truncate text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
          {title}
        </h2>
        {right && <div className="flex items-center gap-2 text-[11px] text-ink-muted">{right}</div>}
      </header>
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

import type { ConnectionStatus as Status } from "@/lib/usePriceStream";

const STYLES: Record<Status, { dot: string; label: string }> = {
  connected: { dot: "bg-up shadow-[0_0_6px_#22c55e]", label: "Live" },
  reconnecting: { dot: "bg-accent-yellow shadow-[0_0_6px_#ecad0a] status-pulse", label: "Reconnecting" },
  disconnected: { dot: "bg-down shadow-[0_0_6px_#ef4444]", label: "Disconnected" },
};

export function ConnectionStatus({ status }: { status: Status }) {
  const s = STYLES[status];
  return (
    <div
      data-testid="connection-status"
      data-status={status}
      title={`Price stream: ${status}`}
      className="flex items-center gap-1.5 rounded-sm border border-line px-2 py-1 text-[10.5px] uppercase tracking-wider text-ink-muted"
    >
      <span className={`inline-block h-2 w-2 rounded-full ${s.dot}`} />
      {s.label}
    </div>
  );
}

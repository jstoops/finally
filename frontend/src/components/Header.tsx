import { fmtMoney, fmtPct, fmtSignedMoney, trendClass } from "@/lib/format";
import type { ConnectionStatus as Status } from "@/lib/usePriceStream";
import { ConnectionStatus } from "./ConnectionStatus";

interface HeaderProps {
  totalValue: number | null;
  cash: number | null;
  unrealizedPnl: number | null;
  costBasis: number | null;
  status: Status;
  onReset: () => void;
  resetting: boolean;
}

function Stat({ label, children, testId }: { label: string; children: React.ReactNode; testId?: string }) {
  return (
    <div className="flex flex-col leading-tight">
      <span className="text-[9.5px] font-medium uppercase tracking-[0.16em] text-ink-faint">{label}</span>
      <span data-testid={testId} className="font-mono text-[15px] font-semibold tabular-nums text-ink">
        {children}
      </span>
    </div>
  );
}

export function Header({ totalValue, cash, unrealizedPnl, costBasis, status, onReset, resetting }: HeaderProps) {
  const pnlPct = unrealizedPnl != null && costBasis ? (unrealizedPnl / costBasis) * 100 : null;
  return (
    <header
      data-testid="header"
      className="flex h-12 shrink-0 items-center gap-6 border-b border-line bg-bg-panel px-4"
    >
      <div className="flex items-baseline gap-2">
        <span className="text-[17px] font-bold tracking-tight text-ink">
          Fin<span className="text-accent-yellow">Ally</span>
        </span>
        <span className="hidden text-[10px] uppercase tracking-[0.2em] text-ink-faint lg:inline">
          AI Trading Workstation
        </span>
      </div>

      <div className="h-7 w-px bg-line" />

      <div className="flex items-center gap-6">
        <Stat label="Portfolio Value" testId="total-value">
          {totalValue == null ? "—" : fmtMoney(totalValue)}
        </Stat>
        <Stat label="Cash" testId="cash-balance">
          {cash == null ? "—" : fmtMoney(cash)}
        </Stat>
        <Stat label="Unrealized P&L">
          <span data-testid="unrealized-pnl" className={trendClass(unrealizedPnl)}>
            {unrealizedPnl == null ? "—" : fmtSignedMoney(unrealizedPnl)}
            {pnlPct != null && <span className="ml-1.5 text-[11px] font-medium">{fmtPct(pnlPct)}</span>}
          </span>
        </Stat>
      </div>

      <div className="ml-auto flex items-center gap-3">
        <ConnectionStatus status={status} />
        <button
          type="button"
          data-testid="reset-button"
          onClick={onReset}
          disabled={resetting}
          className="rounded-sm border border-line-strong px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-wider text-ink-muted transition hover:border-down/70 hover:text-down disabled:opacity-50"
        >
          {resetting ? "Resetting…" : "Reset"}
        </button>
      </div>
    </header>
  );
}

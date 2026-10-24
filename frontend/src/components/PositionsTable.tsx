import { fmtMoney, fmtPct, fmtPrice, fmtQty, fmtSignedMoney, trendClass } from "@/lib/format";
import type { Position } from "@/lib/types";
import { Panel } from "./Panel";

interface PositionsTableProps {
  positions: Position[];
  onSelect?: (ticker: string) => void;
}

export function PositionsTable({ positions, onSelect }: PositionsTableProps) {
  const th = "px-2 py-1 font-medium text-right";
  const td = "px-2 py-1.5 text-right font-mono tabular-nums";
  return (
    <Panel
      title="Positions"
      right={<span className="font-mono">{positions.length}</span>}
      testId="positions-table"
      className="flex-1"
      bodyClassName="overflow-auto"
    >
      <table className="w-full border-collapse text-[12px]">
        <thead className="sticky top-0 bg-bg-panel">
          <tr className="border-b border-line text-[9.5px] uppercase tracking-[0.14em] text-ink-faint">
            <th className="px-2.5 py-1 text-left font-medium">Sym</th>
            <th className={th}>Qty</th>
            <th className={th}>Avg Cost</th>
            <th className={th}>Last</th>
            <th className={th}>Mkt Value</th>
            <th className={th}>Unrl P&L</th>
            <th className={`${th} pr-2.5`}>P&L %</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr
              key={p.ticker}
              data-testid={`position-row-${p.ticker}`}
              onClick={() => onSelect?.(p.ticker)}
              className="cursor-pointer border-b border-line/60 hover:bg-bg-hover"
            >
              <td className="px-2.5 py-1.5 font-mono font-semibold text-ink">{p.ticker}</td>
              <td data-testid={`position-qty-${p.ticker}`} className={td}>
                {fmtQty(p.quantity)}
              </td>
              <td data-testid={`position-avg-${p.ticker}`} className={`${td} text-ink-muted`}>
                {fmtPrice(p.avg_cost)}
              </td>
              <td data-testid={`position-price-${p.ticker}`} className={td}>
                {fmtPrice(p.current_price)}
              </td>
              <td className={td}>{fmtMoney(p.market_value)}</td>
              <td data-testid={`position-pnl-${p.ticker}`} className={`${td} ${trendClass(p.unrealized_pnl)}`}>
                {fmtSignedMoney(p.unrealized_pnl)}
              </td>
              <td
                data-testid={`position-pnlpct-${p.ticker}`}
                className={`${td} pr-2.5 ${trendClass(p.unrealized_pnl_percent)}`}
              >
                {fmtPct(p.unrealized_pnl_percent)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!positions.length && (
        <p data-testid="positions-empty" className="p-4 text-center text-[11px] text-ink-faint">
          No open positions.
        </p>
      )}
    </Panel>
  );
}

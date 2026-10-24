"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { fmtPct, fmtPrice, trendClass } from "@/lib/format";
import { changeSinceOpen } from "@/lib/portfolio";
import type { PriceMap, WatchlistEntry } from "@/lib/types";
import { Panel } from "./Panel";
import { Sparkline } from "./Sparkline";

/** How long the flash tint is held before the CSS transition fades it out. */
export const FLASH_HOLD_MS = 120;

/** Returns "up"/"down" briefly whenever `price` changes, then null. */
export function usePriceFlash(price: number | null | undefined) {
  const prev = useRef(price);
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  useEffect(() => {
    const before = prev.current;
    prev.current = price;
    if (price == null || before == null || price === before) return;
    setFlash(price > before ? "up" : "down");
    const t = setTimeout(() => setFlash(null), FLASH_HOLD_MS);
    return () => clearTimeout(t);
  }, [price]);
  return flash;
}

interface RowProps {
  entry: WatchlistEntry;
  price: number | null;
  open: number | null;
  spark: number[];
  selected: boolean;
  onSelect: (ticker: string) => void;
  onRemove: (ticker: string) => void;
}

function WatchlistRow({ entry, price, open, spark, selected, onSelect, onRemove }: RowProps) {
  const t = entry.ticker;
  const flash = usePriceFlash(price);
  const chg = changeSinceOpen(price, open);
  return (
    <tr
      data-testid={`watchlist-row-${t}`}
      data-selected={selected}
      onClick={() => onSelect(t)}
      className={`group cursor-pointer border-b border-line/60 transition-colors hover:bg-bg-hover ${
        selected ? "bg-accent-blue/10 shadow-[inset_2px_0_0_#209dd7]" : ""
      }`}
    >
      <td className="py-1.5 pl-2.5 pr-1 font-mono text-[12.5px] font-semibold text-ink">{t}</td>
      <td className="px-1 text-right">
        <span
          data-testid={`watchlist-price-${t}`}
          className={`price-cell inline-block rounded-sm px-1 py-0.5 font-mono tabular-nums text-ink ${
            flash ? `flash-${flash}` : ""
          }`}
        >
          {fmtPrice(price)}
        </span>
      </td>
      <td
        data-testid={`watchlist-change-${t}`}
        className={`px-1 text-right font-mono text-[11.5px] tabular-nums ${trendClass(chg)}`}
      >
        {fmtPct(chg)}
      </td>
      <td className="px-1.5">
        <Sparkline values={spark} testId={`watchlist-sparkline-${t}`} />
      </td>
      <td className="w-6 pr-1.5 text-right">
        <button
          type="button"
          data-testid={`watchlist-remove-${t}`}
          aria-label={`Remove ${t} from watchlist`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove(t);
          }}
          className="rounded-sm px-1 text-[13px] leading-none text-ink-faint opacity-40 transition hover:bg-down/15 hover:text-down group-hover:opacity-100"
        >
          ×
        </button>
      </td>
    </tr>
  );
}

interface WatchlistProps {
  entries: WatchlistEntry[];
  prices: PriceMap;
  sparklines: Record<string, number[]>;
  selected: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => Promise<void>;
  onRemove: (ticker: string) => Promise<void>;
}

export function Watchlist({ entries, prices, sparklines, selected, onSelect, onAdd, onRemove }: WatchlistProps) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const ticker = input.trim().toUpperCase();
    if (!ticker) return;
    setBusy(true);
    setError(null);
    try {
      await onAdd(ticker);
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (ticker: string) => {
    setError(null);
    try {
      await onRemove(ticker);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Panel title="Watchlist" right={<span className="font-mono">{entries.length}</span>} testId="watchlist" className="h-full" bodyClassName="flex flex-col">
      <form onSubmit={submit} className="flex shrink-0 gap-1.5 border-b border-line p-2">
        <input
          data-testid="watchlist-add-input"
          value={input}
          onChange={(e) => setInput(e.target.value.toUpperCase())}
          placeholder="Add ticker…"
          maxLength={10}
          spellCheck={false}
          autoComplete="off"
          className="min-w-0 flex-1 rounded-sm border border-line bg-bg px-2 py-1 font-mono text-[12px] uppercase text-ink placeholder:normal-case placeholder:text-ink-faint focus:border-accent-blue focus:outline-none"
        />
        <button
          type="submit"
          data-testid="watchlist-add-button"
          disabled={busy || !input.trim()}
          className="rounded-sm bg-accent-blue/90 px-2.5 text-[11px] font-semibold uppercase tracking-wider text-white transition hover:bg-accent-blue disabled:opacity-40"
        >
          Add
        </button>
      </form>
      {error && (
        <div data-testid="watchlist-error" className="shrink-0 border-b border-line bg-down/10 px-2.5 py-1 text-[11px] text-down">
          {error}
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10 bg-bg-panel">
            <tr className="border-b border-line text-[9.5px] uppercase tracking-[0.14em] text-ink-faint">
              <th className="py-1 pl-2.5 text-left font-medium">Sym</th>
              <th className="px-1 text-right font-medium">Last</th>
              <th className="px-1 text-right font-medium">Chg %</th>
              <th className="px-1.5 text-left font-medium">Trend</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => {
              const live = prices[entry.ticker];
              return (
                <WatchlistRow
                  key={entry.ticker}
                  entry={entry}
                  price={live?.price ?? entry.price}
                  open={live?.open_price ?? entry.open_price}
                  spark={sparklines[entry.ticker] ?? []}
                  selected={selected === entry.ticker}
                  onSelect={onSelect}
                  onRemove={remove}
                />
              );
            })}
          </tbody>
        </table>
        {!entries.length && (
          <p className="p-4 text-center text-[11px] text-ink-faint">Watchlist is empty. Add a ticker above.</p>
        )}
      </div>
    </Panel>
  );
}

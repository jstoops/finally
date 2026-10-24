"use client";

import { useEffect, useState } from "react";
import { fmtMoney, fmtPrice, fmtQty } from "@/lib/format";
import type { Side, Trade } from "@/lib/types";

interface TradeBarProps {
  /** Ticker to prefill (e.g. the one selected in the watchlist). */
  presetTicker: string | null;
  onTrade: (ticker: string, quantity: number, side: Side) => Promise<Trade>;
}

export function TradeBar({ presetTicker, onTrade }: TradeBarProps) {
  const [ticker, setTicker] = useState(presetTicker ?? "");
  const [quantity, setQuantity] = useState("");
  const [busy, setBusy] = useState<Side | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (presetTicker) setTicker(presetTicker);
  }, [presetTicker]);

  const submit = async (side: Side) => {
    const t = ticker.trim().toUpperCase();
    const q = Number(quantity);
    setError(null);
    setSuccess(null);
    if (!t) return setError("Enter a ticker.");
    // Range checks (q <= 0 etc.) are left to the server so its 400 message is shown verbatim.
    if (!quantity.trim() || !Number.isFinite(q)) return setError("Enter a quantity.");
    setBusy(side);
    try {
      const trade = await onTrade(t, q, side);
      setSuccess(
        `${trade.side === "buy" ? "Bought" : "Sold"} ${fmtQty(trade.quantity)} ${trade.ticker} @ $${fmtPrice(trade.price)} (${fmtMoney(trade.quantity * trade.price)})`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const input =
    "rounded-sm border border-line bg-bg px-2 py-1.5 font-mono text-[12.5px] text-ink placeholder:text-ink-faint focus:border-accent-blue focus:outline-none";

  return (
    <div data-testid="trade-bar" className="shrink-0 rounded-sm border border-line bg-bg-panel">
      <form
        className="flex flex-wrap items-center gap-2 px-2.5 py-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit("buy");
        }}
      >
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted">Trade</span>
        <input
          data-testid="trade-ticker"
          aria-label="Ticker"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="TICKER"
          maxLength={10}
          spellCheck={false}
          autoComplete="off"
          className={`${input} w-24 uppercase`}
        />
        <input
          data-testid="trade-quantity"
          aria-label="Quantity"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          placeholder="Qty"
          inputMode="decimal"
          type="number"
          min="0"
          step="any"
          className={`${input} w-24`}
        />
        <button
          type="button"
          data-testid="trade-buy"
          disabled={busy !== null}
          onClick={() => submit("buy")}
          className="rounded-sm bg-up/85 px-4 py-1.5 text-[11.5px] font-bold uppercase tracking-wider text-white transition hover:bg-up disabled:opacity-50"
        >
          {busy === "buy" ? "…" : "Buy"}
        </button>
        <button
          type="button"
          data-testid="trade-sell"
          disabled={busy !== null}
          onClick={() => submit("sell")}
          className="rounded-sm bg-down/85 px-4 py-1.5 text-[11.5px] font-bold uppercase tracking-wider text-white transition hover:bg-down disabled:opacity-50"
        >
          {busy === "sell" ? "…" : "Sell"}
        </button>
        <span className="text-[10px] uppercase tracking-wider text-ink-faint">Market · instant fill</span>
      </form>
      {(error || success) && (
        <div
          data-testid={error ? "trade-error" : "trade-success"}
          role={error ? "alert" : "status"}
          className={`border-t border-line px-2.5 py-1 text-[11.5px] ${error ? "bg-down/10 text-down" : "bg-up/10 text-up"}`}
        >
          {error ?? success}
        </div>
      )}
    </div>
  );
}

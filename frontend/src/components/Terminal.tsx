"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { liveValuation } from "@/lib/portfolio";
import type { ChatMessage, Portfolio, Side, Snapshot, WatchlistEntry } from "@/lib/types";
import { usePriceStream } from "@/lib/usePriceStream";
import { ChatPanel } from "./ChatPanel";
import { Header } from "./Header";
import { Heatmap } from "./Heatmap";
import { PnlChart } from "./PnlChart";
import { PositionsTable } from "./PositionsTable";
import { PriceChart } from "./PriceChart";
import { TradeBar } from "./TradeBar";
import { Watchlist } from "./Watchlist";

/** Top-level workstation: owns server state and wires the panels together (PLAN §10 data flow). */
export function Terminal() {
  const { prices, sparklines, status, clearSparklines } = usePriceStream();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [watchlist, setWatchlist] = useState<WatchlistEntry[]>([]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [chatCollapsed, setChatCollapsed] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const localId = useRef(0);

  const refreshPortfolio = useCallback(() => api.portfolio().then(setPortfolio), []);
  const refreshWatchlist = useCallback(() => api.watchlist().then(setWatchlist), []);
  const refreshHistory = useCallback(() => api.portfolioHistory().then(setSnapshots), []);

  const refreshAll = useCallback(async () => {
    try {
      await Promise.all([refreshPortfolio(), refreshWatchlist(), refreshHistory()]);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  }, [refreshPortfolio, refreshWatchlist, refreshHistory]);

  useEffect(() => {
    refreshAll();
    api
      .chatHistory()
      .then(setMessages)
      .catch(() => {});
  }, [refreshAll]);

  // Keep a valid selection: default to the first watchlist ticker.
  useEffect(() => {
    if (!watchlist.length) return;
    if (!selected) setSelected(watchlist[0].ticker);
  }, [watchlist, selected]);

  const live = useMemo(() => (portfolio ? liveValuation(portfolio, prices) : null), [portfolio, prices]);
  const costBasis = useMemo(
    () => portfolio?.positions.reduce((s, p) => s + p.quantity * p.avg_cost, 0) ?? null,
    [portfolio],
  );

  const handleTrade = useCallback(
    async (ticker: string, quantity: number, side: Side) => {
      const res = await api.trade(ticker, quantity, side);
      setPortfolio(res.portfolio);
      refreshHistory().catch(() => {});
      return res.trade;
    },
    [refreshHistory],
  );

  const handleAdd = useCallback(
    async (ticker: string) => {
      const entry = await api.addTicker(ticker);
      await refreshWatchlist();
      setSelected(entry.ticker);
    },
    [refreshWatchlist],
  );

  const handleRemove = useCallback(
    async (ticker: string) => {
      await api.removeTicker(ticker);
      const next = await api.watchlist();
      setWatchlist(next);
      if (selected === ticker) setSelected(next[0]?.ticker ?? null);
    },
    [selected],
  );

  const handleSend = useCallback(
    async (text: string) => {
      const optimistic: ChatMessage = {
        id: `local-${++localId.current}`,
        role: "user",
        content: text,
        actions: null,
        created_at: new Date().toISOString(),
      };
      setMessages((m) => [...m, optimistic]);
      const reply = await api.chat(text);
      setMessages((m) => [...m, reply]);
      if (reply.actions) await refreshAll();
    },
    [refreshAll],
  );

  const handleReset = useCallback(async () => {
    if (!window.confirm("Reset your account? This restores $10,000 cash and clears all positions, trades and chat.")) {
      return;
    }
    setResetting(true);
    try {
      await api.reset();
      setMessages([]);
      clearSparklines();
      setSelected(null);
      await refreshAll();
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setResetting(false);
    }
  }, [clearSparklines, refreshAll]);

  return (
    <div className="flex h-screen min-h-[600px] flex-col overflow-hidden bg-bg">
      <Header
        totalValue={live?.total_value ?? null}
        cash={live?.cash_balance ?? null}
        unrealizedPnl={live?.unrealized_pnl ?? null}
        costBasis={costBasis}
        status={status}
        onReset={handleReset}
        resetting={resetting}
      />
      {loadError && (
        <div data-testid="load-error" className="shrink-0 border-b border-down/40 bg-down/10 px-4 py-1 text-[11.5px] text-down">
          {loadError}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <main className="grid min-h-0 min-w-0 flex-1 grid-cols-1 gap-1.5 overflow-auto p-1.5 lg:grid-cols-[minmax(300px,340px)_minmax(0,1fr)] lg:overflow-hidden">
          <div className="min-h-[420px] lg:min-h-0">
            <Watchlist
              entries={watchlist}
              prices={prices}
              sparklines={sparklines}
              selected={selected}
              onSelect={setSelected}
              onAdd={handleAdd}
              onRemove={handleRemove}
            />
          </div>
          <div className="grid min-h-0 min-w-0 grid-rows-[minmax(280px,1fr)_auto] gap-1.5 lg:grid-rows-[minmax(0,1.05fr)_minmax(0,1fr)]">
            <PriceChart ticker={selected} live={selected ? prices[selected] : undefined} />
            <div className="grid min-h-0 grid-cols-1 gap-1.5 md:grid-cols-2">
              <div className="flex min-h-[260px] min-w-0 flex-col gap-1.5">
                <TradeBar presetTicker={selected} onTrade={handleTrade} />
                <PositionsTable positions={live?.positions ?? []} onSelect={setSelected} />
              </div>
              <div className="grid min-h-[360px] min-w-0 grid-rows-2 gap-1.5 md:min-h-0">
                <Heatmap positions={live?.positions ?? []} onSelect={setSelected} />
                <PnlChart snapshots={snapshots} liveTotal={live?.total_value ?? null} />
              </div>
            </div>
          </div>
        </main>
        <ChatPanel
          messages={messages}
          onSend={handleSend}
          collapsed={chatCollapsed}
          onToggle={() => setChatCollapsed((c) => !c)}
        />
      </div>
    </div>
  );
}

"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { fmtPrice, fmtQty } from "@/lib/format";
import type { ChatActions, ChatMessage } from "@/lib/types";

function ActionList({ actions }: { actions: ChatActions }) {
  const trades = actions.trades ?? [];
  const changes = actions.watchlist_changes ?? [];
  if (!trades.length && !changes.length) return null;
  return (
    <ul className="mt-2 space-y-1">
      {trades.map((t, i) => {
        const ok = t.status === "executed";
        return (
          <li
            key={`t${i}`}
            data-testid="chat-action"
            data-kind="trade"
            data-status={t.status}
            className={`rounded-sm border px-2 py-1 font-mono text-[11px] ${
              ok ? "border-up/40 bg-up/10 text-up" : "border-down/50 bg-down/10 text-down"
            }`}
          >
            <span className="font-bold">{ok ? "✓" : "✕"}</span>{" "}
            <span className="uppercase">{t.side}</span> {fmtQty(t.quantity)} {t.ticker}
            {ok && t.price != null && <> @ ${fmtPrice(t.price)}</>}
            {!ok && <span className="ml-1 font-sans opacity-90">— {t.error ?? "failed"}</span>}
          </li>
        );
      })}
      {changes.map((c, i) => {
        const ok = c.status === "executed";
        return (
          <li
            key={`w${i}`}
            data-testid="chat-action"
            data-kind="watchlist"
            data-status={c.status}
            className={`rounded-sm border px-2 py-1 font-mono text-[11px] ${
              ok ? "border-accent-blue/40 bg-accent-blue/10 text-accent-blue" : "border-down/50 bg-down/10 text-down"
            }`}
          >
            <span className="font-bold">{ok ? "✓" : "✕"}</span> {c.action === "add" ? "Added" : "Removed"} {c.ticker}{" "}
            {c.action === "add" ? "to" : "from"} watchlist
            {!ok && <span className="ml-1 font-sans opacity-90">— {c.error ?? "failed"}</span>}
          </li>
        );
      })}
    </ul>
  );
}

function Message({ m }: { m: ChatMessage }) {
  const user = m.role === "user";
  return (
    <div data-testid="chat-message" data-role={m.role} className={`flex ${user ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[92%] rounded-md px-2.5 py-1.5 text-[12.5px] leading-relaxed ${
          user ? "bg-accent-purple/30 text-ink" : "border border-line bg-bg-raised text-ink"
        }`}
      >
        {!user && (
          <div className="mb-0.5 text-[9.5px] font-semibold uppercase tracking-[0.16em] text-accent-yellow">FinAlly</div>
        )}
        <div className="whitespace-pre-wrap break-words">{m.content}</div>
        {m.actions && <ActionList actions={m.actions} />}
      </div>
    </div>
  );
}

interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (text: string) => Promise<void>;
  collapsed: boolean;
  onToggle: () => void;
}

export function ChatPanel({ messages, onSend, collapsed, onToggle }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, loading, collapsed]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setError(null);
    setLoading(true);
    try {
      await onSend(text);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  if (collapsed) {
    return (
      <aside data-testid="chat-panel" data-collapsed="true" className="flex w-9 shrink-0 flex-col items-center border-l border-line bg-bg-panel">
        <button
          type="button"
          data-testid="chat-toggle"
          onClick={onToggle}
          aria-label="Open AI assistant"
          className="mt-2 flex flex-col items-center gap-2 rounded-sm px-1 py-2 text-ink-muted hover:bg-bg-hover hover:text-accent-yellow"
        >
          <span className="text-[13px]">◂</span>
          <span className="text-[10px] font-semibold uppercase tracking-[0.2em] [writing-mode:vertical-rl]">AI Assistant</span>
        </button>
      </aside>
    );
  }

  return (
    <aside
      data-testid="chat-panel"
      data-collapsed="false"
      className="flex w-[360px] shrink-0 flex-col border-l border-line bg-bg-panel xl:w-[380px]"
    >
      <header className="flex h-9 shrink-0 items-center justify-between border-b border-line px-3">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-accent-yellow shadow-[0_0_6px_#ecad0a]" />
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-ink">AI Assistant</h2>
        </div>
        <button
          type="button"
          data-testid="chat-toggle"
          onClick={onToggle}
          aria-label="Collapse AI assistant"
          className="rounded-sm px-1.5 text-[13px] text-ink-muted hover:bg-bg-hover hover:text-ink"
        >
          ▸
        </button>
      </header>

      <div ref={scrollRef} data-testid="chat-messages" className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-3">
        {!messages.length && !loading && (
          <div className="mt-6 space-y-2 text-center text-[12px] text-ink-faint">
            <p className="text-ink-muted">Ask FinAlly about your portfolio.</p>
            <p>&ldquo;How concentrated am I?&rdquo; · &ldquo;Buy 5 NVDA&rdquo; · &ldquo;Add PYPL to my watchlist&rdquo;</p>
          </div>
        )}
        {messages.map((m) => (
          <Message key={m.id} m={m} />
        ))}
        {loading && (
          <div data-testid="chat-loading" className="flex items-center gap-2 text-[11.5px] text-ink-muted">
            <span className="flex gap-1">
              <span className="typing-dot h-1.5 w-1.5 rounded-full bg-accent-yellow" />
              <span className="typing-dot h-1.5 w-1.5 rounded-full bg-accent-yellow" />
              <span className="typing-dot h-1.5 w-1.5 rounded-full bg-accent-yellow" />
            </span>
            FinAlly is thinking…
          </div>
        )}
      </div>

      {error && (
        <div data-testid="chat-error" role="alert" className="shrink-0 border-t border-down/40 bg-down/10 px-3 py-1.5 text-[11.5px] text-down">
          {error}
        </div>
      )}

      <form onSubmit={submit} className="flex shrink-0 gap-2 border-t border-line p-2.5">
        <input
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Message FinAlly…"
          autoComplete="off"
          className="min-w-0 flex-1 rounded-sm border border-line bg-bg px-2.5 py-1.5 text-[12.5px] text-ink placeholder:text-ink-faint focus:border-accent-purple focus:outline-none"
        />
        <button
          type="submit"
          data-testid="chat-send"
          disabled={loading || !input.trim()}
          className="rounded-sm bg-accent-purple px-3 text-[11px] font-bold uppercase tracking-wider text-white transition hover:brightness-125 disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </aside>
  );
}

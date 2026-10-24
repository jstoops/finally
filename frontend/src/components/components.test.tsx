import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage, Position, WatchlistEntry } from "@/lib/types";
import { tick } from "@/test/mocks";
import { ChatPanel } from "./ChatPanel";
import { ConnectionStatus } from "./ConnectionStatus";
import { Header } from "./Header";
import { Heatmap, pnlTileColor } from "./Heatmap";
import { PositionsTable } from "./PositionsTable";
import { TradeBar } from "./TradeBar";
import { FLASH_HOLD_MS, Watchlist } from "./Watchlist";

const entries: WatchlistEntry[] = [
  { ticker: "AAPL", price: 190, open_price: 189, added_at: "2026-10-09T14:00:00Z" },
  { ticker: "MSFT", price: null, open_price: null, added_at: "2026-10-09T14:00:01Z" },
];

const position = (over: Partial<Position>): Position => ({
  ticker: "AAPL",
  quantity: 10,
  avg_cost: 100,
  current_price: 110,
  market_value: 1100,
  unrealized_pnl: 100,
  unrealized_pnl_percent: 10,
  weight: 0.5,
  ...over,
});

afterEach(() => vi.useRealTimers());

describe("Header and connection status", () => {
  it("shows formatted totals and the connection state", () => {
    render(
      <Header
        totalValue={10234.5}
        cash={8000}
        unrealizedPnl={-12.5}
        costBasis={1000}
        status="connected"
        onReset={() => {}}
        resetting={false}
      />,
    );
    expect(screen.getByTestId("total-value")).toHaveTextContent("$10,234.50");
    expect(screen.getByTestId("cash-balance")).toHaveTextContent("$8,000.00");
    expect(screen.getByTestId("unrealized-pnl")).toHaveTextContent("-$12.50");
    expect(screen.getByTestId("unrealized-pnl")).toHaveClass("text-down");
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "connected");
  });

  it.each([
    ["connected", "Live", "bg-up"],
    ["reconnecting", "Reconnecting", "bg-accent-yellow"],
    ["disconnected", "Disconnected", "bg-down"],
  ] as const)("renders %s as a %s dot", (status, label, color) => {
    render(<ConnectionStatus status={status} />);
    const el = screen.getByTestId("connection-status");
    expect(el).toHaveTextContent(label);
    expect(el.querySelector("span")).toHaveClass(color);
  });

  it("reset button calls onReset", async () => {
    const onReset = vi.fn();
    render(<Header totalValue={1} cash={1} unrealizedPnl={0} costBasis={0} status="connected" onReset={onReset} resetting={false} />);
    await userEvent.click(screen.getByTestId("reset-button"));
    expect(onReset).toHaveBeenCalledOnce();
  });
});

describe("Watchlist", () => {
  const baseProps = {
    entries,
    prices: {},
    sparklines: {},
    selected: "AAPL",
    onSelect: vi.fn(),
    onAdd: vi.fn(async () => {}),
    onRemove: vi.fn(async () => {}),
  };

  it("renders rows with prices, Chg % from open and placeholders", () => {
    render(<Watchlist {...baseProps} prices={{ AAPL: tick("AAPL", 191.5, 189) }} sparklines={{ AAPL: [190, 191, 191.5] }} />);
    expect(screen.getByTestId("watchlist-row-AAPL")).toHaveAttribute("data-selected", "true");
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveTextContent("191.50");
    expect(screen.getByTestId("watchlist-change-AAPL")).toHaveTextContent("+1.32%");
    expect(screen.getByTestId("watchlist-change-AAPL")).toHaveClass("text-up");
    expect(screen.getByTestId("watchlist-price-MSFT")).toHaveTextContent("—");
    expect(screen.getByTestId("watchlist-sparkline-AAPL")).toHaveAttribute("data-points", "3");
    expect(screen.getByTestId("watchlist-sparkline-AAPL").querySelector("polyline")).not.toBeNull();
  });

  it("flashes green on uptick and red on downtick, then clears", () => {
    vi.useFakeTimers();
    const { rerender } = render(<Watchlist {...baseProps} prices={{ AAPL: tick("AAPL", 190) }} />);
    const cell = () => screen.getByTestId("watchlist-price-AAPL");
    expect(cell()).not.toHaveClass("flash-up");

    rerender(<Watchlist {...baseProps} prices={{ AAPL: tick("AAPL", 190.5) }} />);
    expect(cell()).toHaveClass("flash-up");
    act(() => vi.advanceTimersByTime(FLASH_HOLD_MS + 1));
    expect(cell()).not.toHaveClass("flash-up");

    rerender(<Watchlist {...baseProps} prices={{ AAPL: tick("AAPL", 189) }} />);
    expect(cell()).toHaveClass("flash-down");
    act(() => vi.advanceTimersByTime(FLASH_HOLD_MS + 1));
    expect(cell()).not.toHaveClass("flash-down");
  });

  it("does not flash when the price is unchanged", () => {
    const { rerender } = render(<Watchlist {...baseProps} prices={{ AAPL: tick("AAPL", 190) }} />);
    rerender(<Watchlist {...baseProps} prices={{ AAPL: tick("AAPL", 190, 100, 99) }} />);
    expect(screen.getByTestId("watchlist-price-AAPL").className).not.toMatch(/flash-/);
  });

  it("adds a ticker (uppercased) and clears the input", async () => {
    const onAdd = vi.fn(async () => {});
    render(<Watchlist {...baseProps} onAdd={onAdd} />);
    await userEvent.type(screen.getByTestId("watchlist-add-input"), "pypl");
    await userEvent.click(screen.getByTestId("watchlist-add-button"));
    expect(onAdd).toHaveBeenCalledWith("PYPL");
    expect(screen.getByTestId("watchlist-add-input")).toHaveValue("");
  });

  it("shows the server error inline when adding fails", async () => {
    const onAdd = vi.fn(async () => {
      throw new Error("Invalid ticker: 1BAD");
    });
    render(<Watchlist {...baseProps} onAdd={onAdd} />);
    await userEvent.type(screen.getByTestId("watchlist-add-input"), "1BAD{Enter}");
    expect(await screen.findByTestId("watchlist-error")).toHaveTextContent("Invalid ticker: 1BAD");
  });

  it("removes a ticker without selecting the row", async () => {
    const onRemove = vi.fn(async () => {});
    const onSelect = vi.fn();
    render(<Watchlist {...baseProps} onRemove={onRemove} onSelect={onSelect} />);
    await userEvent.click(screen.getByTestId("watchlist-remove-MSFT"));
    expect(onRemove).toHaveBeenCalledWith("MSFT");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("selects a ticker when its row is clicked", async () => {
    const onSelect = vi.fn();
    render(<Watchlist {...baseProps} onSelect={onSelect} />);
    await userEvent.click(screen.getByTestId("watchlist-row-MSFT"));
    expect(onSelect).toHaveBeenCalledWith("MSFT");
  });
});

describe("Positions and heatmap", () => {
  const positions = [
    position({ ticker: "AAPL", weight: 0.6 }),
    position({ ticker: "TSLA", unrealized_pnl: -50, unrealized_pnl_percent: -5, weight: 0.4 }),
  ];

  it("renders the positions table", () => {
    render(<PositionsTable positions={positions} />);
    const row = screen.getByTestId("position-row-AAPL");
    expect(within(row).getByTestId("position-qty-AAPL")).toHaveTextContent("10");
    expect(screen.getByTestId("position-avg-AAPL")).toHaveTextContent("100.00");
    expect(screen.getByTestId("position-price-AAPL")).toHaveTextContent("110.00");
    expect(screen.getByTestId("position-pnl-AAPL")).toHaveTextContent("+$100.00");
    expect(screen.getByTestId("position-pnlpct-TSLA")).toHaveTextContent("-5.00%");
    expect(screen.getByTestId("position-pnlpct-TSLA")).toHaveClass("text-down");
    expect(screen.queryByTestId("positions-empty")).toBeNull();
  });

  it("shows an empty state", () => {
    render(<PositionsTable positions={[]} />);
    expect(screen.getByTestId("positions-empty")).toBeInTheDocument();
    render(<Heatmap positions={[]} />);
    expect(screen.getByTestId("heatmap-empty")).toBeInTheDocument();
  });

  it("renders heatmap tiles colored by P&L and sized by weight", () => {
    render(<Heatmap positions={positions} />);
    const aapl = screen.getByTestId("heatmap-tile-AAPL");
    const tsla = screen.getByTestId("heatmap-tile-TSLA");
    expect(aapl).toHaveAttribute("data-pnl", "up");
    expect(tsla).toHaveAttribute("data-pnl", "down");
    const area = (el: HTMLElement) => parseFloat(el.style.width) * parseFloat(el.style.height);
    expect(area(aapl) / area(tsla)).toBeCloseTo(1.5, 1);
  });

  it("tile color is green for profit, red for loss, neutral when flat", () => {
    const [r1, g1] = pnlTileColor(5).match(/\d+/g)!.map(Number);
    expect(g1).toBeGreaterThan(r1);
    const [r2, g2] = pnlTileColor(-5).match(/\d+/g)!.map(Number);
    expect(r2).toBeGreaterThan(g2);
    expect(pnlTileColor(0)).toBe("rgb(42, 50, 64)");
  });
});

describe("TradeBar", () => {
  const trade = { id: "1", ticker: "AAPL", side: "buy" as const, quantity: 5, price: 190.5, executed_at: "" };

  it("prefills the ticker and submits a buy", async () => {
    const onTrade = vi.fn(async () => trade);
    render(<TradeBar presetTicker="AAPL" onTrade={onTrade} />);
    expect(screen.getByTestId("trade-ticker")).toHaveValue("AAPL");
    await userEvent.type(screen.getByTestId("trade-quantity"), "5");
    await userEvent.click(screen.getByTestId("trade-buy"));
    expect(onTrade).toHaveBeenCalledWith("AAPL", 5, "buy");
    expect(await screen.findByTestId("trade-success")).toHaveTextContent("Bought 5 AAPL @ $190.50");
  });

  it("shows a 400 error inline on sell", async () => {
    const onTrade = vi.fn(async () => {
      throw new Error("Insufficient shares: have 0, need 5");
    });
    render(<TradeBar presetTicker="AAPL" onTrade={onTrade} />);
    await userEvent.type(screen.getByTestId("trade-quantity"), "5");
    await userEvent.click(screen.getByTestId("trade-sell"));
    expect(onTrade).toHaveBeenCalledWith("AAPL", 5, "sell");
    expect(await screen.findByTestId("trade-error")).toHaveTextContent("Insufficient shares");
  });

  it("requires a quantity before calling the API", async () => {
    const onTrade = vi.fn();
    render(<TradeBar presetTicker="AAPL" onTrade={onTrade} />);
    await userEvent.click(screen.getByTestId("trade-buy"));
    expect(onTrade).not.toHaveBeenCalled();
    expect(screen.getByTestId("trade-error")).toBeInTheDocument();
  });
});

describe("ChatPanel", () => {
  const messages: ChatMessage[] = [
    { id: "1", role: "user", content: "Buy 5 NVDA and 50 TSLA", actions: null, created_at: "" },
    {
      id: "2",
      role: "assistant",
      content: "Done.\n\n⚠️ Couldn't buy 50 TSLA: insufficient cash.",
      actions: {
        trades: [
          { ticker: "NVDA", side: "buy", quantity: 5, status: "executed", price: 875.2 },
          { ticker: "TSLA", side: "buy", quantity: 50, status: "failed", error: "Insufficient cash" },
        ],
        watchlist_changes: [{ ticker: "PYPL", action: "add", status: "executed" }],
      },
      created_at: "",
    },
  ];

  it("renders messages and inline actions, failed ones distinct", () => {
    render(<ChatPanel messages={messages} onSend={vi.fn()} collapsed={false} onToggle={() => {}} />);
    const rendered = screen.getAllByTestId("chat-message");
    expect(rendered.map((m) => m.dataset.role)).toEqual(["user", "assistant"]);
    const actions = screen.getAllByTestId("chat-action");
    expect(actions).toHaveLength(3);
    const ok = actions.find((a) => a.textContent?.includes("NVDA"))!;
    const failed = actions.find((a) => a.textContent?.includes("TSLA"))!;
    expect(ok).toHaveAttribute("data-status", "executed");
    expect(ok).toHaveTextContent("@ $875.20");
    expect(ok).toHaveClass("text-up");
    expect(failed).toHaveAttribute("data-status", "failed");
    expect(failed).toHaveTextContent("Insufficient cash");
    expect(failed).toHaveClass("text-down");
    expect(actions[2]).toHaveAttribute("data-kind", "watchlist");
    expect(actions[2]).toHaveTextContent("Added PYPL to watchlist");
  });

  it("shows a loading indicator while waiting and clears it afterwards", async () => {
    let resolve!: () => void;
    const onSend = vi.fn(() => new Promise<void>((r) => (resolve = r)));
    render(<ChatPanel messages={[]} onSend={onSend} collapsed={false} onToggle={() => {}} />);
    await userEvent.type(screen.getByTestId("chat-input"), "hello");
    await userEvent.click(screen.getByTestId("chat-send"));
    expect(onSend).toHaveBeenCalledWith("hello");
    expect(screen.getByTestId("chat-loading")).toBeInTheDocument();
    expect(screen.getByTestId("chat-input")).toHaveValue("");
    await act(async () => resolve());
    expect(screen.queryByTestId("chat-loading")).toBeNull();
  });

  it("shows an error when sending fails", async () => {
    const onSend = vi.fn(async () => {
      throw new Error("AI assistant is not configured.");
    });
    render(<ChatPanel messages={[]} onSend={onSend} collapsed={false} onToggle={() => {}} />);
    fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "hi" } });
    fireEvent.submit(screen.getByTestId("chat-input").closest("form")!);
    await waitFor(() => expect(screen.getByTestId("chat-error")).toHaveTextContent("not configured"));
  });

  it("collapses and expands", async () => {
    const onToggle = vi.fn();
    const { rerender } = render(<ChatPanel messages={[]} onSend={vi.fn()} collapsed={false} onToggle={onToggle} />);
    await userEvent.click(screen.getByTestId("chat-toggle"));
    expect(onToggle).toHaveBeenCalled();
    rerender(<ChatPanel messages={[]} onSend={vi.fn()} collapsed onToggle={onToggle} />);
    expect(screen.getByTestId("chat-panel")).toHaveAttribute("data-collapsed", "true");
    expect(screen.queryByTestId("chat-input")).toBeNull();
  });
});

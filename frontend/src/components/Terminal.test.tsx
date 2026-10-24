import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Portfolio } from "@/lib/types";
import { installEventSource, MockEventSource, mockFetch, tick } from "@/test/mocks";
import { Terminal } from "./Terminal";

vi.mock("lightweight-charts", async () => (await import("@/test/mocks")).lightweightChartsMock());

const emptyPortfolio: Portfolio = { cash_balance: 10000, positions_value: 0, total_value: 10000, unrealized_pnl: 0, positions: [] };
const boughtPortfolio: Portfolio = {
  cash_balance: 9810,
  positions_value: 190,
  total_value: 10000,
  unrealized_pnl: 0,
  positions: [
    { ticker: "AAPL", quantity: 1, avg_cost: 190, current_price: 190, market_value: 190, unrealized_pnl: 0, unrealized_pnl_percent: 0, weight: 1 },
  ],
};
const watchlist = [
  { ticker: "AAPL", price: 190, open_price: 189, added_at: "2026-10-09T14:00:00Z" },
  { ticker: "MSFT", price: 400, open_price: 401, added_at: "2026-10-09T14:00:01Z" },
];

function setup(overrides: Record<string, Parameters<typeof mockFetch>[0][string]> = {}) {
  let portfolio = emptyPortfolio;
  return mockFetch({
    "GET /api/portfolio": () => ({ body: portfolio }),
    "GET /api/watchlist": () => ({ body: { tickers: watchlist } }),
    "GET /api/portfolio/history": () => ({ body: { snapshots: [{ total_value: 10000, recorded_at: "2026-10-09T14:00:00Z" }] } }),
    "GET /api/chat/history": () => ({ body: { messages: [] } }),
    "GET /api/prices/AAPL/history": () => ({ body: { ticker: "AAPL", points: [{ timestamp: 1, price: 190 }] } }),
    "GET /api/prices/MSFT/history": () => ({ body: { ticker: "MSFT", points: [] } }),
    "POST /api/portfolio/trade": () => {
      portfolio = boughtPortfolio;
      return {
        body: {
          trade: { id: "t", ticker: "AAPL", side: "buy", quantity: 1, price: 190, executed_at: "" },
          portfolio: boughtPortfolio,
        },
      };
    },
    "POST /api/chat": () => {
      portfolio = boughtPortfolio;
      return {
        body: {
          id: "a1",
          role: "assistant",
          content: "Buying 1 share of AAPL.",
          actions: { trades: [{ ticker: "AAPL", side: "buy", quantity: 1, status: "executed", price: 190 }] },
          created_at: "",
        },
      };
    },
    "POST /api/reset": () => {
      portfolio = emptyPortfolio;
      return { body: { status: "ok" } };
    },
    ...overrides,
  });
}

const calls = (fetchMock: ReturnType<typeof setup>, key: string) =>
  fetchMock.mock.calls.filter(([url, init]) => `${init?.method ?? "GET"} ${String(url)}` === key).length;

describe("Terminal data flow", () => {
  beforeEach(() => installEventSource());
  afterEach(() => vi.unstubAllGlobals());

  it("loads initial state and selects the first ticker", async () => {
    setup();
    render(<Terminal />);
    expect(await screen.findByTestId("watchlist-row-AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("cash-balance")).toHaveTextContent("$10,000.00");
    expect(screen.getByTestId("total-value")).toHaveTextContent("$10,000.00");
    await waitFor(() => expect(screen.getByTestId("main-chart-ticker")).toHaveTextContent("AAPL"));
    expect(screen.getByTestId("pnl-chart")).toHaveAttribute("data-points", "1");
  });

  it("values positions live from the stream without refetching the portfolio", async () => {
    const fetchMock = setup();
    render(<Terminal />);
    await screen.findByTestId("watchlist-row-AAPL");
    await userEvent.type(screen.getByTestId("trade-quantity"), "1");
    await userEvent.click(screen.getByTestId("trade-buy"));
    expect(await screen.findByTestId("position-row-AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("cash-balance")).toHaveTextContent("$9,810.00");
    const before = calls(fetchMock, "GET /api/portfolio");

    act(() => MockEventSource.latest().emit({ AAPL: tick("AAPL", 200, 189) }));
    expect(screen.getByTestId("total-value")).toHaveTextContent("$10,010.00");
    expect(screen.getByTestId("position-pnl-AAPL")).toHaveTextContent("+$10.00");
    expect(screen.getByTestId("heatmap-tile-AAPL")).toHaveAttribute("data-pnl", "up");
    expect(calls(fetchMock, "GET /api/portfolio")).toBe(before);
  });

  it("refetches portfolio, watchlist and history after a chat reply with actions", async () => {
    const fetchMock = setup();
    render(<Terminal />);
    await screen.findByTestId("watchlist-row-AAPL");
    await waitFor(() => expect(calls(fetchMock, "GET /api/portfolio")).toBe(1));
    await userEvent.type(screen.getByTestId("chat-input"), "buy{Enter}");
    expect(await screen.findByText("Buying 1 share of AAPL.")).toBeInTheDocument();
    await waitFor(() => expect(calls(fetchMock, "GET /api/portfolio")).toBe(2));
    expect(calls(fetchMock, "GET /api/watchlist")).toBe(2);
    expect(calls(fetchMock, "GET /api/portfolio/history")).toBe(2);
    expect(await screen.findByTestId("position-row-AAPL")).toBeInTheDocument();
    expect(screen.getAllByTestId("chat-message").map((m) => m.dataset.role)).toEqual(["user", "assistant"]);
  });

  it("reset asks for confirmation, then clears chat and sparklines", async () => {
    const fetchMock = setup();
    render(<Terminal />);
    await screen.findByTestId("watchlist-row-AAPL");
    act(() => MockEventSource.latest().emit({ AAPL: tick("AAPL", 191, 189, 1) }));
    act(() => MockEventSource.latest().emit({ AAPL: tick("AAPL", 192, 189, 2) }));
    expect(screen.getByTestId("watchlist-sparkline-AAPL")).toHaveAttribute("data-points", "2");
    await userEvent.type(screen.getByTestId("chat-input"), "hello{Enter}");
    await screen.findByText("Buying 1 share of AAPL.");

    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    await userEvent.click(screen.getByTestId("reset-button"));
    expect(confirm).toHaveBeenCalled();
    expect(calls(fetchMock, "POST /api/reset")).toBe(0);

    confirm.mockReturnValueOnce(true);
    await userEvent.click(screen.getByTestId("reset-button"));
    await waitFor(() => expect(calls(fetchMock, "POST /api/reset")).toBe(1));
    await waitFor(() => expect(screen.queryAllByTestId("chat-message")).toHaveLength(0));
    expect(screen.getByTestId("watchlist-sparkline-AAPL")).toHaveAttribute("data-points", "0");
    await waitFor(() => expect(screen.getByTestId("cash-balance")).toHaveTextContent("$10,000.00"));
  });

  it("shows the server's 400 message inline for a rejected trade", async () => {
    setup({ "POST /api/portfolio/trade": () => ({ status: 400, body: { error: "Insufficient cash" } }) });
    render(<Terminal />);
    await screen.findByTestId("watchlist-row-AAPL");
    await userEvent.type(screen.getByTestId("trade-quantity"), "1000");
    await userEvent.click(screen.getByTestId("trade-buy"));
    expect(await screen.findByTestId("trade-error")).toHaveTextContent("Insufficient cash");
  });
});

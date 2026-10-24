import { APIRequestContext, expect } from "@playwright/test";

export const DEFAULT_TICKERS = [
  "AAPL",
  "GOOGL",
  "MSFT",
  "AMZN",
  "TSLA",
  "NVDA",
  "META",
  "JPM",
  "V",
  "NFLX",
];

export const BASE_URL = process.env.BASE_URL ?? "http://localhost:8000";

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
  weight: number;
}

export interface Portfolio {
  cash_balance: number;
  positions_value: number;
  total_value: number;
  unrealized_pnl: number;
  positions: Position[];
}

export interface PriceEvent {
  ticker: string;
  price: number;
  previous_price: number;
  open_price: number;
  timestamp: number;
  change: number;
  change_percent: number;
  direction: "up" | "down" | "flat";
}

export async function resetAccount(request: APIRequestContext): Promise<void> {
  const res = await request.post("/api/reset");
  expect(res.status(), await res.text()).toBe(200);
  expect(await res.json()).toEqual({ status: "ok" });
}

export async function getPortfolio(request: APIRequestContext): Promise<Portfolio> {
  const res = await request.get("/api/portfolio");
  expect(res.status()).toBe(200);
  return res.json();
}

export async function getWatchlistTickers(request: APIRequestContext): Promise<string[]> {
  const res = await request.get("/api/watchlist");
  expect(res.status()).toBe(200);
  const body = await res.json();
  return body.tickers.map((t: { ticker: string }) => t.ticker);
}

export async function trade(
  request: APIRequestContext,
  ticker: string,
  side: "buy" | "sell",
  quantity: number,
) {
  return request.post("/api/portfolio/trade", { data: { ticker, side, quantity } });
}

/** Wait until the watchlist reports a price for `ticker` (Massive mode may lag; the simulator is immediate). */
export async function waitForPrice(request: APIRequestContext, ticker: string): Promise<number> {
  let price: number | null = null;
  await expect
    .poll(
      async () => {
        const res = await request.get("/api/watchlist");
        const body = await res.json();
        const row = body.tickers.find((t: { ticker: string }) => t.ticker === ticker);
        price = row?.price ?? null;
        return price;
      },
      { message: `waiting for a price for ${ticker}` },
    )
    .not.toBeNull();
  return price as unknown as number;
}

/**
 * Read SSE events from /api/stream/prices for up to `ms` milliseconds (or until `count` events).
 * Returns the raw text preamble (for `retry:`) and the parsed data events.
 */
export async function readSse(
  opts: { ms?: number; count?: number } = {},
): Promise<{ raw: string; events: Record<string, PriceEvent>[]; contentType: string | null }> {
  const { ms = 3000, count = Infinity } = opts;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  let raw = "";
  const events: Record<string, PriceEvent>[] = [];
  let contentType: string | null = null;
  try {
    const res = await fetch(`${BASE_URL}/api/stream/prices`, { signal: controller.signal });
    contentType = res.headers.get("content-type");
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (events.length < count) {
      const { value, done } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      raw += chunk;
      buffer += chunk;
      // SSE frames are separated by a blank line (\n\n or \r\n\r\n).
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const data = frame
          .split(/\r?\n/)
          .filter((l) => l.startsWith("data:"))
          .map((l) => l.slice(5).trimStart())
          .join("\n");
        if (data) events.push(JSON.parse(data));
      }
    }
    controller.abort();
  } catch (err) {
    if ((err as Error).name !== "AbortError") throw err;
  } finally {
    clearTimeout(timer);
  }
  return { raw, events, contentType };
}

/** Parse "$10,000.00" / "10000" / "-$1,234.56" into a number. */
export function parseMoney(text: string): number {
  const cleaned = text.replace(/[^0-9.\-]/g, "");
  return Number(cleaned);
}

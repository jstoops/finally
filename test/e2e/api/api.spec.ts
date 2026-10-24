import { expect, test } from "@playwright/test";
import {
  DEFAULT_TICKERS,
  getPortfolio,
  getWatchlistTickers,
  readSse,
  resetAccount,
  trade,
  waitForPrice,
} from "../helpers";

const ISO_UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;

test.beforeEach(async ({ request }) => {
  await resetAccount(request);
});

test.describe("system", () => {
  test("GET /api/health returns ok", async ({ request }) => {
    const res = await request.get("/api/health");
    expect(res.status()).toBe(200);
    expect(await res.json()).toEqual({ status: "ok" });
  });

  test("POST /api/reset restores seeded state", async ({ request }) => {
    await waitForPrice(request, "AAPL");
    expect((await trade(request, "AAPL", "buy", 2)).status()).toBe(200);
    await request.post("/api/watchlist", { data: { ticker: "PYPL" } });
    await request.delete("/api/watchlist/MSFT");
    await request.post("/api/chat", { data: { message: "hello" } });

    await resetAccount(request);

    const portfolio = await getPortfolio(request);
    expect(portfolio.cash_balance).toBe(10000);
    expect(portfolio.positions).toEqual([]);
    expect(await getWatchlistTickers(request)).toEqual(DEFAULT_TICKERS);
    const chat = await (await request.get("/api/chat/history")).json();
    expect(chat.messages).toEqual([]);
    const history = await (await request.get("/api/portfolio/history")).json();
    expect(history.snapshots).toHaveLength(1);
    expect(history.snapshots[0].total_value).toBe(10000);
  });
});

test.describe("watchlist", () => {
  test("GET /api/watchlist lists the default tickers in order with prices", async ({ request }) => {
    const res = await request.get("/api/watchlist");
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.tickers.map((t: { ticker: string }) => t.ticker)).toEqual(DEFAULT_TICKERS);
    for (const row of body.tickers) {
      expect(Object.keys(row).sort()).toEqual(["added_at", "open_price", "price", "ticker"]);
      expect(row.added_at).toMatch(ISO_UTC);
      // Simulator mode prices every seeded ticker immediately.
      expect(typeof row.price).toBe("number");
      expect(typeof row.open_price).toBe("number");
    }
  });

  test("POST adds (201), is idempotent (200), normalizes, and rejects malformed (400)", async ({
    request,
  }) => {
    const created = await request.post("/api/watchlist", { data: { ticker: "  pypl " } });
    expect(created.status()).toBe(201);
    const entry = await created.json();
    expect(entry.ticker).toBe("PYPL");
    expect(entry.added_at).toMatch(ISO_UTC);

    const again = await request.post("/api/watchlist", { data: { ticker: "PYPL" } });
    expect(again.status()).toBe(200);
    expect((await again.json()).ticker).toBe("PYPL");

    const tickers = await getWatchlistTickers(request);
    expect(tickers.filter((t) => t === "PYPL")).toHaveLength(1);
    expect(tickers.at(-1)).toBe("PYPL");

    // The simulator prices a newly added ticker immediately.
    await waitForPrice(request, "PYPL");

    for (const bad of ["123", "TOO-LONG-TICKER", "$$$", ""]) {
      const res = await request.post("/api/watchlist", { data: { ticker: bad } });
      expect(res.status(), `ticker ${JSON.stringify(bad)}`).toBe(400);
      expect(typeof (await res.json()).error).toBe("string");
    }
  });

  test("POST with a missing field returns 422", async ({ request }) => {
    const res = await request.post("/api/watchlist", { data: {} });
    expect(res.status()).toBe(422);
  });

  test("DELETE removes (204) and returns 404 when absent", async ({ request }) => {
    const res = await request.delete("/api/watchlist/NFLX");
    expect(res.status()).toBe(204);
    expect(await getWatchlistTickers(request)).not.toContain("NFLX");

    const missing = await request.delete("/api/watchlist/NFLX");
    expect(missing.status()).toBe(404);
    expect(typeof (await missing.json()).error).toBe("string");
  });
});

test.describe("portfolio", () => {
  test("GET /api/portfolio initial shape", async ({ request }) => {
    const p = await getPortfolio(request);
    expect(p).toEqual({
      cash_balance: 10000,
      positions_value: 0,
      total_value: 10000,
      unrealized_pnl: 0,
      positions: [],
    });
  });

  test("buy returns trade + portfolio and updates cash/position", async ({ request }) => {
    await waitForPrice(request, "AAPL");
    const res = await trade(request, "aapl", "buy", 3);
    expect(res.status(), await res.text()).toBe(200);
    const body = await res.json();

    expect(body.trade).toMatchObject({ ticker: "AAPL", side: "buy", quantity: 3 });
    expect(typeof body.trade.id).toBe("string");
    expect(body.trade.price).toBeGreaterThan(0);
    expect(body.trade.executed_at).toMatch(ISO_UTC);

    const p = body.portfolio;
    expect(p.cash_balance).toBeCloseTo(10000 - 3 * body.trade.price, 2);
    expect(p.positions).toHaveLength(1);
    const pos = p.positions[0];
    expect(Object.keys(pos).sort()).toEqual(
      [
        "avg_cost",
        "current_price",
        "market_value",
        "quantity",
        "ticker",
        "unrealized_pnl",
        "unrealized_pnl_percent",
        "weight",
      ].sort(),
    );
    expect(pos).toMatchObject({ ticker: "AAPL", quantity: 3, weight: 1 });
    expect(pos.avg_cost).toBeCloseTo(body.trade.price, 4);
    expect(pos.market_value).toBeCloseTo(pos.quantity * pos.current_price, 2);
    expect(p.total_value).toBeCloseTo(p.cash_balance + p.positions_value, 2);
  });

  test("avg cost is quantity-weighted across buys; weights sum to 1", async ({ request }) => {
    await waitForPrice(request, "AAPL");
    await waitForPrice(request, "MSFT");
    const t1 = (await (await trade(request, "AAPL", "buy", 2)).json()).trade;
    const t2 = (await (await trade(request, "AAPL", "buy", 1.5)).json()).trade;
    await trade(request, "MSFT", "buy", 1);

    const p = await getPortfolio(request);
    const aapl = p.positions.find((x) => x.ticker === "AAPL")!;
    expect(aapl.quantity).toBeCloseTo(3.5, 4);
    expect(aapl.avg_cost).toBeCloseTo((2 * t1.price + 1.5 * t2.price) / 3.5, 2);
    const weightSum = p.positions.reduce((s, x) => s + x.weight, 0);
    expect(weightSum).toBeCloseTo(1, 4);
  });

  test("sell partially, then fully removes the position", async ({ request }) => {
    await waitForPrice(request, "AAPL");
    await trade(request, "AAPL", "buy", 5);

    const partial = await trade(request, "AAPL", "sell", 2);
    expect(partial.status()).toBe(200);
    const pbody = await partial.json();
    expect(pbody.trade.side).toBe("sell");
    expect(pbody.portfolio.positions[0].quantity).toBeCloseTo(3, 4);

    const full = await trade(request, "AAPL", "sell", 3);
    expect(full.status()).toBe(200);
    expect((await full.json()).portfolio.positions).toEqual([]);
  });

  test("business-rule failures return 400 with an error message", async ({ request }) => {
    await waitForPrice(request, "AAPL");
    const cases: Array<[string, Record<string, unknown>]> = [
      ["insufficient cash", { ticker: "AAPL", side: "buy", quantity: 1_000_000 }],
      ["sell more than held", { ticker: "AAPL", side: "sell", quantity: 1 }],
      ["zero quantity", { ticker: "AAPL", side: "buy", quantity: 0 }],
      ["negative quantity", { ticker: "AAPL", side: "buy", quantity: -1 }],
      ["malformed ticker", { ticker: "12$", side: "buy", quantity: 1 }],
      ["no cached price", { ticker: "ZZZZ", side: "buy", quantity: 1 }],
    ];
    for (const [name, data] of cases) {
      const res = await request.post("/api/portfolio/trade", { data });
      expect(res.status(), name).toBe(400);
      const body = await res.json();
      expect(typeof body.error, name).toBe("string");
      if (name === "no cached price") {
        expect(body.error).toBe("No price available for ZZZZ. Add it to your watchlist first.");
      }
    }
    // None of the failures touched the account.
    expect((await getPortfolio(request)).cash_balance).toBe(10000);
  });

  test("malformed trade bodies return 422 or 400", async ({ request }) => {
    const missing = await request.post("/api/portfolio/trade", { data: { ticker: "AAPL" } });
    expect(missing.status()).toBe(422);
    const wrongType = await request.post("/api/portfolio/trade", {
      data: { ticker: "AAPL", side: "buy", quantity: "lots" },
    });
    expect(wrongType.status()).toBe(422);
    const badSide = await request.post("/api/portfolio/trade", {
      data: { ticker: "AAPL", side: "short", quantity: 1 },
    });
    expect([400, 422]).toContain(badSide.status());
  });

  test("GET /api/portfolio/history records snapshots after reset and trades", async ({ request }) => {
    const first = await (await request.get("/api/portfolio/history")).json();
    expect(first.snapshots).toHaveLength(1);
    expect(first.snapshots[0].recorded_at).toMatch(ISO_UTC);

    await waitForPrice(request, "AAPL");
    await trade(request, "AAPL", "buy", 1);
    await trade(request, "AAPL", "sell", 1);

    const after = await (await request.get("/api/portfolio/history")).json();
    expect(after.snapshots.length).toBeGreaterThanOrEqual(3);
    const times = after.snapshots.map((s: { recorded_at: string }) => s.recorded_at);
    expect([...times].sort()).toEqual(times); // oldest first
    for (const s of after.snapshots) {
      expect(Object.keys(s).sort()).toEqual(["recorded_at", "total_value"]);
    }
  });
});

test.describe("market data", () => {
  test("GET /api/prices/{ticker}/history returns recent points", async ({ request }) => {
    await expect
      .poll(async () => (await (await request.get("/api/prices/AAPL/history")).json()).points.length)
      .toBeGreaterThan(1);
    const body = await (await request.get("/api/prices/AAPL/history")).json();
    expect(body.ticker).toBe("AAPL");
    for (const pt of body.points) {
      expect(typeof pt.timestamp).toBe("number");
      expect(typeof pt.price).toBe("number");
    }
    const ts = body.points.map((p: { timestamp: number }) => p.timestamp);
    expect([...ts].sort((a, b) => a - b)).toEqual(ts);
    // Unix seconds, not milliseconds.
    expect(ts[0]).toBeLessThan(1e11);
  });

  test("GET /api/prices/{ticker}/history is empty for an untracked ticker", async ({ request }) => {
    const res = await request.get("/api/prices/QQQQ/history");
    expect(res.status()).toBe(200);
    expect(await res.json()).toEqual({ ticker: "QQQQ", points: [] });
  });

  test("SSE stream sends retry and keyed events with all fields", async () => {
    const { raw, events, contentType } = await readSse({ ms: 4000, count: 2 });
    expect(contentType).toContain("text/event-stream");
    expect(raw).toMatch(/retry: ?1000/);
    expect(events.length).toBeGreaterThanOrEqual(1);
    const ev = events[0];
    for (const t of DEFAULT_TICKERS) expect(Object.keys(ev)).toContain(t);
    const aapl = ev.AAPL;
    expect(aapl.ticker).toBe("AAPL");
    for (const f of ["price", "previous_price", "open_price", "timestamp", "change", "change_percent"]) {
      expect(typeof (aapl as unknown as Record<string, unknown>)[f], f).toBe("number");
    }
    expect(["up", "down", "flat"]).toContain(aapl.direction);
    expect(aapl.timestamp).toBeLessThan(1e11);
  });
});

test.describe("tracked tickers", () => {
  test("removing a held ticker from the watchlist keeps it priced", async ({ request }) => {
    await waitForPrice(request, "TSLA");
    await trade(request, "TSLA", "buy", 1);
    expect((await request.delete("/api/watchlist/TSLA")).status()).toBe(204);

    const { events } = await readSse({ ms: 3000, count: 1 });
    expect(Object.keys(events[0])).toContain("TSLA");
    // Selling still works because a price is still cached.
    expect((await trade(request, "TSLA", "sell", 1)).status()).toBe(200);
  });

  test("selling an unwatched ticker to zero stops tracking it", async ({ request }) => {
    await request.post("/api/watchlist", { data: { ticker: "PYPL" } });
    await waitForPrice(request, "PYPL");
    await trade(request, "PYPL", "buy", 1);
    await request.delete("/api/watchlist/PYPL");
    expect((await trade(request, "PYPL", "sell", 1)).status()).toBe(200);

    const { events } = await readSse({ ms: 3000, count: 1 });
    expect(Object.keys(events[0])).not.toContain("PYPL");
    expect((await (await request.get("/api/prices/PYPL/history")).json()).points).toEqual([]);
  });

  test("reset re-syncs tracked tickers to the default watchlist", async ({ request }) => {
    await request.post("/api/watchlist", { data: { ticker: "PYPL" } });
    await waitForPrice(request, "PYPL");
    await resetAccount(request);
    const { events } = await readSse({ ms: 3000, count: 1 });
    expect(Object.keys(events[0]).sort()).toEqual([...DEFAULT_TICKERS].sort());
  });
});

test.describe("chat (LLM_MOCK=true)", () => {
  const MESSAGE_KEYS = ["actions", "content", "created_at", "id", "role"];

  test("greeting returns the stored assistant message with null actions", async ({ request }) => {
    const res = await request.post("/api/chat", { data: { message: "hello there" } });
    expect(res.status(), await res.text()).toBe(200);
    const msg = await res.json();
    expect(Object.keys(msg).sort()).toEqual(MESSAGE_KEYS);
    expect(msg.role).toBe("assistant");
    expect(msg.content).toBe("Hello! I'm FinAlly, your AI trading assistant. How can I help?");
    expect(msg.actions).toBeNull();
    expect(msg.created_at).toMatch(ISO_UTC);
  });

  test("'buy' executes a trade and reports it in actions", async ({ request }) => {
    await waitForPrice(request, "AAPL");
    const msg = await (await request.post("/api/chat", { data: { message: "Please BUY something" } })).json();
    expect(msg.content).toContain("Buying 1 share of AAPL.");
    expect(msg.actions.trades).toHaveLength(1);
    const t = msg.actions.trades[0];
    expect(t).toMatchObject({ ticker: "AAPL", side: "buy", quantity: 1, status: "executed" });
    expect(t.price).toBeGreaterThan(0);

    const p = await getPortfolio(request);
    expect(p.positions.map((x) => x.ticker)).toEqual(["AAPL"]);
  });

  test("'sell' with no position records a failed action and appends a note", async ({ request }) => {
    const msg = await (await request.post("/api/chat", { data: { message: "sell" } })).json();
    expect(msg.content).toContain("Selling 1 share of AAPL.");
    const t = msg.actions.trades[0];
    expect(t.status).toBe("failed");
    expect(typeof t.error).toBe("string");
    expect(t.price).toBeUndefined();
    // A templated failure note is appended to the message.
    expect(msg.content.length).toBeGreaterThan("Selling 1 share of AAPL.".length);
  });

  test("'add' and 'remove' change the watchlist", async ({ request }) => {
    const add = await (await request.post("/api/chat", { data: { message: "add PYPL" } })).json();
    expect(add.content).toContain("Adding PYPL to your watchlist.");
    expect(add.actions.watchlist_changes[0]).toMatchObject({
      ticker: "PYPL",
      action: "add",
      status: "executed",
    });
    expect(await getWatchlistTickers(request)).toContain("PYPL");

    const rm = await (await request.post("/api/chat", { data: { message: "remove PYPL" } })).json();
    expect(rm.actions.watchlist_changes[0]).toMatchObject({
      ticker: "PYPL",
      action: "remove",
      status: "executed",
    });
    expect(await getWatchlistTickers(request)).not.toContain("PYPL");
  });

  test("GET /api/chat/history returns messages oldest first", async ({ request }) => {
    await request.post("/api/chat", { data: { message: "hello" } });
    await request.post("/api/chat", { data: { message: "add PYPL" } });
    const res = await request.get("/api/chat/history");
    expect(res.status()).toBe(200);
    const { messages } = await res.json();
    expect(messages.map((m: { role: string }) => m.role)).toEqual([
      "user",
      "assistant",
      "user",
      "assistant",
    ]);
    expect(messages[0]).toMatchObject({ content: "hello", actions: null });
    expect(messages[3].actions.watchlist_changes[0].ticker).toBe("PYPL");
    for (const m of messages) expect(Object.keys(m).sort()).toEqual(MESSAGE_KEYS);
  });

  test("POST /api/chat with a missing message returns 422", async ({ request }) => {
    const res = await request.post("/api/chat", { data: {} });
    expect(res.status()).toBe(422);
  });
});

test.describe("errors", () => {
  test("unknown API route returns 404 JSON, not the SPA", async ({ request }) => {
    const res = await request.get("/api/does-not-exist");
    expect(res.status()).toBe(404);
  });
});

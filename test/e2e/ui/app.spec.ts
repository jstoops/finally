import { expect, Page, test } from "@playwright/test";
import { DEFAULT_TICKERS, getPortfolio, parseMoney, resetAccount, waitForPrice } from "../helpers";

const tid = (page: Page, id: string) => page.getByTestId(id);

async function openApp(page: Page) {
  await page.goto("/");
  await expect(tid(page, "connection-status")).toHaveAttribute("data-status", "connected");
}

async function placeTrade(page: Page, ticker: string, qty: string, side: "buy" | "sell") {
  await tid(page, "trade-ticker").fill(ticker);
  await tid(page, "trade-quantity").fill(qty);
  await tid(page, side === "buy" ? "trade-buy" : "trade-sell").click();
}

test.beforeEach(async ({ request }) => {
  await resetAccount(request);
});

test("fresh start: default watchlist, $10,000 cash, prices streaming", async ({ page }) => {
  await openApp(page);

  const rows = page.locator('[data-testid^="watchlist-row-"]');
  await expect(rows).toHaveCount(DEFAULT_TICKERS.length);
  for (const t of DEFAULT_TICKERS) await expect(tid(page, `watchlist-row-${t}`)).toBeVisible();

  await expect(tid(page, "cash-balance")).toContainText("10,000.00");
  await expect(tid(page, "total-value")).toContainText("10,000.00");

  // Prices stream: the AAPL price text changes over a few seconds.
  const price = tid(page, "watchlist-price-AAPL");
  await expect(price).toHaveText(/\d+\.\d{2}/);
  const first = await price.innerText();
  await expect.poll(() => price.innerText(), { timeout: 15_000 }).not.toBe(first);

  // Chg % column and sparkline are present.
  await expect(tid(page, "watchlist-change-AAPL")).toHaveText(/%/);
  await expect(tid(page, "watchlist-sparkline-AAPL").locator("polyline")).toHaveCount(1);
});

test("price flash class is applied on updates", async ({ page }) => {
  await openApp(page);
  // The flash class is transient, so watch for it with a MutationObserver instead of polling.
  const seen = await tid(page, "watchlist-price-AAPL").evaluate(
    (el) =>
      new Promise<string>((resolve, reject) => {
        const check = () => {
          const m = el.className.match(/flash-(up|down)/);
          if (m) {
            observer.disconnect();
            resolve(m[0]);
          }
        };
        const observer = new MutationObserver(check);
        observer.observe(el, { attributes: true, attributeFilter: ["class"] });
        check();
        setTimeout(() => reject(new Error("no flash class within 15s")), 15_000);
      }),
  );
  expect(seen).toMatch(/^flash-(up|down)$/);
});

test("clicking a ticker selects it in the main chart", async ({ page }) => {
  await openApp(page);
  await tid(page, "watchlist-row-MSFT").click();
  await expect(tid(page, "main-chart-ticker")).toContainText("MSFT");
  await expect(tid(page, "main-chart").locator("canvas").first()).toBeVisible();
});

test("add and remove a ticker from the watchlist", async ({ page, request }) => {
  await openApp(page);

  await tid(page, "watchlist-add-input").fill("pypl");
  await tid(page, "watchlist-add-button").click();
  await expect(tid(page, "watchlist-row-PYPL")).toBeVisible();
  await expect(tid(page, "watchlist-price-PYPL")).toHaveText(/\d+\.\d{2}/);

  await tid(page, "watchlist-remove-PYPL").click();
  await expect(tid(page, "watchlist-row-PYPL")).toHaveCount(0);

  // Persisted server-side.
  const body = await (await request.get("/api/watchlist")).json();
  expect(body.tickers.map((t: { ticker: string }) => t.ticker)).toEqual(DEFAULT_TICKERS);

  // A reload keeps the default list.
  await page.reload();
  await expect(page.locator('[data-testid^="watchlist-row-"]')).toHaveCount(DEFAULT_TICKERS.length);
});

test("buy shares: cash decreases and position appears", async ({ page, request }) => {
  await waitForPrice(request, "AAPL");
  await openApp(page);

  await placeTrade(page, "AAPL", "5", "buy");

  await expect(tid(page, "position-row-AAPL")).toBeVisible();
  await expect(tid(page, "position-qty-AAPL")).toHaveText(/^5(\.0+)?$/);
  await expect
    .poll(async () => parseMoney(await tid(page, "cash-balance").innerText()))
    .toBeLessThan(10000);

  const p = await getPortfolio(request);
  expect(p.positions[0]).toMatchObject({ ticker: "AAPL", quantity: 5 });
  expect(parseMoney(await tid(page, "cash-balance").innerText())).toBeCloseTo(p.cash_balance, 1);
  await expect(tid(page, "heatmap-tile-AAPL")).toBeVisible();
});

test("sell shares: position updates, then disappears", async ({ page, request }) => {
  await waitForPrice(request, "NVDA");
  await openApp(page);

  await placeTrade(page, "NVDA", "3", "buy");
  await expect(tid(page, "position-qty-NVDA")).toHaveText(/^3(\.0+)?$/);
  const cashAfterBuy = parseMoney(await tid(page, "cash-balance").innerText());

  await placeTrade(page, "NVDA", "1", "sell");
  await expect(tid(page, "position-qty-NVDA")).toHaveText(/^2(\.0+)?$/);
  await expect
    .poll(async () => parseMoney(await tid(page, "cash-balance").innerText()))
    .toBeGreaterThan(cashAfterBuy);

  await placeTrade(page, "NVDA", "2", "sell");
  await expect(tid(page, "position-row-NVDA")).toHaveCount(0);
  await expect(tid(page, "heatmap-tile-NVDA")).toHaveCount(0);
});

test("trade errors are shown inline", async ({ page }) => {
  await openApp(page);
  await placeTrade(page, "AAPL", "1000000", "buy");
  await expect(tid(page, "trade-error")).toBeVisible();
  await expect(tid(page, "trade-error")).not.toBeEmpty();

  await placeTrade(page, "AAPL", "1", "sell");
  await expect(tid(page, "trade-error")).toBeVisible();
});

test("portfolio visualization: heatmap colors match P&L and P&L chart has points", async ({
  page,
  request,
}) => {
  await waitForPrice(request, "AAPL");
  await waitForPrice(request, "MSFT");
  await openApp(page);
  await placeTrade(page, "AAPL", "2", "buy");
  await expect(tid(page, "position-row-AAPL")).toBeVisible();
  await placeTrade(page, "MSFT", "2", "buy");
  await expect(tid(page, "position-row-MSFT")).toBeVisible();

  for (const t of ["AAPL", "MSFT"]) {
    const tile = tid(page, `heatmap-tile-${t}`);
    await expect(tile).toBeVisible();
    // Wait for the price to move away from cost so the tile is clearly profit or loss.
    await expect
      .poll(async () => tile.getAttribute("data-pnl"), { timeout: 20_000 })
      .toMatch(/^(up|down)$/);
    // The rendered colour must agree with the P&L state (green for profit, red for loss).
    await expect
      .poll(
        async () => {
          const state = await tile.getAttribute("data-pnl");
          const bg = await tile.evaluate((el) => getComputedStyle(el).backgroundColor);
          const [r, g] = (bg.match(/\d+(\.\d+)?/g) ?? []).map(Number);
          if (state === "up") return g > r;
          if (state === "down") return r > g;
          return false;
        },
        { timeout: 5_000 },
      )
      .toBe(true);
  }

  // Tiles are sized by weight: both are present with non-zero area.
  const boxA = await tid(page, "heatmap-tile-AAPL").boundingBox();
  const boxM = await tid(page, "heatmap-tile-MSFT").boundingBox();
  expect(boxA!.width * boxA!.height).toBeGreaterThan(0);
  expect(boxM!.width * boxM!.height).toBeGreaterThan(0);

  // P&L chart: reset + two trades = at least 3 snapshots.
  const chart = tid(page, "pnl-chart");
  await expect(chart).toBeVisible();
  await expect(chart.locator("canvas").first()).toBeVisible();
  await expect
    .poll(async () => Number((await chart.getAttribute("data-points")) ?? 0))
    .toBeGreaterThanOrEqual(3);
});

test("AI chat (mocked): 'buy' executes a trade shown inline", async ({ page, request }) => {
  await waitForPrice(request, "AAPL");
  await openApp(page);

  await tid(page, "chat-input").fill("buy");
  await tid(page, "chat-send").click();

  const assistant = page.locator('[data-testid="chat-message"][data-role="assistant"]').last();
  await expect(assistant).toContainText("Buying 1 share of AAPL.");
  const action = assistant.getByTestId("chat-action");
  await expect(action).toHaveAttribute("data-status", "executed");
  await expect(action).toContainText("AAPL");
  await expect(page.locator('[data-testid="chat-message"][data-role="user"]').last()).toContainText(
    "buy",
  );

  // Portfolio is refreshed after a chat response with actions.
  await expect(tid(page, "position-row-AAPL")).toBeVisible();
  await expect(tid(page, "chat-loading")).toHaveCount(0);
});

test("AI chat (mocked): failed action is visibly distinct; history reloads", async ({ page }) => {
  await openApp(page);
  await tid(page, "chat-input").fill("sell");
  await tid(page, "chat-send").click();

  const action = page.getByTestId("chat-action").last();
  await expect(action).toHaveAttribute("data-status", "failed");

  await tid(page, "chat-input").fill("add PYPL");
  await tid(page, "chat-send").click();
  await expect(tid(page, "watchlist-row-PYPL")).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("chat-message")).toHaveCount(4);
  await expect(page.getByTestId("chat-action").first()).toHaveAttribute("data-status", "failed");
});

test("reset restores $10k and the default watchlist", async ({ page, request }) => {
  await waitForPrice(request, "AAPL");
  await openApp(page);
  await placeTrade(page, "AAPL", "4", "buy");
  await expect(tid(page, "position-row-AAPL")).toBeVisible();
  await tid(page, "watchlist-add-input").fill("PYPL");
  await tid(page, "watchlist-add-button").click();
  await expect(tid(page, "watchlist-row-PYPL")).toBeVisible();
  await tid(page, "chat-input").fill("hello");
  await tid(page, "chat-send").click();
  await expect(page.getByTestId("chat-message")).toHaveCount(2);

  page.once("dialog", (d) => d.accept());
  await tid(page, "reset-button").click();

  await expect(tid(page, "cash-balance")).toContainText("10,000.00");
  await expect(tid(page, "position-row-AAPL")).toHaveCount(0);
  await expect(tid(page, "watchlist-row-PYPL")).toHaveCount(0);
  await expect(page.locator('[data-testid^="watchlist-row-"]')).toHaveCount(DEFAULT_TICKERS.length);
  await expect(page.getByTestId("chat-message")).toHaveCount(0);
});

test("reset is cancelled when the confirm dialog is dismissed", async ({ page, request }) => {
  await waitForPrice(request, "AAPL");
  await openApp(page);
  await placeTrade(page, "AAPL", "1", "buy");
  await expect(tid(page, "position-row-AAPL")).toBeVisible();

  page.once("dialog", (d) => d.dismiss());
  await tid(page, "reset-button").click();
  await expect(tid(page, "position-row-AAPL")).toBeVisible();
  expect((await getPortfolio(request)).positions).toHaveLength(1);
});

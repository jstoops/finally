import { vi } from "vitest";
import type { PriceUpdate } from "@/lib/types";

/** Minimal controllable EventSource stand-in. */
export class MockEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static instances: MockEventSource[] = [];

  readyState = MockEventSource.CONNECTING;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  close = vi.fn(() => {
    this.readyState = MockEventSource.CLOSED;
  });

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }

  open() {
    this.readyState = MockEventSource.OPEN;
    this.onopen?.(new Event("open"));
  }
  emit(data: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  }
  fail(readyState: number) {
    this.readyState = readyState;
    this.onerror?.(new Event("error"));
  }

  static latest() {
    return MockEventSource.instances[MockEventSource.instances.length - 1];
  }
}

export function installEventSource() {
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource);
}

export function tick(ticker: string, price: number, open = 100, timestamp = Date.now() / 1000): PriceUpdate {
  return {
    ticker,
    price,
    previous_price: price,
    open_price: open,
    timestamp,
    change: 0,
    change_percent: 0,
    direction: "flat",
  };
}

/** vi.mock factory for lightweight-charts (canvas doesn't exist in jsdom). */
export function lightweightChartsMock() {
  const series = () => ({
    setData: vi.fn(),
    update: vi.fn(),
    createPriceLine: vi.fn(() => ({})),
    removePriceLine: vi.fn(),
  });
  return {
    createChart: vi.fn(() => ({
      addAreaSeries: vi.fn(series),
      addBaselineSeries: vi.fn(series),
      timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
      remove: vi.fn(),
    })),
    ColorType: { Solid: "solid" },
    CrosshairMode: { Normal: 0 },
    LineStyle: { Solid: 0, Dotted: 1, Dashed: 2 },
  };
}

type Route = (init?: RequestInit) => { status?: number; body?: unknown };

/** Stubs global fetch with a "METHOD /path" -> handler table; records calls. */
export function mockFetch(routes: Record<string, Route>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(input)}`;
    const route = routes[key];
    if (!route) return new Response(JSON.stringify({ error: `unmocked ${key}` }), { status: 404 });
    const { status = 200, body } = route(init);
    return new Response(status === 204 ? null : JSON.stringify(body ?? {}), { status });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

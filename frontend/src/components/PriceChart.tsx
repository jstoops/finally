"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  LineStyle,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { api } from "@/lib/api";
import { baseChartOptions, CHART_COLORS, dedupeByTime, toChartTime } from "@/lib/chart";
import { fmtPct, fmtPrice, trendClass } from "@/lib/format";
import { changeSinceOpen } from "@/lib/portfolio";
import type { PriceUpdate } from "@/lib/types";
import { Panel } from "./Panel";

interface PriceChartProps {
  ticker: string | null;
  live?: PriceUpdate;
}

/** Main chart: loads the last ~5 minutes from the backend on selection, then appends SSE ticks. */
export function PriceChart({ ticker, live }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const openLineRef = useRef<IPriceLine | null>(null);
  const lastTimeRef = useRef<number>(0);
  const [loadedTicker, setLoadedTicker] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      ...baseChartOptions,
      localization: { priceFormatter: (p: number) => p.toFixed(2) },
    });
    const series = chart.addAreaSeries({
      lineColor: CHART_COLORS.blue,
      topColor: "rgba(32, 157, 215, 0.28)",
      bottomColor: "rgba(32, 157, 215, 0.01)",
      lineWidth: 2,
      priceLineColor: CHART_COLORS.blue,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      openLineRef.current = null;
    };
  }, []);

  // Load history whenever the selection changes.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    series.setData([]);
    lastTimeRef.current = 0;
    if (openLineRef.current) {
      series.removePriceLine(openLineRef.current);
      openLineRef.current = null;
    }
    setLoadedTicker(null);
    if (!ticker) return;
    let cancelled = false;
    api
      .priceHistory(ticker)
      .then((h) => {
        if (cancelled || !seriesRef.current) return;
        const data = dedupeByTime(h.points.map((p) => ({ time: toChartTime(p.timestamp), value: p.price })));
        seriesRef.current.setData(data);
        lastTimeRef.current = data.length ? data[data.length - 1].time : 0;
        chartRef.current?.timeScale().fitContent();
      })
      .catch(() => {
        /* An empty chart still fills from the live stream. */
      })
      .finally(() => {
        if (!cancelled) setLoadedTicker(ticker);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  // Append live ticks once history is in place.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !live || live.ticker !== ticker || loadedTicker !== ticker) return;
    const time = toChartTime(live.timestamp);
    if (time < lastTimeRef.current) return;
    series.update({ time: time as UTCTimestamp, value: live.price });
    lastTimeRef.current = time;
    if (!openLineRef.current && live.open_price) {
      openLineRef.current = series.createPriceLine({
        price: live.open_price,
        color: CHART_COLORS.yellow,
        lineStyle: LineStyle.Dashed,
        lineWidth: 1,
        axisLabelVisible: true,
        title: "OPEN",
      });
    }
  }, [live, ticker, loadedTicker]);

  const chg = changeSinceOpen(live?.price, live?.open_price);

  return (
    <Panel
      testId="main-chart"
      title={
        <span className="flex items-baseline gap-3 normal-case tracking-normal">
          <span data-testid="main-chart-ticker" className="font-mono text-[13px] font-bold text-ink">
            {ticker ?? "—"}
          </span>
          {live && (
            <>
              <span className="font-mono text-[13px] font-semibold tabular-nums text-ink">{fmtPrice(live.price)}</span>
              <span className={`font-mono text-[11.5px] tabular-nums ${trendClass(chg)}`}>{fmtPct(chg)}</span>
            </>
          )}
        </span>
      }
      right={<span className="uppercase tracking-wider text-ink-faint">Last 5 min · live</span>}
      bodyClassName="relative"
    >
      <div ref={containerRef} className="absolute inset-0 p-1" />
      {!ticker && (
        <div className="absolute inset-0 flex items-center justify-center text-[12px] text-ink-faint">
          Select a ticker to chart
        </div>
      )}
    </Panel>
  );
}

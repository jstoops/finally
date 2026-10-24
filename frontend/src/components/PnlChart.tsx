"use client";

import { useEffect, useMemo, useRef } from "react";
import { createChart, LineStyle, type IChartApi, type ISeriesApi } from "lightweight-charts";
import { baseChartOptions, CHART_COLORS, dedupeByTime, toChartTime } from "@/lib/chart";
import { fmtMoney, fmtSignedMoney, trendClass } from "@/lib/format";
import type { Snapshot } from "@/lib/types";
import { Panel } from "./Panel";

const STARTING_CASH = 10000;

interface PnlChartProps {
  snapshots: Snapshot[];
  liveTotal: number | null;
}

/** Total portfolio value over time from snapshots, with the live total as the trailing point. */
export function PnlChart({ snapshots, liveTotal }: PnlChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Baseline"> | null>(null);
  const lastTimeRef = useRef(0);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      ...baseChartOptions,
      timeScale: { ...baseChartOptions.timeScale, secondsVisible: false },
      localization: { priceFormatter: (p: number) => fmtMoney(p) },
    });
    const series = chart.addBaselineSeries({
      baseValue: { type: "price", price: STARTING_CASH },
      topLineColor: CHART_COLORS.up,
      topFillColor1: "rgba(34, 197, 94, 0.25)",
      topFillColor2: "rgba(34, 197, 94, 0.02)",
      bottomLineColor: CHART_COLORS.down,
      bottomFillColor1: "rgba(239, 68, 68, 0.02)",
      bottomFillColor2: "rgba(239, 68, 68, 0.25)",
      lineWidth: 2,
    });
    series.createPriceLine({
      price: STARTING_CASH,
      color: "#3b4658",
      lineStyle: LineStyle.Dotted,
      lineWidth: 1,
      axisLabelVisible: false,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  const data = useMemo(
    () =>
      dedupeByTime(
        snapshots.map((s) => ({ time: toChartTime(Date.parse(s.recorded_at) / 1000), value: s.total_value })),
      ),
    [snapshots],
  );

  useEffect(() => {
    if (!seriesRef.current) return;
    seriesRef.current.setData(data);
    lastTimeRef.current = data.length ? data[data.length - 1].time : 0;
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  useEffect(() => {
    if (!seriesRef.current || liveTotal == null || !data.length) return;
    const time = toChartTime(Date.now() / 1000);
    if (time < lastTimeRef.current) return;
    seriesRef.current.update({ time, value: liveTotal });
    lastTimeRef.current = time;
  }, [liveTotal, data]);

  const pnl = liveTotal != null ? liveTotal - STARTING_CASH : null;

  return (
    <Panel
      title="Portfolio Value"
      right={
        pnl != null && (
          <span className={`font-mono tabular-nums ${trendClass(pnl)}`}>{fmtSignedMoney(pnl)} vs start</span>
        )
      }
      bodyClassName="relative"
    >
      <div ref={containerRef} data-testid="pnl-chart" data-points={snapshots.length} className="absolute inset-0 p-1" />
    </Panel>
  );
}

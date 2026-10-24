"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fmtMoney, fmtPct } from "@/lib/format";
import { squarify } from "@/lib/treemap";
import type { Position } from "@/lib/types";
import { Panel } from "./Panel";

/** P&L % at which a tile reaches full color intensity. */
const FULL_INTENSITY_PCT = 5;

export function pnlTileColor(pnlPct: number): string {
  const t = Math.min(Math.abs(pnlPct) / FULL_INTENSITY_PCT, 1);
  if (Math.abs(pnlPct) < 0.005) return "rgb(42, 50, 64)";
  // Interpolate from a muted slate toward saturated green / red.
  const from = [42, 50, 64];
  const to = pnlPct > 0 ? [22, 163, 74] : [220, 38, 38];
  const c = from.map((f, i) => Math.round(f + (to[i] - f) * (0.25 + 0.75 * t)));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

const pnlKind = (pct: number) => (Math.abs(pct) < 0.005 ? "flat" : pct > 0 ? "up" : "down");

interface HeatmapProps {
  positions: Position[];
  onSelect?: (ticker: string) => void;
}

export function Heatmap({ positions, onSelect }: HeatmapProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 400, h: 240 });

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setSize({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rects = useMemo(
    () => squarify(positions.map((p) => ({ key: p.ticker, value: p.weight })), size.w, size.h),
    [positions, size],
  );
  const byTicker = useMemo(() => new Map(positions.map((p) => [p.ticker, p])), [positions]);

  return (
    <Panel title="Portfolio Heatmap" testId="heatmap" bodyClassName="relative p-1">
      <div ref={ref} className="relative h-full w-full">
        {!positions.length && (
          <div
            data-testid="heatmap-empty"
            className="absolute inset-0 flex items-center justify-center text-[11px] text-ink-faint"
          >
            No positions yet. Buy something to see your heatmap.
          </div>
        )}
        {rects.map((r) => {
          const p = byTicker.get(r.key)!;
          const pct = p.unrealized_pnl_percent;
          const small = r.w < 56 || r.h < 34;
          return (
            <button
              type="button"
              key={r.key}
              data-testid={`heatmap-tile-${r.key}`}
              data-pnl={pnlKind(pct)}
              onClick={() => onSelect?.(r.key)}
              title={`${p.ticker}  ${fmtPct(pct)}  ${fmtMoney(p.market_value)}  (${(p.weight * 100).toFixed(1)}%)`}
              className="absolute flex flex-col items-center justify-center overflow-hidden border border-bg-panel text-white transition-[background-color] duration-500 hover:brightness-110"
              style={{
                left: `${(r.x / size.w) * 100}%`,
                top: `${(r.y / size.h) * 100}%`,
                width: `${(r.w / size.w) * 100}%`,
                height: `${(r.h / size.h) * 100}%`,
                backgroundColor: pnlTileColor(pct),
              }}
            >
              <span className={`font-mono font-bold leading-tight ${small ? "text-[10px]" : "text-[13px]"}`}>
                {p.ticker}
              </span>
              {!small && (
                <>
                  <span className="font-mono text-[11px] tabular-nums opacity-90">{fmtPct(pct)}</span>
                  <span className="font-mono text-[9.5px] tabular-nums opacity-60">{(p.weight * 100).toFixed(1)}%</span>
                </>
              )}
            </button>
          );
        })}
      </div>
    </Panel>
  );
}

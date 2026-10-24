interface SparklineProps {
  values: number[];
  width?: number;
  height?: number;
  testId?: string;
}

/** Inline-SVG polyline of prices accumulated from the stream since page load. */
export function Sparkline({ values, width = 72, height = 22, testId }: SparklineProps) {
  const pad = 1.5;
  let points = "";
  let color = "#566175";
  if (values.length >= 2) {
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const step = (width - pad * 2) / (values.length - 1);
    points = values
      .map((v, i) => {
        const x = pad + i * step;
        const y = max === min ? height / 2 : pad + (1 - (v - min) / range) * (height - pad * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
    const delta = values[values.length - 1] - values[0];
    color = delta > 0 ? "#22c55e" : delta < 0 ? "#ef4444" : "#8592a6";
  }
  return (
    <svg
      data-testid={testId}
      data-points={values.length}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="block overflow-visible"
      aria-hidden
    >
      {points ? (
        <polyline points={points} fill="none" stroke={color} strokeWidth={1.25} strokeLinejoin="round" />
      ) : (
        <line
          x1={pad}
          x2={width - pad}
          y1={height / 2}
          y2={height / 2}
          stroke="#2f3a4d"
          strokeDasharray="2 3"
        />
      )}
    </svg>
  );
}

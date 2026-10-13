import type { VersionPoint } from "../api";
import { grade, percent, verdictLabels, versionLabels } from "../format";

const FIRST = "Version 1";

// The held-out accuracy and grade of each version the rounds tried, in two
// small charts side by side: one point per version, colored by its verdict,
// with version 1's score as a line to compare against.
export function VersionChart({
  first,
  tried,
}: Readonly<{ first: VersionPoint; tried: VersionPoint[] }>) {
  return (
    <>
      <div className="version-charts">
        <Chart
          title="Held-out accuracy"
          top={1}
          step={0.1}
          show={percent}
          first={first.accuracy}
          points={tried.map((point) => ({ ...point, value: point.accuracy }))}
        />
        <Chart
          title="Held-out grade"
          top={3}
          step={0.5}
          show={grade}
          first={first.grade}
          points={tried.map((point) => ({ ...point, value: point.grade }))}
        />
      </div>
      <ul className="chart-key" aria-label="Key">
        <li>
          <span className="key-mark key-kept" aria-hidden="true" />
          {verdictLabels.kept}
        </li>
        <li>
          <span className="key-mark key-rolled_back" aria-hidden="true" />
          {verdictLabels.rolled_back}
        </li>
        <li>
          <span className="key-mark key-under_test" aria-hidden="true" />
          {versionLabels.under_test}
        </li>
        <li>
          <span className="key-line" aria-hidden="true" />
          {FIRST}
        </li>
      </ul>
    </>
  );
}

// The size each chart is drawn at, which it shrinks from on a narrow screen.
const WIDTH = 520;
const HEIGHT = 220;
const LEFT = 48;
const RIGHT = 16;
const TOP = 12;
const BOTTOM = 44;

interface Plotted extends VersionPoint {
  value: number | null;
}

interface Scored extends Plotted {
  value: number;
}

const isScored = (point: Plotted): point is Scored => point.value !== null;

// Where a chart's axis starts: a step below the lowest score, rounded down to
// a step, so close scores are told apart rather than flattened against zero.
function axisStart(values: number[], step: number): number {
  const lowest = Math.min(...values);
  return Math.max(0, (Math.floor(lowest / step) - 1) * step);
}

function Chart({
  title,
  top,
  step,
  show,
  first,
  points,
}: Readonly<{
  title: string;
  top: number;
  step: number;
  show: (value: number) => string;
  first: number | null;
  points: Plotted[];
}>) {
  const scored = points.filter(isScored);
  const values = [first, ...scored.map((point) => point.value)].filter(
    (value) => value !== null,
  );
  const start = axisStart(values.length > 0 ? values : [top], step);
  const ticks = Array.from(
    { length: Math.round((top - start) / step) + 1 },
    (_, index) => start + index * step,
  );
  const y = (value: number) =>
    TOP + (1 - (value - start) / (top - start)) * (HEIGHT - TOP - BOTTOM);
  const x = (index: number) =>
    LEFT + ((index + 1) / (points.length + 1)) * (WIDTH - LEFT - RIGHT);
  const bottom = HEIGHT - BOTTOM;
  return (
    <figure className="version-chart">
      <figcaption>{title}</figcaption>
      <svg
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        role="img"
        aria-label={describe(title, show, first, scored)}
      >
        {ticks.map((tick) => (
          <g key={tick} className="chart-tick">
            <line x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick)} y2={y(tick)} />
            <text x={LEFT - 8} y={y(tick)} textAnchor="end" dy="0.32em">
              {show(tick)}
            </text>
          </g>
        ))}
        {first !== null && (
          <g className="chart-first">
            <line x1={LEFT} x2={WIDTH - RIGHT} y1={y(first)} y2={y(first)} />
            <text x={WIDTH - RIGHT} y={y(first) - 6} textAnchor="end">
              {FIRST}
            </text>
          </g>
        )}
        {points.map((point, index) => (
          <g key={point.number}>
            <text
              className="chart-label"
              x={x(index)}
              y={bottom + 18}
              textAnchor="middle"
            >
              {point.number}
            </text>
            {point.value !== null && (
              <circle
                className={`chart-point point-${point.verdict ?? "under_test"}`}
                cx={x(index)}
                cy={y(point.value)}
                r={6}
              >
                <title>{`Version ${String(point.number)}: ${show(point.value)}`}</title>
              </circle>
            )}
          </g>
        ))}
        <text
          className="chart-axis"
          x={LEFT + (WIDTH - LEFT - RIGHT) / 2}
          y={HEIGHT - 6}
          textAnchor="middle"
        >
          Version tried
        </text>
      </svg>
    </figure>
  );
}

// What the chart shows, for a screen reader.
function describe(
  title: string,
  show: (value: number) => string,
  first: number | null,
  scored: Scored[],
): string {
  const start =
    first === null ? `${FIRST} isn't scored yet` : `${FIRST} ${show(first)}`;
  const tried = scored.map(
    (point) =>
      `version ${String(point.number)} ${show(point.value)}, ${point.verdict ? verdictLabels[point.verdict].toLowerCase() : versionLabels.under_test.toLowerCase()}`,
  );
  return `${title}. ${[start, ...tried].join(", ")}.`;
}

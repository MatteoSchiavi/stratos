import type { Sample } from "./types";
import { duration, utc } from "./api";

export function AltitudeChart({
  samples,
  index,
  onSelect,
}: {
  samples: Sample[];
  index: number;
  onSelect: (n: number) => void;
}) {
  if (!samples.length) return null;
  const w = 900,
    h = 105,
    pad = 8;
  const maxT = Math.max(samples[samples.length - 1].elapsed_s, 1);
  const maxZ = Math.max(...samples.map((p) => p.geometric_msl_m)) * 1.12 || 1;
  const x = (i: number) => pad + (samples[i].elapsed_s / maxT) * (w - 2 * pad);
  const y = (z: number) => h - pad - (z / maxZ) * (h - 2 * pad);
  const path = samples
    .map(
      (p, i) =>
        `${i ? "L" : "M"}${x(i).toFixed(2)},${y(p.geometric_msl_m).toFixed(2)}`,
    )
    .join(" ");
  const p = samples[Math.min(index, samples.length - 1)];
  return (
    <section
      className="chart-panel"
      aria-label="Altitude profile and synchronized timeline"
    >
      <div className="chart-heading">
        <span>
          ALTITUDE PROFILE <small>GEOMETRIC MSL</small>
        </span>
        <span>
          {utc(p.time_utc)} <b>{duration(p.elapsed_s)}</b>
        </span>
      </div>
      <div className="chart-body">
        <span className="chart-unit">{(maxZ / 1000).toFixed(0)} km</span>
        <svg
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="none"
          role="img"
          aria-label="Prescribed altitude against elapsed time"
        >
          {[0.25, 0.5, 0.75, 1].map((v) => (
            <line
              key={v}
              x1={pad}
              x2={w - pad}
              y1={y(maxZ * v)}
              y2={y(maxZ * v)}
              stroke="#2b3035"
              strokeDasharray="3 6"
            />
          ))}
          <path
            d={`${path} L${x(samples.length - 1)},${h - pad} L${pad},${h - pad} Z`}
            fill="#6cb7c6"
            fillOpacity="0.06"
          />
          <path
            d={path}
            fill="none"
            stroke="#6cb7c6"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
          <line
            x1={x(index)}
            x2={x(index)}
            y1={0}
            y2={h}
            stroke="#dde9eb"
            strokeOpacity="0.45"
          />
          <circle
            cx={x(index)}
            cy={y(p.geometric_msl_m)}
            r="4"
            fill="#d8eff3"
          />
        </svg>
      </div>
      <input
        className="timeline"
        type="range"
        aria-label="Trajectory timeline"
        min={0}
        max={samples.length - 1}
        value={index}
        onChange={(e) => onSelect(Number(e.target.value))}
      />
      <div className="chart-axis">
        <span>LAUNCH / 00:00</span>
        <span>{duration(maxT / 2)}</span>
        <span>{duration(maxT)} / END OF PROFILE</span>
      </div>
    </section>
  );
}

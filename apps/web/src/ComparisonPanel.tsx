import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Download, GitCompareArrows, ShieldAlert } from "lucide-react";
import { api, downloadJson, duration, utc } from "./api";
import { TrajectoryMap } from "./LazyMap";
import type { SimulationSummary, StudyComparison } from "./types";

const distance = (m: number) =>
  Math.abs(m) >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${m.toFixed(1)} m`;
const value = (v: unknown) =>
  v === null || v === undefined
    ? "—"
    : typeof v === "object"
      ? JSON.stringify(v)
      : String(v);

export function ComparisonPanel({ studies }: { studies: SimulationSummary[] }) {
  const [reference, setReference] = useState<SimulationSummary | null>(null);
  const [candidate, setCandidate] = useState<SimulationSummary | null>(null);
  const a = reference ?? studies[0];
  const b = candidate ?? studies.find((r) => r.id !== a?.id);
  const choices = [
    ...new Map(
      [
        ...studies,
        ...(reference ? [reference] : []),
        ...(candidate ? [candidate] : []),
      ].map((r) => [r.id, r]),
    ).values(),
  ];
  const [alignment, setAlignment] = useState<"elapsed" | "utc">("elapsed");
  const [count, setCount] = useState(241);
  const [result, setResult] = useState<StudyComparison | null>(null);
  const [index, setIndex] = useState(0);
  const comparison = useMutation({
    mutationFn: () => {
      if (!a || !b) throw new Error("Select two saved studies");
      return api<StudyComparison>("/simulations/compare", {
        reference_id: a.id,
        candidate_id: b.id,
        alignment,
        sample_count: count,
      });
    },
    onSuccess: (data) => {
      setResult(data);
      setIndex(0);
    },
  });
  const paths = useMemo(
    () => ({
      reference: result?.points.map((p) => p.reference) ?? [],
      candidate: result?.points.map((p) => p.candidate) ?? [],
    }),
    [result],
  );
  const selected = result?.points[Math.min(index, result.points.length - 1)];
  const dirty =
    result &&
    (result.request.reference_id !== a?.id ||
      result.request.candidate_id !== b?.id ||
      result.request.alignment !== alignment ||
      result.sample_count !== count);
  const graph = result?.points
    .map(
      (p, i) =>
        `${10 + (i / (result.points.length - 1)) * 980},${112 - (p.horizontal_separation_m / Math.max(result.metrics.maximum_sampled_separation_m, 1)) * 94}`,
    )
    .join(" ");
  return (
    <section className="comparison-panel" aria-label="Saved-study comparison">
      <div className="section-heading">
        <div>
          <span className="eyebrow">CHALLENGE THE ASSUMPTIONS</span>
          <h2>Compare saved studies</h2>
          <p>
            Aligned paths, changed inputs and traceable scenario sensitivity.
          </p>
        </div>
        <GitCompareArrows size={24} />
      </div>
      {choices.length < 2 ? (
        <p className="empty-state">
          Save a second prediction to compare launch times, profiles or weather
          inputs.
        </p>
      ) : (
        <>
          <div className="form-grid">
            <label className="field">
              <span>Reference study · cyan</span>
              <select
                aria-label="Reference study"
                value={a?.id ?? ""}
                onChange={(e) =>
                  setReference(choices.find((r) => r.id === e.target.value)!)
                }
              >
                {choices.map((r) => (
                  <option key={r.id} value={r.id}>
                    {utc(r.created_utc)} · {r.weather_provider} ·{" "}
                    {distance(r.distance_m)} · {r.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Candidate study · amber</span>
              <select
                aria-label="Candidate study"
                value={b?.id ?? ""}
                onChange={(e) =>
                  setCandidate(choices.find((r) => r.id === e.target.value)!)
                }
              >
                {choices.map((r) => (
                  <option key={r.id} value={r.id}>
                    {utc(r.created_utc)} · {r.weather_provider} ·{" "}
                    {distance(r.distance_m)} · {r.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Time alignment</span>
              <select
                aria-label="Comparison time alignment"
                value={alignment}
                onChange={(e) =>
                  setAlignment(e.target.value as typeof alignment)
                }
              >
                <option value="elapsed">Equal elapsed time since launch</option>
                <option value="utc">Equal UTC within shared horizon</option>
              </select>
            </label>
            <label className="field">
              <span>Aligned sample count</span>
              <select
                aria-label="Comparison sample count"
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
              >
                {[121, 241, 481, 1001].map((n) => (
                  <option key={n} value={n}>
                    {n} aligned samples
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="form-actions">
            <button
              className="button primary"
              disabled={!a || !b || a.id === b.id || comparison.isPending}
              onClick={() => {
                if (!a || !b) return;
                setReference(a);
                setCandidate(b);
                comparison.mutate();
              }}
            >
              {comparison.isPending
                ? "Aligning saved trajectories…"
                : "Compare studies"}
            </button>
            {result && (
              <button
                className="button secondary"
                onClick={() =>
                  downloadJson(
                    `stratos-comparison-${result.comparison_sha256.slice(0, 12)}.json`,
                    result,
                  )
                }
              >
                <Download size={14} />
                Export comparison
              </button>
            )}
            <span className="muted">
              Saved results only · no new weather download
            </span>
          </div>
          {comparison.error && (
            <div className="notice error" role="alert">
              <ShieldAlert size={16} />
              {comparison.error.message}
              {result && " — The previous valid comparison remains below."}
            </div>
          )}
          {dirty && (
            <p className="slice-pending" role="status">
              Selection changed. Compare again to update the pinned result
              below.
            </p>
          )}
          {result && selected && (
            <>
              <div className="notice neutral">
                <ShieldAlert size={16} />
                <span>
                  <strong>MODELED SCENARIO SENSITIVITY.</strong> Both paths are
                  uncalibrated predictions. {result.alignment_description}.
                </span>
              </div>
              <div className="comparison-sources">
                {result.sources.map((source, i) => (
                  <div key={i}>
                    <strong>
                      {i === 0 ? "Reference" : "Candidate"}: {source.name}
                    </strong>
                    <span>
                      {source.weather_provider} · {source.solver_version} ·{" "}
                      {source.saved_sample_count} saved snapshots
                    </span>
                    {source.weather_run_utc && (
                      <span>GFS cycle {utc(source.weather_run_utc)}</span>
                    )}
                    <code>{source.id}</code>
                  </div>
                ))}
              </div>
              <div className="comparison-metrics">
                <div>
                  <span>MAXIMUM SAMPLED SEPARATION</span>
                  <strong>
                    {distance(result.metrics.maximum_sampled_separation_m)}
                  </strong>
                </div>
                <div>
                  <span>SHARED-WINDOW END SEPARATION</span>
                  <strong>
                    {distance(result.metrics.shared_window_end_separation_m)}
                  </strong>
                </div>
                <div>
                  <span>MAXIMUM SAMPLED HEIGHT DIFFERENCE</span>
                  <strong>
                    {distance(
                      result.metrics
                        .maximum_absolute_sampled_height_difference_m,
                    )}
                  </strong>
                </div>
                <div>
                  <span>SHARED COMPARISON WINDOW</span>
                  <strong>{duration(result.duration_s)}</strong>
                </div>
              </div>
              <TrajectoryMap
                samples={paths.reference}
                secondarySamples={paths.candidate}
                index={Math.min(index, result.points.length - 1)}
                synthetic={result.sources.some(
                  (r) => r.weather_provider === "SYNTHETIC",
                )}
                onSelect={setIndex}
              />
              <div
                className="comparison-chart"
                role="region"
                aria-label="Aligned scenario separation chart"
              >
                <div className="profile-heading">
                  <h3>Horizontal separation · sampled</h3>
                  <span>
                    0 → {distance(result.metrics.maximum_sampled_separation_m)}
                  </span>
                </div>
                <svg
                  viewBox="0 0 1000 130"
                  role="img"
                  aria-label="Sampled horizontal separation over shared time"
                  preserveAspectRatio="none"
                  onClick={(e) => {
                    const rect = e.currentTarget.getBoundingClientRect();
                    setIndex(
                      Math.max(
                        0,
                        Math.min(
                          result.points.length - 1,
                          Math.round(
                            ((e.clientX - rect.left) / rect.width) *
                              (result.points.length - 1),
                          ),
                        ),
                      ),
                    );
                  }}
                >
                  <line x1="10" x2="990" y1="112" y2="112" stroke="#39424a" />
                  <polyline
                    points={graph}
                    fill="none"
                    stroke="#b0c9d3"
                    strokeWidth="2"
                  />
                  <line
                    x1={10 + (index / (result.points.length - 1)) * 980}
                    x2={10 + (index / (result.points.length - 1)) * 980}
                    y1="10"
                    y2="118"
                    stroke="#deb77a"
                  />
                </svg>
                <input
                  type="range"
                  aria-label="Comparison timeline"
                  min={0}
                  max={result.points.length - 1}
                  value={index}
                  onChange={(e) => setIndex(e.target.valueAsNumber)}
                />
                <div className="comparison-readout">
                  <span>
                    Sample separation{" "}
                    <strong>
                      {distance(selected.horizontal_separation_m)}
                    </strong>
                  </span>
                  <span>
                    Candidate − reference height{" "}
                    <strong>{distance(selected.height_difference_m)}</strong>
                  </span>
                </div>
                <div className="comparison-times">
                  <span>
                    Reference {utc(selected.reference.time_utc)} ·{" "}
                    {selected.reference.geometric_msl_m.toFixed(1)}m MSL
                  </span>
                  <span>
                    Candidate {utc(selected.candidate.time_utc)} ·{" "}
                    {selected.candidate.geometric_msl_m.toFixed(1)}m MSL
                  </span>
                </div>
              </div>
              <div className="profile-heading">
                <h3>Changed configuration fields</h3>
                <span>
                  {result.configuration_differences.length} differences
                </span>
              </div>
              <div
                className="profile-table"
                role="region"
                aria-label="Compared configuration differences"
                tabIndex={0}
              >
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Field</th>
                      <th scope="col">Reference</th>
                      <th scope="col">Candidate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.configuration_differences.map((row) => (
                      <tr key={row.field}>
                        <td>
                          <code>{row.field}</code>
                        </td>
                        <td>{value(row.reference)}</td>
                        <td>{value(row.candidate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="fine-print">
                {result.sample_count} aligned display samples interpolate saved
                snapshots along WGS84 geodesics; height interpolates linearly.
                Statistics cover this shared window and sampled grid. Retain
                both original simulation exports for reproducible analysis.
              </p>
              <p className="fine-print slice-hash">
                Comparison SHA-256 <code>{result.comparison_sha256}</code>
              </p>
            </>
          )}
        </>
      )}
    </section>
  );
}

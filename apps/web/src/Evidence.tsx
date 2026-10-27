import { ArrowDownToLine, Check, FileJson } from "lucide-react";
import { utc } from "./api";
import type { Simulation } from "./types";
export function Evidence({ run }: { run: Simulation | undefined }) {
  if (!run)
    return (
      <div className="empty-state">
        No finalized run. Complete a simulation to inspect its manifest.
      </div>
    );
  return (
    <section className="evidence-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">REPRODUCIBILITY MANIFEST</span>
          <h2>Every prediction leaves a trail.</h2>
          <p>
            {utc(run.created_utc)} · {run.id}
          </p>
        </div>
        <FileJson size={27} />
      </div>
      <div className="notice neutral">
        <Check size={17} />
        <span>
          Original configuration and calculated results are saved locally.
          Export JSON to retain all samples and the manifest together.
        </span>
      </div>
      <dl className="evidence-values">
        <div>
          <dt>Output SHA-256</dt>
          <dd>{run.manifest.output_sha256}</dd>
        </div>
        <div>
          <dt>Mission configuration SHA-256</dt>
          <dd>{run.manifest.config_sha256}</dd>
        </div>
        <div>
          <dt>Manifest SHA-256</dt>
          <dd>{run.manifest.sha256}</dd>
        </div>
        <div>
          <dt>Source tree SHA-256</dt>
          <dd>{run.manifest.code.source_tree_sha256}</dd>
        </div>
        <div>
          <dt>Git commit</dt>
          <dd>
            {run.manifest.code.git_commit ??
              "Unborn repository — source hashes retained"}
          </dd>
        </div>
        <div>
          <dt>Weather initialization</dt>
          <dd>
            {run.manifest.weather.run_utc
              ? utc(run.manifest.weather.run_utc)
              : "Synthetic analytic field — no NOAA cycle"}
          </dd>
        </div>
      </dl>
      <h3>Model limitations</h3>
      <ul className="limitations">
        {run.limitations.map((v) => (
          <li key={v}>{v}</li>
        ))}
      </ul>
      <div className="form-actions">
        <a
          className="button primary"
          href={`/api/simulations/${run.id}/export`}
          download
        >
          <ArrowDownToLine size={15} />
          Complete JSON
        </a>
        <a
          className="button secondary"
          href={`/api/simulations/${run.id}/export?format=csv`}
          download
        >
          <ArrowDownToLine size={15} />
          Sample CSV
        </a>
      </div>
      <details>
        <summary>Inspect exact configuration and weather provenance</summary>
        <pre>
          {JSON.stringify(
            {
              config: run.manifest.config,
              weather: run.manifest.weather,
              packages: run.manifest.code.packages,
            },
            null,
            2,
          )}
        </pre>
      </details>
    </section>
  );
}

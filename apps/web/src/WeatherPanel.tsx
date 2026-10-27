import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowUpRight,
  Database,
  ShieldAlert,
  Wind,
} from "lucide-react";
import { api, utc } from "./api";
import type {
  Dataset,
  DownloadInput,
  Estimate,
  Job,
  WeatherRun,
} from "./types";
import { NumberField } from "./Fields";
import { WeatherExplorer } from "./WeatherExplorer";
function initialCycle() {
  const d = new Date(Date.now() - 6 * 3600000);
  d.setUTCHours(Math.floor(d.getUTCHours() / 6) * 6, 0, 0, 0);
  return d.toISOString();
}
export function WeatherPanel({
  datasets,
  onJob,
}: {
  datasets: Dataset[];
  onJob: () => void;
}) {
  const [input, setInput] = useState<DownloadInput>({
    run_utc: initialCycle(),
    first_lead_hour: 0,
    last_lead_hour: 48,
    west_deg: 5,
    east_deg: 20,
    south_deg: 40,
    north_deg: 52,
  });
  const [estimate, setEstimate] = useState<{
    value: Estimate;
    input: string;
  } | null>(null);
  const [error, setError] = useState("");
  const [discovery, setDiscovery] = useState<WeatherRun[] | null>(null);
  const discover = useMutation({
    mutationFn: () => api<WeatherRun[]>("/weather/runs"),
    onSuccess: (r) => {
      setDiscovery(r);
      setError("");
    },
    onError: (e) => setError(e.message),
  });
  const estimation = useMutation({
    mutationFn: async () => {
      const fingerprint = JSON.stringify(input);
      const value = await api<Estimate>("/weather/estimate", input);
      return { value, input: fingerprint };
    },
    onSuccess: (result) => {
      setEstimate(result);
      setError("");
    },
    onError: (e) => setError(e.message),
  });
  const download = useMutation({
    mutationFn: () => api<Job>("/weather/downloads", input),
    onSuccess: () => {
      setError("");
      onJob();
    },
    onError: (e) => setError(e.message),
  });
  const ready =
    estimate &&
    estimate.input === JSON.stringify(input) &&
    estimate.value.unpacked_array_bytes <= estimate.value.memory_limit_bytes &&
    estimate.value.estimated_bytes <= estimate.value.cache_limit_bytes;
  return (
    <section className="weather-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">REAL METEOROLOGICAL INPUT</span>
          <h2>Bring the atmosphere into the model.</h2>
          <p>Cropped GFS 0.25° · deterministic · hourly leads · NOAA NOMADS</p>
        </div>
        <Wind size={28} />
      </div>
      <div className="notice neutral">
        <Database size={17} />
        <span>
          Downloads pin the exact cycle and file hashes. Missing data cause a
          visible failure; synthetic weather is never substituted.
        </span>
      </div>
      <div className="weather-controls">
        <button
          className="button secondary"
          onClick={() => discover.mutate()}
          disabled={discover.isPending}
        >
          {discover.isPending ? "Checking NOAA…" : "Discover published cycles"}
          <ArrowUpRight size={15} />
        </button>
        {discovery && (
          <span className="muted">
            {discovery.length} cycles with available files
          </span>
        )}
      </div>
      {discovery && (
        <div className="cycle-list">
          {discovery.map((r) => (
            <button
              className={`cycle ${input.run_utc === r.run_utc ? "selected" : ""}`}
              key={r.run_utc}
              onClick={() => setInput({ ...input, run_utc: r.run_utc })}
            >
              {utc(r.run_utc)}
              <span>
                {r.published_leads_hours.length} published leads ·{" "}
                {r.age_hours.toFixed(1)}h old
              </span>
            </button>
          ))}
        </div>
      )}
      <div className="form-grid">
        <label className="field span-2">
          <span>Exact initialization · UTC</span>
          <input
            type="datetime-local"
            value={input.run_utc.slice(0, 16)}
            onChange={(e) => {
              if (e.target.value)
                setInput({ ...input, run_utc: e.target.value + ":00Z" });
            }}
          />
          <small>
            00 / 06 / 12 / 18 UTC. Availability must be verified by NOAA. Select
            at most a 72h window within hourly leads 0–120.
          </small>
        </label>
        <NumberField
          label="First forecast lead · h"
          value={input.first_lead_hour}
          min={0}
          max={119}
          onChange={(n) => setInput({ ...input, first_lead_hour: n })}
        />
        <NumberField
          label="Last forecast lead · h"
          value={input.last_lead_hour}
          min={1}
          max={120}
          onChange={(n) => setInput({ ...input, last_lead_hour: n })}
        />
        {(["west", "east", "south", "north"] as const).map((key) => (
          <NumberField
            key={key}
            label={`${key[0].toUpperCase() + key.slice(1)} boundary · °`}
            value={input[`${key}_deg`]}
            step={0.25}
            onChange={(n) => setInput({ ...input, [`${key}_deg`]: n })}
          />
        ))}
      </div>
      <div className="download-footer">
        <button
          className="button secondary"
          onClick={() => estimation.mutate()}
          disabled={estimation.isPending}
        >
          Estimate download
        </button>
        {estimate && estimate.input === JSON.stringify(input) && (
          <div className="download-estimate">
            <strong>
              ≈ {(estimate.value.estimated_bytes / 1048576).toFixed(1)} MiB
            </strong>
            <span>
              {estimate.value.files} files ·{" "}
              {(estimate.value.unpacked_array_bytes / 1048576).toFixed(0)} MiB
              arrays · 512 MiB cache cap · pacing alone ≥{" "}
              {(estimate.value.minimum_filter_wait_seconds / 60).toFixed(1)} min
            </span>
          </div>
        )}
        <button
          className="button primary"
          disabled={!ready || download.isPending}
          onClick={() => download.mutate()}
        >
          <ArrowDownToLine size={15} /> Download selected subset
        </button>
      </div>
      {estimate && estimate.input === JSON.stringify(input) && !ready && (
        <div className="notice error" role="alert">
          This crop exceeds the declared memory or cache budget. Reduce the
          geographic bounds or forecast duration before downloading.
        </div>
      )}
      {error && (
        <div className="notice error" role="alert">
          <ShieldAlert size={17} />
          <span>{error}</span>
        </div>
      )}
      <div className="section-subheading">
        <h3>Verified local datasets</h3>
        <span>{datasets.length} cached</span>
      </div>
      {!datasets.length ? (
        <p className="empty-state">
          No NOAA dataset cached. Discover a supported cycle and download a
          bounded region. Offline synthetic simulation remains available.
        </p>
      ) : (
        datasets.map((d) => (
          <div className="dataset" key={d.id}>
            <Database size={19} />
            <div>
              <strong>GFS · {utc(d.run_utc)}</strong>
              <span>
                {utc(d.valid_start_utc)} → {utc(d.valid_end_utc)}
              </span>
              <code>{d.sha256.slice(0, 20)}…</code>
            </div>
            <span>
              {(
                d.files.reduce((s, f) => s + f.size_bytes, 0) / 1048576
              ).toFixed(1)}{" "}
              MiB
            </span>
          </div>
        ))
      )}
      <p className="fine-print">
        Pressure-level HGT / U / V / temperature plus surface fields. Automatic
        adjacent-crop fetching is an explicit, bounded simulation option. No
        ensemble or terrain-recovery model. GFS is a forecast, not a
        measurement.
      </p>
      {datasets.length > 0 && <WeatherExplorer datasets={datasets} />}
    </section>
  );
}

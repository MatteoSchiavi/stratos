import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Check,
  Download,
  Plus,
  Radio,
  Trash2,
  Upload,
} from "lucide-react";
import { api, downloadJson, utc } from "./api";
import { NumberField } from "./Fields";
import type { Job, SimulationSummary } from "./types";

type Observation = {
  time_s: number;
  sequence: number;
  latitude_deg: number | null;
  longitude_deg: number | null;
  altitude_m: number | null;
  temperature_k: number | null;
  voltage_v: number | null;
  pressure_pa: number | null;
  clock_valid: boolean;
  fix_valid: boolean;
  origin: "measured" | "simulated" | "assumed";
};
type Contact = {
  channels_hz: number[] | null;
  start_s: number;
  end_s: number;
  receiver_id: string;
  region: "EU868" | "US915";
  data_rates: number[];
  compatible: boolean;
  evidence: "assumed" | "predicted" | "observed";
  source: string;
  loss_probability: number;
};
type Configuration = {
  epoch_utc: string;
  position_source: { simulation_id: string; output_sha256: string } | null;
  schema_version: 1;
  duration_s: number;
  step_s: number;
  sample_interval_s: number;
  fresh_interval_s: number;
  max_fix_age_s: number;
  history_batch: number;
  history_repeats: number;
  seed: number;
  fopts_bytes: number;
  fair_use_s_per_24h: number | null;
  fresh_airtime_fraction: number;
  positions: Observation[];
  contacts: Contact[];
  outages: { start_s: number; end_s: number }[];
  profiles: {
    name: string;
    region: "EU868" | "US915";
    start_s: number;
    end_s: number;
    south: number;
    north: number;
    west: number;
    east: number;
    permission_configured: boolean;
    permission_reference: string;
    duty_fraction: number;
    dwell_limit_ms: number | null;
  }[];
  power: {
    battery_initial_j: number;
    battery_capacity_j: number;
    reserve_j: number;
    harvest_w: number;
    idle_w: number;
    tx_w: number;
    rx_allowance_j: number;
    capacitor_f: number;
    initial_voltage_v: number;
    max_voltage_v: number;
    wake_voltage_v: number;
    sleep_voltage_v: number;
    charge_w: number;
    efficiency: number;
  };
};
type RadioResult = {
  valid: boolean;
  errors: string[];
  sf: number;
  bandwidth_hz: number;
  application_limit_bytes: number;
  application_bytes: number;
  lorawan_overhead_bytes: number;
  phy_bytes: number;
  airtime_s: number | null;
  scope: string;
};
type Packet = {
  hex: string;
  family: string;
  bytes: number;
  integrity: string;
  observations: Observation[];
};
type Batch = {
  input_fingerprint?: string;
  recommended_batch_size: number | null;
  assumptions: string;
  candidates: {
    batch_size: number;
    packet_bytes: number;
    fresh_interval_s: number;
    max_collection_delay_s: number;
    airtime_used_s: number | null;
    lost_records_per_failed_packet: number;
    loss_variance_per_packet: number;
    feasible: boolean;
  }[];
};
type Study = {
  id: string;
  created_utc: string;
  sha256: string;
  configuration: Configuration;
  output: {
    freshness: {
      first_received_position_s: number | null;
      max_known_position_age_s: number | null;
      mean_known_position_age_s: number | null;
      final_position_age_s: number | null;
    };
    metrics: Record<string, number>;
    blocked_steps: Record<string, number>;
    timeline: {
      time_s: number;
      pending_records: number;
      received_records: number;
      battery_j: number;
      capacitor_v: number;
    }[];
    events: {
      time_s: number;
      family: string;
      region: string;
      sf: number;
      bandwidth_hz: number;
      received: boolean;
      record_indices: number[];
      airtime_s: number;
      decision: string;
      opportunity_receiver_ids: string[];
    }[];
    limitations: string[];
  };
};
type Archive = {
  input_fingerprint?: string;
  id: string;
  archive_bytes: number;
  original_bytes: number;
  record_count: number;
  round_trip_verified: boolean;
  source_sha256: string;
  archive_sha256: string;
  summary: {
    retained_count: number;
    original_count: number;
    limitations: string;
    records: { index: number; reasons: string[]; observation: Observation }[];
  };
};
const rates = {
  EU868: [
    "SF12 / 125 kHz",
    "SF11 / 125 kHz",
    "SF10 / 125 kHz",
    "SF9 / 125 kHz",
    "SF8 / 125 kHz",
    "SF7 / 125 kHz",
    "SF7 / 250 kHz",
  ],
  US915: [
    "SF10 / 125 kHz · 11 B",
    "SF9 / 125 kHz",
    "SF8 / 125 kHz",
    "SF7 / 125 kHz",
    "SF8 / 500 kHz",
  ],
};
const nf = (v: number | undefined, digits = 0) =>
  v === undefined
    ? "—"
    : v.toLocaleString(undefined, { maximumFractionDigits: digits });

const stable = (value: unknown) =>
  JSON.stringify(value, (key, v) => {
    if (key === "epoch_utc" && typeof v === "string")
      return new Date(v).toISOString();
    return v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(
          Object.entries(v).sort(([a], [b]) => a.localeCompare(b)),
        )
      : v;
  });

export function TelemetryPanel({ studies }: { studies: SimulationSummary[] }) {
  const qc = useQueryClient();
  const example = useQuery({
    queryKey: ["telemetry-example"],
    queryFn: () => api<Configuration>("/telemetry/example"),
  });
  const saved = useQuery({
    queryKey: ["telemetry-studies"],
    queryFn: () =>
      api<{ id: string; created_utc: string }[]>("/telemetry/studies"),
    refetchInterval: 3000,
  });
  const savedArchives = useQuery({
    queryKey: ["telemetry-archives"],
    queryFn: () =>
      api<{ id: string; created_utc: string; record_count: number }[]>(
        "/telemetry/archives",
      ),
    refetchInterval: 3000,
  });
  const [draft, setDraft] = useState<Configuration | null>(null);
  const config = draft ?? example.data;
  const [task, setTask] = useState("recovery");
  const [error, setError] = useState("");
  const [family, setFamily] = useState("NAV+ENV");
  const [region, setRegion] = useState<"EU868" | "US915">("EU868");
  const [dr, setDr] = useState(5);
  const [airtimeBudget, setAirtimeBudget] = useState(30);
  const [packet, setPacket] = useState<{
    packet: Packet;
    radio: RadioResult;
    fingerprint: string;
  } | null>(null);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [hexInput, setHexInput] = useState("");
  const [decoded, setDecoded] = useState<Packet | null>(null);
  const [rawDraft, setRawDraft] = useState<string | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [pathId, setPathId] = useState("");
  const [pathStatus, setPathStatus] = useState("");
  const [archive, setArchive] = useState<Archive | null>(null);
  const [archiveStatus, setArchiveStatus] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [selectedStudy, setSelectedStudy] = useState<string | null>(() =>
    new URLSearchParams(location.search).get("recovery"),
  );
  const job = useQuery({
    queryKey: ["telemetry-job", jobId],
    queryFn: () => api<Job>(`/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) =>
      q.state.data &&
      ["completed", "failed", "cancelled", "interrupted"].includes(
        q.state.data.status,
      )
        ? false
        : 500,
  });
  const studyId =
    selectedStudy ??
    (job.data?.status === "completed" ? job.data.result_id : null);
  const result = useQuery({
    queryKey: ["telemetry-study", studyId],
    queryFn: () => api<Study>(`/telemetry/studies/${studyId}`),
    enabled: !!studyId,
  });
  const update = <K extends keyof Configuration>(
    key: K,
    value: Configuration[K],
  ) => {
    if (config) setDraft({ ...config, [key]: value });
  };
  const fingerprint = JSON.stringify({
    family,
    region,
    dr,
    positions: config?.positions,
    fopts: config?.fopts_bytes,
  });
  const encode = useMutation({
    mutationFn: async () => {
      if (!config) throw new Error("Inputs are loading");
      const requestFingerprint = fingerprint;
      const p = await api<Packet>("/telemetry/codec/encode", {
        family,
        observations: config.positions.slice(0, family === "HISTORY" ? 8 : 1),
      });
      const r = await api<RadioResult>("/telemetry/radio/validate", {
        region,
        data_rate: dr,
        application_bytes: p.bytes,
        fopts_bytes: config.fopts_bytes,
      });
      return { packet: p, radio: r, fingerprint: requestFingerprint };
    },
    onSuccess: (v) => {
      setPacket(v);
      setHexInput(v.packet.hex);
      setError("");
    },
    onError: (e) => setError(e.message),
  });
  const batchFingerprint = stable({ config, region, dr, airtimeBudget });
  const archiveFingerprint = stable({
    sourceId,
    positions: sourceId ? null : config?.positions,
    epoch: sourceId ? null : config?.epoch_utc,
  });
  const compare = useMutation({
    mutationFn: () => {
      const identity = batchFingerprint;
      return api<Batch>("/telemetry/batches/optimize", {
        observations: config!.positions.slice(0, 16),
        radio: { region, data_rate: dr, fopts_bytes: config!.fopts_bytes },
        sample_interval_s: config!.sample_interval_s,
        horizon_s: config!.duration_s,
        available_airtime_s: airtimeBudget,
        loss_probability: config!.contacts[0]?.loss_probability ?? 0.2,
        max_fresh_interval_s: config!.fresh_interval_s,
      }).then((v) => ({ ...v, input_fingerprint: identity }));
    },
    onSuccess: (v) => {
      setBatch(v);
      setError("");
    },
    onError: (e) => setError(e.message),
  });
  const submit = useMutation({
    mutationFn: () => api<Job>("/telemetry/studies", config),
    onSuccess: (v) => {
      setJobId(v.id);
      setSelectedStudy(null);
      setError("");
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e) => setError(e.message),
  });
  const archiveAction = useMutation({
    mutationFn: () => {
      const identity = archiveFingerprint;
      return api<Archive>(
        "/telemetry/archives",
        sourceId
          ? { simulation_id: sourceId }
          : { observations: config!.positions, epoch_utc: config!.epoch_utc },
      ).then((v) => ({ ...v, input_fingerprint: identity }));
    },
    onSuccess: (v) => {
      setArchive(v);
      setError("");
      setArchiveStatus("");
    },
    onError: (e) => setError(e.message),
  });
  useEffect(() => {
    if (!result.data?.id) return;
    const url = new URL(location.href);
    url.searchParams.set("recovery", result.data.id);
    history.replaceState(null, "", url);
  }, [result.data?.id]);

  async function loadPath() {
    try {
      const value = await api<{
        observations: Observation[];
        epoch_utc: string;
        output_sha256: string;
      }>(`/telemetry/sources/${pathId}`);
      if (!config) return;
      setDraft({
        ...config,
        positions: value.observations,
        epoch_utc: value.epoch_utc,
        position_source: {
          simulation_id: pathId,
          output_sha256: value.output_sha256,
        },
        duration_s: Math.max(
          60,
          Math.min(
            259200,
            value.observations.at(-1)?.time_s ?? config.duration_s,
          ),
        ),
      });
      setPathStatus(
        `Loaded ${value.observations.length} modeled path samples. Review contact windows and permission intervals for this horizon.`,
      );
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function applyJson() {
    try {
      const value = JSON.parse(rawDraft ?? JSON.stringify(config));
      const valid = await api<Configuration>(
        "/telemetry/configuration/validate",
        value,
      );
      setDraft(valid);
      setRawDraft(null);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  async function restore(file: File) {
    try {
      if (file.size > 4 * 1024 * 1024)
        throw new Error("Archive import is limited to 4 MiB");
      const r = await fetch("/api/telemetry/archives/decode", {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      });
      const value = await r.json();
      if (!r.ok) throw new Error(value.detail ?? "Archive verification failed");
      setArchiveStatus(
        `Verified and decoded ${value.observations.length} original records. Export JSON to keep the restored copy.`,
      );
      downloadJson("stratos-restored-observations.json", {
        context: value.context,
        observations: value.observations,
      });
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  if (!config)
    return (
      <p role="status">
        {example.error?.message ?? "Loading telemetry inputs…"}
      </p>
    );
  const current = result.data;
  const changed = current && stable(current.configuration) !== stable(config);
  return (
    <section
      className="telemetry-workspace"
      aria-label="Telemetry protocol and recovery"
    >
      <div
        className="task-navigation"
        role="tablist"
        aria-label="Telemetry tasks"
      >
        {[
          ["protocol", "1 · Packet & airtime"],
          ["recovery", "2 · Recovery planner"],
          ["archive", "3 · Archive & summaries"],
        ].map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={task === id}
            onClick={() => setTask(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="telemetry-provenance">
        <span className="tiny-dot amber" />
        <span>
          Engineering study ·{" "}
          {config.positions.filter((p) => p.origin === "measured").length}{" "}
          measured input records · contacts and energy remain entered
          assumptions
        </span>
        <span>No transmitter connected</span>
      </div>
      {rawDraft !== null && (
        <p className="slice-pending">
          Full configuration has unapplied JSON edits. Validate & apply them
          below before running.
        </p>
      )}
      {error && (
        <div className="notice error" role="alert">
          {error}
          <button onClick={() => setError("")}>Dismiss</button>
        </div>
      )}
      {task === "protocol" && (
        <>
          <div className="task-intro">
            <h2>Choose a packet. Check where it fits.</h2>
            <p>
              Exact encoded bytes, regional limits and LoRaWAN overhead.
              Protocol v1 uses an explicit mission epoch.
            </p>
          </div>
          <div className="telemetry-card">
            <div className="form-grid protocol-fields">
              <label className="field">
                <span>Packet family</span>
                <select
                  aria-label="Packet family"
                  value={family}
                  onChange={(e) => setFamily(e.target.value)}
                >
                  {["NAV", "NAV+ENV", "HISTORY", "EMERGENCY"].map((f) => (
                    <option key={f}>{f}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Radio region</span>
                <select
                  aria-label="Radio region"
                  value={region}
                  onChange={(e) => {
                    const r = e.target.value as typeof region;
                    setRegion(r);
                    setDr(r === "US915" ? 0 : 5);
                    setBatch(null);
                  }}
                >
                  <option>EU868</option>
                  <option>US915</option>
                </select>
              </label>
              <label className="field">
                <span>Uplink data rate</span>
                <select
                  aria-label="Uplink data rate"
                  value={dr}
                  onChange={(e) => {
                    setDr(+e.target.value);
                    setBatch(null);
                  }}
                >
                  {rates[region].map((v, i) => (
                    <option key={i} value={i}>
                      DR{i} · {v}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="inline-actions">
              <button
                className="button primary"
                disabled={encode.isPending}
                onClick={() => encode.mutate()}
              >
                {encode.isPending ? "Encoding…" : "Encode & validate"}
                <ArrowRight size={14} />
              </button>
              <span>
                Uses{" "}
                {family === "HISTORY"
                  ? Math.min(8, config.positions.length)
                  : 1}{" "}
                record(s) from current inputs. Edit under input data below.
              </span>
            </div>
          </div>
          {packet && (
            <div
              className="telemetry-card"
              aria-label="Packet validation result"
            >
              {packet.fingerprint !== fingerprint && (
                <p className="slice-pending">
                  Inputs changed. Encode again to update this result.
                </p>
              )}
              <div className="result-title">
                <h3>
                  {packet.packet.family} · {packet.packet.bytes} bytes
                </h3>
                <span
                  className={packet.radio.valid ? "status-good" : "status-bad"}
                >
                  {packet.radio.valid
                    ? "Fits selected profile"
                    : "Does not fit selected profile"}
                </span>
              </div>
              <div className="compact-metrics">
                <div>
                  <small>ON AIR</small>
                  <strong>
                    {nf((packet.radio.airtime_s ?? 0) * 1000, 3)} ms
                  </strong>
                </div>
                <div>
                  <small>APPLICATION LIMIT</small>
                  <strong>{packet.radio.application_limit_bytes} B</strong>
                </div>
                <div>
                  <small>LoRaWAN OVERHEAD</small>
                  <strong>{packet.radio.lorawan_overhead_bytes} B</strong>
                </div>
                <div>
                  <small>PHY PAYLOAD</small>
                  <strong>{packet.radio.phy_bytes} B</strong>
                </div>
              </div>
              {packet.radio.errors.map((e) => (
                <p key={e} className="status-bad">
                  {e}
                </p>
              ))}
              <code className="packet-hex">{packet.packet.hex}</code>
              <p className="fine-print">
                {packet.packet.integrity.replaceAll("_", " ")}. CRC is not
                authentication. EMERGENCY relies on an externally verified
                LoRaWAN MIC.
              </p>
              <details>
                <summary>Decoded values & quantization</summary>
                <pre>{JSON.stringify(packet.packet, null, 2)}</pre>
              </details>
            </div>
          )}
          <details className="telemetry-card">
            <summary>Batching trade study</summary>
            <p className="task-description">
              Compare actual encoded groups. Larger groups save overhead but
              delay fresh tracking and lose more records together.
            </p>
            <NumberField
              label="Available airtime · s"
              value={airtimeBudget}
              min={0.001}
              max={86400}
              step="any"
              onChange={setAirtimeBudget}
            />
            <button
              className="button secondary"
              disabled={compare.isPending}
              onClick={() => compare.mutate()}
            >
              Compare batch sizes
            </button>
            {batch && (
              <>
                {batch.input_fingerprint !== batchFingerprint && (
                  <p className="slice-pending">
                    Inputs changed. Compare again to update this trade study.
                  </p>
                )}
                <p className="task-description">
                  {batch.recommended_batch_size === null
                    ? "No group meets these constraints."
                    : `Lowest airtime per record within constraints: ${batch.recommended_batch_size} records.`}
                </p>
                <div className="table-scroll">
                  <table className="engineering-table">
                    <thead>
                      <tr>
                        <th>Records</th>
                        <th>Bytes</th>
                        <th>Fresh interval</th>
                        <th>Collection delay</th>
                        <th>Total airtime</th>
                        <th>Lost / failure</th>
                        <th>Fits constraints</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batch.candidates.map((c) => (
                        <tr key={c.batch_size}>
                          <td>{c.batch_size}</td>
                          <td>{c.packet_bytes}</td>
                          <td>{c.fresh_interval_s}s</td>
                          <td>{c.max_collection_delay_s}s</td>
                          <td>{nf(c.airtime_used_s ?? undefined, 3)}s</td>
                          <td>{c.lost_records_per_failed_packet}</td>
                          <td>{c.feasible ? "Yes" : "No"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="fine-print">{batch.assumptions}</p>
              </>
            )}
          </details>
          <details className="telemetry-card">
            <summary>Decode a received packet</summary>
            <label className="field">
              <span>Raw packet hex</span>
              <textarea
                aria-label="Raw packet hex"
                value={hexInput}
                onChange={(e) => setHexInput(e.target.value)}
                spellCheck={false}
              />
            </label>
            <button
              className="button secondary"
              onClick={() => {
                void api<Packet>("/telemetry/codec/decode", { hex: hexInput })
                  .then((v) => {
                    setDecoded(v);
                    setError("");
                  })
                  .catch((e) => setError(e.message));
              }}
            >
              Decode packet
            </button>
            {decoded && <pre>{JSON.stringify(decoded, null, 2)}</pre>}
          </details>
        </>
      )}
      {task === "recovery" && (
        <>
          <div className="task-intro">
            <h2>What survives the next outage?</h2>
            <p>
              Set a logging cadence and receiver contact windows, then calculate
              a reproducible recovery budget.
            </p>
          </div>
          <div className="inline-actions run-recovery">
            <button
              className="button primary"
              disabled={
                submit.isPending ||
                (!!job.data &&
                  ["queued", "running"].includes(job.data.status)) ||
                rawDraft !== null
              }
              onClick={() => submit.mutate()}
            >
              <Radio size={15} />
              {submit.isPending ? "Queuing…" : "Calculate recovery"}
            </button>
            <button
              className="button secondary"
              onClick={() =>
                downloadJson("stratos-recovery-configuration.json", config)
              }
            >
              <Download size={14} /> Export inputs
            </button>
            <span>Seed {config.seed} · fixed repeats · no delivery oracle</span>
          </div>
          <details className="study-inputs" open={!current || !!changed}>
            <summary>
              Study inputs · {config.sample_interval_s}s logging ·{" "}
              {config.contacts.length} contact windows
            </summary>
            <details className="telemetry-card">
              <summary>Use a saved trajectory as the position source</summary>
              <label className="field">
                <span>Saved position source</span>
                <select
                  aria-label="Saved position source"
                  value={pathId}
                  onChange={(e) => setPathId(e.target.value)}
                >
                  <option value="">Choose a saved trajectory</option>
                  {studies.map((r) => (
                    <option value={r.id} key={r.id}>
                      {utc(r.created_utc)} · {r.weather_provider} ·{" "}
                      {r.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="button secondary"
                disabled={!pathId}
                onClick={() => void loadPath()}
              >
                Use this path
              </button>
              {pathStatus && (
                <p className="task-description" role="status">
                  {pathStatus}
                </p>
              )}
            </details>
            <div className="telemetry-card">
              <div className="form-grid">
                <label className="field">
                  <span>Mission epoch · UTC</span>
                  <input
                    aria-label="Mission epoch · UTC"
                    type="datetime-local"
                    value={config.epoch_utc.slice(0, 16)}
                    onChange={(e) => {
                      if (e.target.value)
                        update("epoch_utc", e.target.value + ":00Z");
                    }}
                  />
                </label>
                <NumberField
                  label="Study duration · s"
                  value={config.duration_s}
                  min={60}
                  max={259200}
                  onChange={(v) => update("duration_s", v)}
                />
                <NumberField
                  label="Log interval · s"
                  value={config.sample_interval_s}
                  min={10}
                  max={3600}
                  onChange={(v) => update("sample_interval_s", v)}
                />
                <NumberField
                  label="Fresh tracking interval · s"
                  value={config.fresh_interval_s}
                  min={10}
                  max={86400}
                  onChange={(v) => update("fresh_interval_s", v)}
                />
                <NumberField
                  label="History records per packet"
                  value={config.history_batch}
                  min={1}
                  max={32}
                  onChange={(v) => update("history_batch", v)}
                />
              </div>
            </div>
            <div className="telemetry-card">
              <div className="result-title">
                <h3>Receiver contact windows</h3>
                <button
                  className="text-button"
                  onClick={() =>
                    update("contacts", [
                      ...config.contacts,
                      {
                        start_s: 0,
                        end_s: config.duration_s,
                        receiver_id: "entered-receiver",
                        channels_hz: null,
                        region: "EU868",
                        data_rates: [5],
                        compatible: false,
                        evidence: "assumed",
                        source: "User-entered; verify receiver compatibility",
                        loss_probability: 0.2,
                      },
                    ])
                  }
                >
                  <Plus size={14} /> Add window
                </button>
              </div>
              <p className="task-description">
                No inferred coverage circles. Times are mission-relative
                seconds; transmission must finish inside a compatible window.
              </p>
              {config.contacts.length === 0 && (
                <p className="empty-state">
                  No contacts: the scheduler will log locally and send nothing.
                </p>
              )}
              {config.contacts.map((c, i) => (
                <div className="contact-editor" key={i}>
                  <label className="field">
                    <span>Receiver identity</span>
                    <input
                      aria-label={`Receiver ${i + 1} identity`}
                      value={c.receiver_id}
                      onChange={(e) =>
                        update(
                          "contacts",
                          config.contacts.map((v, j) =>
                            j === i ? { ...v, receiver_id: e.target.value } : v,
                          ),
                        )
                      }
                    />
                  </label>
                  <NumberField
                    label={`Contact ${i + 1} start · s`}
                    value={c.start_s}
                    min={0}
                    max={config.duration_s}
                    onChange={(v) =>
                      update(
                        "contacts",
                        config.contacts.map((w, j) =>
                          j === i ? { ...w, start_s: v } : w,
                        ),
                      )
                    }
                  />
                  <NumberField
                    label={`Contact ${i + 1} end · s`}
                    value={c.end_s}
                    min={1}
                    max={config.duration_s}
                    onChange={(v) =>
                      update(
                        "contacts",
                        config.contacts.map((w, j) =>
                          j === i ? { ...w, end_s: v } : w,
                        ),
                      )
                    }
                  />
                  <NumberField
                    label={`Contact ${i + 1} packet loss`}
                    value={c.loss_probability}
                    min={0}
                    max={1}
                    step="any"
                    onChange={(v) =>
                      update(
                        "contacts",
                        config.contacts.map((w, j) =>
                          j === i ? { ...w, loss_probability: v } : w,
                        ),
                      )
                    }
                  />
                  <label className="check-field">
                    <input
                      type="checkbox"
                      checked={c.compatible}
                      onChange={(e) =>
                        update(
                          "contacts",
                          config.contacts.map((v, j) =>
                            j === i
                              ? { ...v, compatible: e.target.checked }
                              : v,
                          ),
                        )
                      }
                    />
                    Compatible
                  </label>
                  <button
                    className="icon-button"
                    aria-label={`Remove contact ${i + 1}`}
                    onClick={() =>
                      update(
                        "contacts",
                        config.contacts.filter((_, j) => j !== i),
                      )
                    }
                  >
                    <Trash2 size={16} />
                  </button>
                  <small>
                    {c.region} · DR {c.data_rates.join(", ")} · {c.evidence} ·{" "}
                    {c.source}
                  </small>
                </div>
              ))}
            </div>
            <details className="telemetry-card">
              <summary>Outages, regional permissions & power</summary>
              <p className="task-description">
                {config.outages.length} outage(s), {config.profiles.length}{" "}
                geographic profile(s). Rectangles are configured test areas, not
                authoritative borders. Unknown/stale fixes and missing
                permission block transmissions.
              </p>
              <div className="table-scroll">
                <table className="engineering-table">
                  <thead>
                    <tr>
                      <th>Region</th>
                      <th>Permission reference</th>
                      <th>Cooldown duty</th>
                      <th>Valid interval</th>
                    </tr>
                  </thead>
                  <tbody>
                    {config.profiles.map((p, i) => (
                      <tr key={i}>
                        <td>{p.region}</td>
                        <td>
                          {p.permission_configured
                            ? p.permission_reference
                            : "Not configured · radio off"}
                        </td>
                        <td>{p.duty_fraction * 100}%</td>
                        <td>
                          {p.start_s}–{p.end_s}s
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="form-grid">
                <NumberField
                  label="Battery initial · J"
                  value={config.power.battery_initial_j}
                  min={0}
                  max={10000000}
                  step="any"
                  onChange={(v) =>
                    update("power", { ...config.power, battery_initial_j: v })
                  }
                />
                <NumberField
                  label="Battery reserve · J"
                  value={config.power.reserve_j}
                  min={0}
                  max={10000000}
                  step="any"
                  onChange={(v) =>
                    update("power", { ...config.power, reserve_j: v })
                  }
                />
                <NumberField
                  label="Capacitance · F"
                  value={config.power.capacitor_f}
                  min={0.001}
                  max={10000}
                  step="any"
                  onChange={(v) =>
                    update("power", { ...config.power, capacitor_f: v })
                  }
                />
                <NumberField
                  label="Initial capacitor voltage · V"
                  value={config.power.initial_voltage_v}
                  min={0.01}
                  max={65}
                  step="any"
                  onChange={(v) =>
                    update("power", { ...config.power, initial_voltage_v: v })
                  }
                />
              </div>
              <p className="fine-print">
                Fixed harvest {config.power.harvest_w}W; incremental TX load{" "}
                {config.power.tx_w}W plus {config.power.rx_allowance_j}J RX
                allowance. No cold/ESR/solar calibration. Edit all windows,
                geographic bounds, SF/DR compatibility and power values in the
                full configuration below.
              </p>
            </details>
          </details>
          {job.data && job.data.status !== "completed" && (
            <p role="status" className="task-description">
              {job.data.status}: {job.data.message}
              <button
                className="text-button"
                onClick={() => {
                  void api(`/jobs/${jobId}/cancel`, {}).catch((e) =>
                    setError(e.message),
                  );
                }}
              >
                Cancel
              </button>
            </p>
          )}
          {current && (
            <div className="telemetry-card" aria-label="Recovery results">
              <div className="result-title">
                <h3>Recovery budget</h3>
                <button
                  className="text-button"
                  onClick={() =>
                    downloadJson(`stratos-recovery-${current.id}.json`, current)
                  }
                >
                  <Download size={14} /> Export study
                </button>
              </div>
              {changed && (
                <p className="slice-pending">
                  Inputs differ from this saved study. Calculate again to update
                  the results.
                </p>
              )}
              <p className="fine-print">
                Simulated reception under stated assumptions · saved{" "}
                {utc(current.created_utc)}
              </p>
              <div className="compact-metrics">
                <div>
                  <small>RECORDS RECOVERED</small>
                  <strong>
                    {nf(current.output.metrics.received_records)} /{" "}
                    {nf(current.output.metrics.generated_records)}
                  </strong>
                </div>
                <div>
                  <small>UNRECOVERED</small>
                  <strong>
                    {nf(current.output.metrics.unrecovered_records)}
                  </strong>
                </div>
                <div>
                  <small>AIRTIME</small>
                  <strong>{nf(current.output.metrics.airtime_s, 3)} s</strong>
                </div>
                <div>
                  <small>RADIO ENERGY</small>
                  <strong>
                    {nf(current.output.metrics.radio_energy_j, 3)} J
                  </strong>
                </div>
              </div>
              <RecoveryChart study={current} />
              <p className="task-description">
                {current.output.freshness.first_received_position_s === null
                  ? "No position was received in this scenario."
                  : `First modeled fix after ${nf(current.output.freshness.first_received_position_s, 2)}s · maximum known-position age ${nf(current.output.freshness.max_known_position_age_s ?? undefined, 1)}s.`}
              </p>
              <button
                className="text-button"
                onClick={() => {
                  setDraft(current.configuration);
                  setRawDraft(null);
                }}
              >
                Load this study’s exact inputs
              </button>
              <p className="fine-print">
                Sender backlog includes scheduled fixed repeats. It is
                independent of receiver success; retired records may remain
                unrecovered.
              </p>
              <details>
                <summary>Why the scheduler waited</summary>
                <dl className="decision-list">
                  {Object.entries(current.output.blocked_steps).map(
                    ([k, v]) => (
                      <div key={k}>
                        <dt>{k.replaceAll("_", " ")}</dt>
                        <dd>{v} checks</dd>
                      </div>
                    ),
                  )}
                </dl>
              </details>
              <details>
                <summary>
                  Transmission decisions · {current.output.events.length}
                </summary>
                <div className="table-scroll">
                  <table className="engineering-table">
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>Packet</th>
                        <th>Region / modulation</th>
                        <th>Records</th>
                        <th>Modeled delivery</th>
                      </tr>
                    </thead>
                    <tbody>
                      {current.output.events.map((e, i) => (
                        <tr key={i}>
                          <td>{e.time_s}s</td>
                          <td>{e.family}</td>
                          <td>
                            {e.region} SF{e.sf}/{e.bandwidth_hz / 1000}kHz
                          </td>
                          <td>{e.record_indices.join(", ")}</td>
                          <td>{e.received ? "Received" : "Lost"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
              <details>
                <summary>Energy accounting & limits</summary>
                <pre>{JSON.stringify(current.output.metrics, null, 2)}</pre>
                {current.output.limitations.map((l) => (
                  <p className="fine-print" key={l}>
                    {l}
                  </p>
                ))}
              </details>
              <code className="evidence-hash">
                Study SHA-256 {current.sha256}
              </code>
            </div>
          )}
          {!!saved.data?.length && (
            <details className="telemetry-card">
              <summary>
                Reopen a saved recovery study · {saved.data.length}
              </summary>
              <div className="saved-recovery-list">
                {saved.data.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => {
                      setSelectedStudy(r.id);
                      const url = new URL(location.href);
                      url.searchParams.set("recovery", r.id);
                      history.replaceState(null, "", url);
                    }}
                  >
                    {utc(r.created_utc)}
                    <span>{r.id.slice(0, 8)}</span>
                  </button>
                ))}
              </div>
            </details>
          )}
        </>
      )}
      {task === "archive" && (
        <>
          <div className="task-intro">
            <h2>Keep the original. Summarize a copy.</h2>
            <p>
              The lossless archive preserves original typed values. Radio
              quantization and scientific summaries are separate products.
            </p>
          </div>
          <div className="telemetry-card">
            <label className="field">
              <span>Archive source</span>
              <select
                aria-label="Archive source"
                value={sourceId}
                onChange={(e) => setSourceId(e.target.value)}
              >
                <option value="">
                  Current input observations · {config.positions.length} records
                </option>
                {studies.map((s) => (
                  <option key={s.id} value={s.id}>
                    Saved trajectory · {utc(s.created_utc)} ·{" "}
                    {s.weather_provider} · {s.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            <div className="inline-actions">
              <button
                className="button primary"
                disabled={archiveAction.isPending}
                onClick={() => archiveAction.mutate()}
              >
                {archiveAction.isPending
                  ? "Verifying…"
                  : "Create & verify archive"}
                <Check size={14} />
              </button>
              <label className="button secondary upload-button">
                <Upload size={14} /> Verify imported archive
                <input
                  aria-label="Import binary archive"
                  type="file"
                  accept=".stla"
                  onChange={(e) => {
                    if (e.target.files?.[0]) void restore(e.target.files[0]);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
            {archiveStatus && (
              <p role="status" className="status-good task-description">
                {archiveStatus}
              </p>
            )}
          </div>
          {archive && (
            <div
              className="telemetry-card"
              aria-label="Archive verification result"
            >
              {archive.input_fingerprint !== archiveFingerprint && (
                <p className="slice-pending">
                  Archive source changed. This result retains the previous input
                  records.
                </p>
              )}
              <div className="result-title">
                <h3>Lossless round trip verified</h3>
                <a
                  className="button secondary"
                  href={`/api/telemetry/archives/${archive.id}/binary`}
                  download
                >
                  <Download size={14} /> Download .stla
                </a>
              </div>
              <div className="compact-metrics">
                <div>
                  <small>ORIGINAL RECORDS</small>
                  <strong>{archive.record_count}</strong>
                </div>
                <div>
                  <small>CANONICAL JSON</small>
                  <strong>{nf(archive.original_bytes)} B</strong>
                </div>
                <div>
                  <small>DELTA ARCHIVE</small>
                  <strong>{nf(archive.archive_bytes)} B</strong>
                </div>
                <div>
                  <small>LOSSY SUMMARY</small>
                  <strong>{archive.summary.retained_count} records</strong>
                </div>
              </div>
              <p className="fine-print">{archive.summary.limitations}</p>
              <button
                className="text-button"
                onClick={() =>
                  downloadJson(
                    `stratos-lossy-summary-${archive.id}.json`,
                    archive.summary,
                  )
                }
              >
                <Download size={14} /> Export lossy scientific summary
              </button>
              <details>
                <summary>Retained extrema & trajectory changes</summary>
                <div className="table-scroll">
                  <table className="engineering-table">
                    <thead>
                      <tr>
                        <th>Original index</th>
                        <th>Time</th>
                        <th>Reason retained</th>
                      </tr>
                    </thead>
                    <tbody>
                      {archive.summary.records.map((r) => (
                        <tr key={r.index}>
                          <td>{r.index}</td>
                          <td>{r.observation.time_s}s</td>
                          <td>{r.reasons.join(" · ").replaceAll("_", " ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
              <code className="evidence-hash">
                Original SHA-256 {archive.source_sha256}
              </code>
              <code className="evidence-hash">
                Archive SHA-256 {archive.archive_sha256}
              </code>
            </div>
          )}
          {!!savedArchives.data?.length && (
            <details className="telemetry-card">
              <summary>
                Reopen a saved archive · {savedArchives.data.length}
              </summary>
              <div className="saved-recovery-list">
                {savedArchives.data.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => {
                      void api<Archive>(`/telemetry/archives/${r.id}`)
                        .then((v) => {
                          setArchive(v);
                          setError("");
                        })
                        .catch((e) => setError(e.message));
                    }}
                  >
                    {utc(r.created_utc)} · {r.record_count} records
                    <span>{r.id.slice(0, 8)}</span>
                  </button>
                ))}
              </div>
            </details>
          )}
        </>
      )}
      <details className="telemetry-card telemetry-inputs">
        <summary>Input data & full configuration</summary>
        <p className="task-description">
          Import your receiver windows, evidence sources, outages, permission
          profiles and chronological observations as JSON. Times are seconds
          from an explicit mission/session epoch. Example contacts are
          synthetic. Local JSON imports are limited to 2 MiB.
        </p>
        <div className="inline-actions">
          <button
            className="button secondary"
            onClick={() => {
              setDraft(example.data ?? null);
              setRawDraft(null);
              setError("");
            }}
          >
            Reset to labelled example
          </button>
          <label className="button secondary upload-button">
            <Upload size={14} /> Import configuration
            <input
              aria-label="Import recovery configuration"
              type="file"
              accept=".json"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) {
                  if (f.size > 2 * 1024 * 1024)
                    setError("Configuration exceeds 2 MiB");
                  else void f.text().then((t) => setRawDraft(t));
                }
                e.target.value = "";
              }}
            />
          </label>
        </div>
        <label className="field">
          <span>Full recovery configuration · JSON</span>
          <textarea
            aria-label="Full recovery configuration · JSON"
            className="configuration-editor"
            value={rawDraft ?? JSON.stringify(config, null, 2)}
            onChange={(e) => setRawDraft(e.target.value)}
            spellCheck={false}
          />
        </label>
        {rawDraft !== null && (
          <p className="slice-pending">
            JSON edits are pending. Apply them before calculating.
          </p>
        )}
        <button
          className="button primary"
          onClick={() => void applyJson()}
          disabled={rawDraft === null}
        >
          Validate & apply JSON
        </button>
      </details>
    </section>
  );
}

function RecoveryChart({ study }: { study: Study }) {
  const rows = study.output.timeline;
  const max = Math.max(
    1,
    ...rows.map((r) => r.pending_records),
    ...rows.map((r) => r.received_records),
  );
  const points = (field: "pending_records" | "received_records") =>
    rows
      .map(
        (r) =>
          `${20 + (r.time_s / study.configuration.duration_s) * 960},${160 - (r[field] / max) * 135}`,
      )
      .join(" ");
  return (
    <div className="recovery-chart">
      <div className="chart-key">
        <span>
          <i className="key-amber" /> Sender backlog
        </span>
        <span>
          <i className="key-cyan" /> Unique recovered records
        </span>
      </div>
      <svg
        viewBox="0 0 1000 190"
        role="img"
        aria-label="Recovery backlog and received records over mission time"
      >
        <line x1="20" y1="160" x2="980" y2="160" stroke="#45454d" />
        {study.configuration.contacts.map((c, i) => (
          <rect
            key={i}
            x={20 + (c.start_s / study.configuration.duration_s) * 960}
            width={
              ((c.end_s - c.start_s) / study.configuration.duration_s) * 960
            }
            y={20}
            height={140}
            fill="#8ac5d1"
            opacity={0.045}
          />
        ))}
        <polyline
          points={points("pending_records")}
          fill="none"
          stroke="#deb77a"
          strokeWidth="2.5"
        />
        <polyline
          points={points("received_records")}
          fill="none"
          stroke="#8ac5d1"
          strokeWidth="2.5"
        />
        <text x="20" y="184" fill="#a1a1aa" fontSize="13">
          0s
        </text>
        <text x="980" y="184" textAnchor="end" fill="#a1a1aa" fontSize="13">
          {study.configuration.duration_s}s
        </text>
      </svg>
    </div>
  );
}

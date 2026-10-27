import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  Clock3,
  Database,
  FileJson,
  FlaskConical,
  Globe2,
  Layers3,
  Orbit,
  Play,
  Radio,
  RotateCcw,
  Route,
  Settings2,
  ShieldAlert,
  Square,
  Wind,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api, duration, utc } from "./api";
import { useNow } from "./useNow";
import { TrajectoryMap } from "./LazyMap";
import { AltitudeChart } from "./AltitudeChart";
import { NumberField, Metric } from "./Fields";
import { WeatherPanel } from "./WeatherPanel";
import { Inspector } from "./Inspector";
import { Evidence } from "./Evidence";
import { ComparisonPanel } from "./ComparisonPanel";
import type {
  Dataset,
  Job,
  Mission,
  MissionConfig,
  Revision,
  Simulation,
  SimulationSummary,
} from "./types";

type View = "overview" | "plan" | "simulate" | "analyze";
const EMPTY_SAMPLES: [] = [];
const navigation: { id: View; name: string; icon: LucideIcon }[] = [
  { id: "overview", name: "Overview", icon: Layers3 },
  { id: "plan", name: "Plan", icon: Settings2 },
  { id: "simulate", name: "Simulate", icon: Orbit },
  { id: "analyze", name: "Analyze", icon: Activity },
];

export function App() {
  const qc = useQueryClient();
  const now = useNow();
  const [view, setView] = useState<View>("simulate");
  const [tab, setTab] = useState<"trajectory" | "weather" | "evidence">(
    "trajectory",
  );
  const [selectedId, setSelectedId] = useState<string | null>(() =>
    new URLSearchParams(location.search).get("simulation"),
  );
  const [sampleIndex, setSampleIndex] = useState(0);
  const [missionId, setMissionId] = useState<string | null>(null);
  const [pendingJob, setPendingJob] = useState<string | null>(null);
  const [expand, setExpand] = useState(false);
  const [tileLimit, setTileLimit] = useState(8);
  const [inputBudget, setInputBudget] = useState(64);
  const [archivePage, setArchivePage] = useState(0);
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api<{ worker: { state: string } }>("/health"),
    refetchInterval: 5000,
  });
  const totals = useQuery({
    queryKey: ["summary"],
    queryFn: () =>
      api<{ missions: number; simulations: number; datasets: number }>(
        "/summary",
      ),
    refetchInterval: 4000,
  });
  const archive = useQuery({
    queryKey: ["archive", archivePage],
    queryFn: () =>
      api<SimulationSummary[]>(
        `/simulations?limit=25&offset=${archivePage * 25}`,
      ),
    enabled: view === "analyze",
    refetchInterval: 4000,
  });
  const [draft, setDraft] = useState<MissionConfig | null>(null);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const missions = useQuery({
    queryKey: ["missions"],
    queryFn: () => api<Mission[]>("/missions"),
  });
  const mission =
    missions.data?.find((m) => m.id === missionId) ?? missions.data?.[0];
  const revision = useQuery({
    queryKey: ["revision", mission?.latest_revision_id],
    queryFn: () => api<Revision>(`/revisions/${mission!.latest_revision_id}`),
    enabled: !!mission,
  });
  const saved = useQuery({
    queryKey: ["simulations"],
    queryFn: () => api<SimulationSummary[]>("/simulations"),
    refetchInterval: 2000,
  });
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api<Job[]>("/jobs"),
    refetchInterval: 1000,
  });
  const datasets = useQuery({
    queryKey: ["datasets"],
    queryFn: () => api<Dataset[]>("/weather/datasets"),
    refetchInterval: 4000,
  });
  const activeId = selectedId ?? saved.data?.[0]?.id;
  const simulation = useQuery({
    queryKey: ["simulation", activeId],
    queryFn: () => api<Simulation>(`/simulations/${activeId}`),
    enabled: !!activeId,
  });
  const run = simulation.data;
  const samples = run?.samples ?? EMPTY_SAMPLES;
  const index = Math.min(sampleIndex, Math.max(samples.length - 1, 0));
  const config = draft ?? revision.data?.config ?? null;
  const activeJobs =
    jobs.data?.filter((j) => ["queued", "running"].includes(j.status)) ?? [];
  const lastJob = jobs.data?.[0];
  const refresh = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["jobs"] });
    void qc.invalidateQueries({ queryKey: ["simulations"] });
    void qc.invalidateQueries({ queryKey: ["archive"] });
  }, [qc]);

  useEffect(() => {
    if (!selectedId && saved.data?.[0]) {
      const url = new URL(location.href);
      url.searchParams.set("simulation", saved.data[0].id);
      history.replaceState(null, "", url);
      queueMicrotask(() => setSelectedId(saved.data![0].id));
    }
  }, [saved.data, selectedId]);

  useEffect(() => {
    const job = jobs.data?.find((j) => j.id === pendingJob);
    if (job?.status === "completed" && job.result_id) {
      const id = job.result_id;
      queueMicrotask(() => {
        setPendingJob(null);
        setSelectedId(id);
        setSampleIndex(0);
        const url = new URL(location.href);
        url.searchParams.set("simulation", id);
        history.replaceState(null, "", url);
        refresh();
      });
    }
  }, [jobs.data, pendingJob, refresh]);
  const retry = useMutation({
    mutationFn: (id: string) => api<Job>(`/jobs/${id}/retry`, {}),
    onSuccess: refresh,
    onError: (e) => setError(e.message),
  });

  const save = useMutation({
    mutationFn: () =>
      api<Revision>(`/missions/${config!.id}/revisions`, config),
    onSuccess: (revision) => {
      setDraft((current) =>
        current && JSON.stringify(current) !== JSON.stringify(revision.config)
          ? current
          : null,
      );
      setError("");
      void qc.invalidateQueries({ queryKey: ["missions"] });
    },
    onError: (e) => setError(e.message),
  });
  const execute = useMutation({
    mutationFn: async () => {
      const rev = await api<Revision>(
        `/missions/${config!.id}/revisions`,
        config,
      );
      return api<Job>("/simulations", {
        revision_id: rev.id,
        expansion:
          expand &&
          config?.schema_version === 2 &&
          config.weather.provider === "NOAA_GFS"
            ? { max_tiles: tileLimit, max_download_mib: inputBudget }
            : null,
      });
    },
    onSuccess: (job) => {
      setError("");
      setPendingJob(job.id);
      setSampleIndex(0);
      setView("simulate");
      setTab("trajectory");
      refresh();
      void qc.invalidateQueries({ queryKey: ["missions"] });
    },
    onError: (e) => setError(e.message),
  });
  const cancel = useMutation({
    mutationFn: (id: string) => api<Job>(`/jobs/${id}/cancel`, {}),
    onSuccess: refresh,
    onError: (e) => setError(e.message),
  });

  function openRun(id: string) {
    setPendingJob(null);
    setSelectedId(id);
    setSampleIndex(0);
    setView("simulate");
    setTab("trajectory");
    const url = new URL(location.href);
    url.searchParams.set("simulation", id);
    history.replaceState(null, "", url);
  }
  function updateLaunch(
    key: keyof MissionConfig["launch"],
    value: number | string,
  ) {
    if (config)
      setDraft({ ...config, launch: { ...config.launch, [key]: value } });
  }
  function updateFlight(
    key: keyof MissionConfig["flight"],
    value: number | null,
  ) {
    if (config)
      setDraft({ ...config, flight: { ...config.flight, [key]: value } });
  }
  const synthetic = run?.weather_provider !== "NOAA_GFS";
  const pageTitle =
    view === "plan"
      ? "Mission configuration"
      : view === "overview"
        ? "Mission overview"
        : view === "analyze"
          ? "Simulation archive"
          : "Trajectory workspace";
  const currentError =
    error ||
    missions.error?.message ||
    revision.error?.message ||
    simulation.error?.message;

  async function importYaml(file: File) {
    if (file.size > 64 * 1024) {
      setError("Mission YAML exceeds 64 KiB limit");
      return;
    }
    try {
      const response = await fetch("/api/missions/import-yaml", {
        method: "POST",
        headers: { "Content-Type": "application/yaml" },
        body: await file.text(),
      });
      if (!response.ok)
        throw new Error(JSON.stringify((await response.json()).detail));
      setDraft(null);
      setError("");
      await qc.invalidateQueries({ queryKey: ["missions"] });
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="STRATOS home">
          <span className="brand-mark">
            <Orbit size={23} />
          </span>
          STRATOS<span className="brand-period">.</span>
        </a>
        <div className="workspace-label">
          MISSION ENGINEERING <span>01</span>
        </div>
        <div className="mission-switch">
          <span className="mission-icon">
            <Globe2 size={18} />
          </span>
          <span>
            Single launch program<small>Design & simulation</small>
          </span>
        </div>
        <nav aria-label="Main navigation">
          {navigation.slice(0, 3).map(({ id, name, icon: Icon }) => (
            <button
              key={id}
              aria-current={view === id ? "page" : undefined}
              className={view === id ? "active" : ""}
              onClick={() => setView(id)}
            >
              <Icon size={18} />
              {name}
              {view === id && <span className="nav-indicator" />}
            </button>
          ))}
          <div
            className="nav-deferred"
            title="Hardware bench testing belongs to Phase 5 and is not implemented"
          >
            <FlaskConical size={18} />
            <span>Test</span>
            <small>P5</small>
          </div>
          <div
            className="nav-deferred"
            title="Live reception belongs to Phase 7 and is not implemented"
          >
            <Radio size={18} />
            <span>Flight</span>
            <small>P7</small>
          </div>
          {navigation.slice(3).map(({ id, name, icon: Icon }) => (
            <button
              key={id}
              aria-current={view === id ? "page" : undefined}
              className={view === id ? "active" : ""}
              onClick={() => setView(id)}
            >
              <Icon size={18} />
              {name}
              {view === id && <span className="nav-indicator" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="eyebrow">CURRENT MILESTONE</span>
          <strong>Weather → trajectory</strong>
          <p>
            Foundation & L0 prediction.
            <br />
            No hardware assumptions.
          </p>
          <span className="phase-line">
            <i /> PHASE 0 — 1
          </span>
        </div>
        <div className="sidebar-footer">
          <span className="tiny-dot green" /> LOCAL WORKSPACE <span>v0.1</span>
          <small>Engineering evidence, not launch authority.</small>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Mission workspace <ChevronRight size={13} />
            <span>
              {view === "plan"
                ? "Plan"
                : view === "analyze"
                  ? "Analyze"
                  : view === "overview"
                    ? "Overview"
                    : "Simulate"}
            </span>
          </div>
          <div className="topbar-right">
            <span className="mode-pill">
              <span className="tiny-dot amber" />{" "}
              {run?.operating_mode ?? config?.operating_mode ?? "DEMO"} ·
              SIMULATED
            </span>
            <span className="local-label">
              <Database size={13} /> Local storage
            </span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                STRATOS /{" "}
                {config?.name?.split("/").pop()?.trim() ?? "DESIGN STUDY 01"}
              </div>
              <h1>
                {pageTitle}
                <span className="heading-dot" />
              </h1>
              <p>
                Trace the atmosphere. Inspect the assumptions. Keep the
                evidence.
              </p>
            </div>
            <div className="heading-actions">
              {run && (
                <a
                  className="button secondary"
                  href={`/api/simulations/${run.id}/export`}
                  download
                >
                  <ArrowDownToLine size={15} />
                  <span>Export run</span>
                </a>
              )}
              <button
                className="button primary"
                onClick={() => execute.mutate()}
                disabled={!config || execute.isPending}
                title="Save this mission revision and enqueue a new calculated trajectory"
              >
                <Play size={14} fill="currentColor" />
                {execute.isPending ? "Queuing…" : "Run simulation"}
              </button>
            </div>
          </div>

          {currentError && (
            <div className="notice error" role="alert">
              <ShieldAlert size={17} />
              <span>{currentError}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={15} />
              </button>
            </div>
          )}

          {health.data?.worker && health.data.worker.state !== "ready" && (
            <div className="notice error" role="alert">
              {health.data?.worker?.state === "restart_required"
                ? "Scientific code changed after worker startup. Restart the API/worker before calculating new results."
                : "The background worker heartbeat is unavailable. Calculations and downloads will remain queued until it restarts."}
            </div>
          )}
          {view === "simulate" && run && (
            <div className="saved-context">
              <span>
                Viewing saved prediction · {utc(run.created_utc)} ·{" "}
                {run.solver_version ?? "Legacy surface solver v1"}
              </span>
              <button
                className="text-button"
                onClick={() => {
                  setMissionId(run.manifest.config.id);
                  setDraft(structuredClone(run.manifest.config));
                  setView("plan");
                }}
              >
                Load these exact inputs
                <ArrowUpRight size={13} />
              </button>
            </div>
          )}
          {view === "simulate" && (
            <>
              <div
                className="workspace-tabs"
                role="tablist"
                aria-label="Simulation workspace"
              >
                <button
                  role="tab"
                  aria-selected={tab === "trajectory"}
                  className={tab === "trajectory" ? "selected" : ""}
                  onClick={() => setTab("trajectory")}
                >
                  <Route size={15} />
                  Trajectory
                </button>
                <button
                  role="tab"
                  aria-selected={tab === "weather"}
                  className={tab === "weather" ? "selected" : ""}
                  onClick={() => setTab("weather")}
                >
                  <Wind size={15} />
                  Weather inputs
                </button>
                <button
                  role="tab"
                  aria-selected={tab === "evidence"}
                  className={tab === "evidence" ? "selected" : ""}
                  onClick={() => setTab("evidence")}
                >
                  <FileJson size={15} />
                  Run evidence
                </button>
                <span className="tab-model">
                  MODEL <b>L0 / KINEMATIC</b>
                </span>
              </div>
              {tab === "weather" ? (
                <WeatherPanel datasets={datasets.data ?? []} onJob={refresh} />
              ) : tab === "evidence" ? (
                <Evidence run={run} />
              ) : (
                <>
                  <div className="metrics-row">
                    <Metric
                      label="PREDICTED DISTANCE"
                      value={run ? (run.distance_m / 1000).toFixed(1) : "—"}
                      unit="km"
                      note="Ground track · not air distance"
                      title="Modeled ground-track length. Schema 2 accumulates this on integration steps independently of saved-sample cadence; horizontal air distance is separate in the export."
                    />
                    <Metric
                      label="PRESCRIBED FLOAT"
                      value={
                        run
                          ? (
                              run.manifest.config.flight.target_geometric_m /
                              1000
                            ).toFixed(1)
                          : "—"
                      }
                      unit="km"
                      note="Geometric altitude · MSL"
                      title="Assumed target altitude, not validated buoyancy or a flight guarantee"
                    />
                    <Metric
                      label="PROFILE DURATION"
                      value={run ? duration(run.duration_s) : "—"}
                      note={`${samples.length} calculated samples`}
                      title="Total prescribed ascent, float and optional descent within valid weather volume"
                    />
                    <Metric
                      label="WIND SOURCE"
                      value={
                        run ? (synthetic ? "Synthetic" : "NOAA GFS") : "No run"
                      }
                      note={
                        synthetic
                          ? "Explicit demo · not measured"
                          : "Forecast · deterministic member"
                      }
                      title="Input provenance. NOAA forecasts remain model output, not measured weather"
                    />
                  </div>
                  <div className="notice caution compact">
                    <ShieldAlert size={16} />
                    <span>
                      <strong>Uncalibrated prediction.</strong> Prescribed
                      flight profile. No validated lift, reception, energy
                      margin, or launch approval.
                    </span>
                    <span className="notice-tag">L0</span>
                  </div>
                  <div className="trajectory-layout">
                    <div className="trajectory-main">
                      <div className="map-heading">
                        <div>
                          <span className="tiny-dot cyan" />
                          <strong>Predicted flight path</strong>
                          <span className="muted">
                            One deterministic scenario
                          </span>
                        </div>
                        <span className="map-offline">
                          <Globe2 size={13} /> OFFLINE BASEMAP
                        </span>
                      </div>
                      <TrajectoryMap
                        samples={samples}
                        index={index}
                        synthetic={synthetic && !!run}
                        onSelect={setSampleIndex}
                      />
                      {!run && (
                        <div className="empty-state">
                          {activeJobs.length
                            ? "The worker is calculating your first track. Progress appears below."
                            : "No saved trajectory. Run the offline demo or configure a downloaded NOAA dataset."}
                        </div>
                      )}
                      <AltitudeChart
                        samples={samples}
                        index={index}
                        onSelect={setSampleIndex}
                      />
                    </div>
                    <Inspector sample={samples[index]} simulation={run} />
                  </div>
                  <div className="run-footer">
                    <span>
                      <Check size={13} />
                      {run
                        ? "Saved locally · " + utc(run.created_utc)
                        : "No finalized prediction yet"}
                    </span>
                    <span className="mono">
                      {run
                        ? "SHA-256 " +
                          run.manifest.output_sha256.slice(0, 18) +
                          "…"
                        : "Awaiting calculation"}
                    </span>
                    <button onClick={() => setTab("evidence")}>
                      Inspect reproducibility <ArrowUpRight size={13} />
                    </button>
                  </div>
                </>
              )}
            </>
          )}

          {view === "plan" && config && (
            <section className="plan-layout">
              <form
                className="mission-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  save.mutate();
                }}
              >
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">VERSIONED MISSION</span>
                    <h2>Make each assumption explicit.</h2>
                    <p>
                      Saving creates an immutable revision. Earlier simulations
                      keep their original inputs.
                    </p>
                  </div>
                </div>
                <label className="field">
                  <span>Transport solver</span>
                  <select
                    aria-label="Transport solver"
                    value={config.schema_version}
                    onChange={(e) =>
                      setDraft({
                        ...config,
                        schema_version: Number(e.target.value) as 1 | 2,
                      })
                    }
                  >
                    <option value={2}>
                      WGS84 with altitude curvature · v2
                    </option>
                    <option value={1}>
                      Legacy reference surface · v1 (reproduction)
                    </option>
                  </select>
                  <small>
                    Solver selection is saved in the mission revision; older
                    results remain unchanged.
                  </small>
                </label>
                <label className="field">
                  <span>Mission name</span>
                  <input
                    value={config.name}
                    maxLength={100}
                    required
                    onChange={(e) =>
                      setDraft({ ...config, name: e.target.value })
                    }
                  />
                </label>
                <div className="form-section">
                  <span className="section-number">01</span>
                  <h3>Launch & initial state</h3>
                </div>
                <div className="form-grid">
                  <NumberField
                    label="Latitude · °N"
                    value={config.launch.latitude_deg}
                    min={-89.5}
                    max={89.5}
                    step="any"
                    onChange={(n) => updateLaunch("latitude_deg", n)}
                  />
                  <NumberField
                    label="Longitude · °E"
                    value={config.launch.longitude_deg}
                    min={-180}
                    max={180}
                    step="any"
                    onChange={(n) => updateLaunch("longitude_deg", n)}
                  />
                  <label className="field span-2">
                    <span>Start time · UTC</span>
                    <input
                      type="datetime-local"
                      required
                      value={config.launch.start_utc.slice(0, 16)}
                      onChange={(e) => {
                        if (e.target.value)
                          updateLaunch("start_utc", e.target.value + ":00Z");
                      }}
                    />
                    <small>
                      Must lie inside the selected weather volume. Display and
                      storage use UTC.
                    </small>
                    {Date.parse(config.launch.start_utc) < now && (
                      <small className="past-time-warning">
                        This example start is in the past. Choose a future time
                        for prospective planning; this does not validate
                        historical issued-at-time availability.
                      </small>
                    )}
                    <button
                      type="button"
                      className="text-button"
                      onClick={() =>
                        updateLaunch(
                          "start_utc",
                          new Date(
                            Math.ceil(Date.now() / 3600000) * 3600000,
                          ).toISOString(),
                        )
                      }
                    >
                      Use next full UTC hour
                    </button>
                  </label>
                  <NumberField
                    label="Ground elevation · m MSL"
                    step="any"
                    value={config.launch.ground_geometric_m}
                    min={-400}
                    max={6000}
                    onChange={(n) => updateLaunch("ground_geometric_m", n)}
                    hint="User assumption; no site survey or terrain model."
                  />
                  <NumberField
                    label="Initial altitude · m MSL"
                    step="any"
                    value={config.flight.initial_geometric_m}
                    min={-400}
                    max={20000}
                    onChange={(n) => updateFlight("initial_geometric_m", n)}
                    hint="Set to target altitude for an airborne float-only study."
                  />
                </div>
                <div className="form-section">
                  <span className="section-number">02</span>
                  <h3>Prescribed flight profile</h3>
                </div>
                <div className="form-grid">
                  <NumberField
                    label="Target altitude · m MSL"
                    step="any"
                    value={config.flight.target_geometric_m}
                    min={100}
                    max={20000}
                    onChange={(n) => updateFlight("target_geometric_m", n)}
                  />
                  <NumberField
                    label="Ascent rate · m/s"
                    value={config.flight.ascent_ms}
                    step="any"
                    min={0}
                    max={15}
                    onChange={(n) => updateFlight("ascent_ms", n)}
                  />
                  <NumberField
                    label="Float duration · h"
                    value={config.flight.float_duration_hours}
                    step="any"
                    min={0}
                    max={72}
                    onChange={(n) => updateFlight("float_duration_hours", n)}
                  />
                  <NumberField
                    label="Payload mass · g"
                    value={config.flight.payload_mass_g}
                    step="any"
                    min={0}
                    max={3000}
                    onChange={(n) => updateFlight("payload_mass_g", n)}
                    hint="Recorded only. Mass does not affect this L0 model."
                  />
                  <NumberField
                    label="Integration step · s"
                    value={config.flight.integration_step_s}
                    min={5}
                    max={120}
                    onChange={(n) => updateFlight("integration_step_s", n)}
                  />
                  <NumberField
                    label="Saved sample interval · s"
                    value={config.flight.sample_interval_s}
                    min={30}
                    max={300}
                    onChange={(n) => updateFlight("sample_interval_s", n)}
                  />
                </div>
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={config.flight.descent_ms !== null}
                    onChange={(e) =>
                      updateFlight("descent_ms", e.target.checked ? 3 : null)
                    }
                  />{" "}
                  Include prescribed descent to configured flat ground
                </label>
                {config.flight.descent_ms !== null && (
                  <NumberField
                    label="Descent rate · m/s"
                    value={config.flight.descent_ms}
                    step="any"
                    min={0}
                    max={30}
                    onChange={(n) => updateFlight("descent_ms", n)}
                  />
                )}
                <div className="form-section">
                  <span className="section-number">03</span>
                  <h3>Weather provenance</h3>
                </div>
                <label className="field">
                  <span>Wind field</span>
                  <select
                    value={config.weather.dataset_id ?? "synthetic"}
                    onChange={(e) => {
                      const dataset = datasets.data?.find(
                        (d) => d.id === e.target.value,
                      );
                      setDraft({
                        ...config,
                        weather: dataset
                          ? { provider: "NOAA_GFS", dataset_id: dataset.id }
                          : { provider: "SYNTHETIC", dataset_id: null },
                        launch: {
                          ...config.launch,
                          start_utc:
                            dataset?.valid_start_utc ?? config.launch.start_utc,
                        },
                      });
                    }}
                  >
                    <option value="synthetic">
                      SYNTHETIC — constant U 12 / V 3 m/s · demo
                    </option>
                    {datasets.data?.map((d) => (
                      <option value={d.id} key={d.id}>
                        NOAA GFS — {utc(d.run_utc)} · valid{" "}
                        {utc(d.valid_start_utc)} → {utc(d.valid_end_utc)} ·{" "}
                        {d.id.slice(-6)}
                      </option>
                    ))}
                  </select>
                  <small>
                    No cached NOAA forecast? Open Simulate → Weather inputs to
                    download one.
                  </small>
                </label>
                {config.weather.provider === "NOAA_GFS" &&
                  config.schema_version === 2 && (
                    <div className="expansion-controls">
                      <label className="check-field">
                        <input
                          type="checkbox"
                          checked={expand}
                          onChange={(e) => setExpand(e.target.checked)}
                        />
                        Automatically fetch adjacent weather crops
                      </label>
                      <p className="fine-print">
                        Explicit per-run option. Same GFS cycle only; overlap
                        must agree. Stops on quota, time, altitude or provider
                        failure. The budget counts all verified input bytes,
                        including cache reuse.
                      </p>
                      {expand && (
                        <div className="form-grid">
                          <NumberField
                            label="Maximum weather segments"
                            value={tileLimit}
                            min={1}
                            max={16}
                            onChange={setTileLimit}
                          />
                          <NumberField
                            label="Maximum input budget · MiB"
                            value={inputBudget}
                            min={1}
                            max={128}
                            onChange={setInputBudget}
                          />
                        </div>
                      )}
                    </div>
                  )}
                <div className="form-actions">
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => {
                      setDraft(null);
                      setError("");
                    }}
                  >
                    <RotateCcw size={14} />
                    Reset edits
                  </button>
                  <button
                    type="submit"
                    className="button primary"
                    disabled={save.isPending}
                  >
                    <Check size={15} />
                    {save.isPending
                      ? "Saving revision…"
                      : save.isSuccess && !draft
                        ? "Revision saved"
                        : "Save mission revision"}
                  </button>
                </div>
              </form>
              <aside className="plan-notes">
                <span className="eyebrow">ASSUMPTION REGISTER</span>
                <h2>Designed to be questioned.</h2>
                <div className="note-block">
                  <span>01 / Flight model</span>
                  <p>
                    Altitude is prescribed, not predicted from helium, mass,
                    drag, or thermal behavior.
                  </p>
                </div>
                <div className="note-block">
                  <span>02 / Mission mode</span>
                  <p>
                    DEMO is the simulation record mode. NOAA forecast
                    provenance, when selected, remains distinct from synthetic
                    inputs. No measured telemetry.
                  </p>
                </div>
                <div className="note-block">
                  <span>03 / Transmission</span>
                  <p>
                    Radio is disabled. Power, compatible receivers and recovered
                    data are not modeled in this phase.
                  </p>
                </div>
                <div className="note-block">
                  <span>04 / Reproducibility</span>
                  <p>
                    Every run pins this revision, weather file hashes, source
                    hashes and package versions.
                  </p>
                </div>
                <div className="yaml-actions">
                  <button
                    className="button secondary"
                    onClick={() => fileRef.current?.click()}
                  >
                    <ArrowUpRight size={14} />
                    Import mission YAML
                  </button>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".yaml,.yml"
                    hidden
                    onChange={(e) => {
                      if (e.target.files?.[0])
                        void importYaml(e.target.files[0]);
                      e.target.value = "";
                    }}
                  />
                  {revision.data && (
                    <a
                      className="button secondary"
                      href={`/api/revisions/${revision.data.id}/yaml`}
                      download
                    >
                      <ArrowDownToLine size={14} />
                      Export saved YAML
                    </a>
                  )}
                </div>
              </aside>
            </section>
          )}

          {view === "overview" && (
            <section className="overview">
              <div className="overview-lead">
                <span className="eyebrow">
                  ONE LAUNCH. TRACEABLE DECISIONS.
                </span>
                <h2>
                  Understand the path.
                  <br />
                  <span>Then challenge it.</span>
                </h2>
                <p>
                  This workspace currently tests atmospheric transport. A
                  calculated route is one piece of evidence, not a reason to
                  launch.
                </p>
                <button
                  className="button primary"
                  onClick={() => setView("plan")}
                >
                  Review mission assumptions
                  <ArrowRight size={15} />
                </button>
              </div>
              <div className="overview-evidence">
                <h3>Evidence available</h3>
                <div>
                  <Route size={20} />
                  <span>
                    <strong>{saved.data?.length ?? 0} saved predictions</strong>
                    <small>
                      Exact inputs, raw samples and reproducibility hashes
                    </small>
                  </span>
                </div>
                <div>
                  <Database size={20} />
                  <span>
                    <strong>
                      {datasets.data?.length ?? 0} NOAA datasets cached
                    </strong>
                    <small>
                      {datasets.data?.length
                        ? "Forecasts, not observations"
                        : "Real-data acceptance remains pending until a dataset is verified"}
                    </small>
                  </span>
                </div>
                <div>
                  <ShieldAlert size={20} />
                  <span>
                    <strong>Launch readiness unassessed</strong>
                    <small>
                      Hardware, energy, radio, recovery and permissions remain
                      open
                    </small>
                  </span>
                </div>
                <button
                  className="text-button"
                  onClick={() => {
                    setView("simulate");
                    setTab("weather");
                  }}
                >
                  Inspect weather inputs
                  <ArrowUpRight size={15} />
                </button>
              </div>
            </section>
          )}

          {view === "analyze" && (
            <section className="archive">
              <div className="section-heading">
                <div>
                  <span className="eyebrow">IMMUTABLE RESULTS</span>
                  <h2>Return to the evidence.</h2>
                  <p>
                    Open a saved prediction to inspect the original trajectory,
                    inputs, and manifest.
                  </p>
                </div>
                <span className="count-pill">
                  {totals.data?.simulations ?? saved.data?.length ?? 0} RUNS
                </span>
              </div>
              <div className="archive-head">
                <span>PREDICTION / SAVED UTC</span>
                <span>WEATHER</span>
                <span>DISTANCE</span>
                <span>DURATION</span>
                <span />
              </div>
              {(archive.data ?? saved.data)?.map((r) => (
                <button
                  className="archive-row"
                  key={r.id}
                  onClick={() => openRun(r.id)}
                >
                  <span>
                    <strong>{r.name}</strong>
                    <small>
                      {utc(r.created_utc)} · {r.id.slice(0, 8)}
                    </small>
                  </span>
                  <span
                    className={
                      r.weather_provider === "SYNTHETIC"
                        ? "source-demo"
                        : "source-real"
                    }
                  >
                    {r.weather_provider === "SYNTHETIC"
                      ? "DEMO / SYNTHETIC"
                      : "NOAA / FORECAST"}
                  </span>
                  <span>
                    {(r.distance_m / 1000).toFixed(1)} <small>km</small>
                  </span>
                  <span>{duration(r.duration_s)}</span>
                  <ArrowUpRight size={17} />
                </button>
              ))}
              <div className="archive-paging">
                <button
                  className="button secondary"
                  disabled={archivePage === 0}
                  onClick={() => setArchivePage(archivePage - 1)}
                >
                  Previous
                </button>
                <span>
                  Page {archivePage + 1} · {totals.data?.simulations ?? 0} saved
                  runs
                </span>
                <button
                  className="button secondary"
                  disabled={
                    (archivePage + 1) * 25 >= (totals.data?.simulations ?? 0)
                  }
                  onClick={() => setArchivePage(archivePage + 1)}
                >
                  Next
                </button>
              </div>
              <ComparisonPanel studies={archive.data ?? saved.data ?? []} />
              {!saved.data?.length && (
                <p className="empty-state">
                  No saved predictions. Run the offline demo to create your
                  first reproducible result.
                </p>
              )}
            </section>
          )}

          <section
            className="job-panel"
            aria-label="Background job status"
            aria-live="polite"
          >
            {activeJobs.length ? (
              activeJobs.map((job) => (
                <div className="job" key={job.id}>
                  <Clock3 size={15} />
                  <div>
                    <strong>
                      {job.kind === "weather"
                        ? "NOAA subset download"
                        : "Trajectory calculation"}{" "}
                      · {job.status}
                    </strong>
                    <span>{job.message}</span>
                    <progress value={job.progress} max={1} />
                  </div>
                  <span>{Math.round(job.progress * 100)}%</span>
                  <button
                    className="text-button"
                    onClick={() => cancel.mutate(job.id)}
                  >
                    <Square size={12} /> Cancel
                  </button>
                </div>
              ))
            ) : lastJob &&
              ["failed", "interrupted", "cancelled"].includes(
                lastJob.status,
              ) ? (
              <div
                className={`job ${lastJob.status === "failed" ? "job-failed" : ""}`}
              >
                <ShieldAlert size={16} />
                <div>
                  <strong>Last job {lastJob.status}</strong>
                  <span>{lastJob.message}</span>
                </div>
                <button
                  className="text-button"
                  onClick={() => retry.mutate(lastJob.id)}
                  disabled={retry.isPending}
                >
                  Retry original job
                </button>
                <button
                  className="text-button"
                  onClick={() => {
                    setView("simulate");
                    setTab("weather");
                  }}
                >
                  Inspect inputs
                  <ArrowUpRight size={14} />
                </button>
              </div>
            ) : (
              <div className="idle-status">
                <span className="tiny-dot green" />
                <span>Local job queue idle</span>
                <span>SQLite WAL · Results persist after refresh</span>
              </div>
            )}
          </section>
        </main>
        <footer className="app-footer">
          <span>STRATOS MISSION ENGINEERING</span>
          <span>Modeled ≠ measured. Evidence before confidence.</span>
          <span>LOCAL FIRST / OPEN TO INSPECTION</span>
        </footer>
      </div>
    </div>
  );
}

import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, Wind, ShieldAlert } from "lucide-react";
import { api, utc } from "./api";
import { NumberField } from "./Fields";
import { TrajectoryMap } from "./LazyMap";
import type { Dataset, WeatherInspection } from "./types";

const EMPTY_SAMPLES: [] = [];

export function WeatherExplorer({ datasets }: { datasets: Dataset[] }) {
  const [id, setId] = useState(datasets[0]?.id ?? "");
  const dataset = datasets.find((d) => d.id === id) ?? datasets[0];
  const [time, setTime] = useState(dataset?.valid_start_utc ?? "");
  const [altitude, setAltitude] = useState(12500);
  const [plane, setPlane] = useState<"geometric_altitude" | "isobaric">(
    "geometric_altitude",
  );
  const [pressure, setPressure] = useState(20000);
  const [variable, setVariable] = useState<"wind_speed" | "temperature">(
    "wind_speed",
  );
  const [gridSize, setGridSize] = useState<17 | 25 | 33>(25);
  const [lat, setLat] = useState(45.05);
  const [lon, setLon] = useState(9.7);
  const [result, setResult] = useState<WeatherInspection | null>(null);
  const sequence = useRef(0);
  const providers = useQuery({
    queryKey: ["weather-capabilities"],
    queryFn: () =>
      api<{ id: string; pressure_levels_pa?: number[] }[]>(
        "/providers/weather",
      ),
    staleTime: Infinity,
  });
  const levels = result?.available_pressure_levels_pa ??
    providers.data?.find((p) => p.id === "NOAA_GFS")?.pressure_levels_pa ?? [
      pressure,
    ];
  const inspect = useMutation({
    onSuccess: ({ data, ticket }) => {
      if (ticket === sequence.current) setResult(data);
    },
    mutationFn: async (point?: { lat: number; lon: number }) => {
      const ticket = ++sequence.current;
      const data = await api<WeatherInspection>("/weather/explore", {
        dataset_id: dataset.id,
        time_utc: time,
        latitude_deg: point?.lat ?? lat,
        longitude_deg: point?.lon ?? lon,
        geometric_msl_m: altitude,
        grid_size: 9,
        plane,
        pressure_pa: plane === "isobaric" ? pressure : null,
        contour_variable: variable,
        contour_grid_size: gridSize,
      });
      return { data, ticket };
    },
  });
  const range = useMemo<[number, number] | undefined>(
    () =>
      result?.scalar_field.minimum != null &&
      result.scalar_field.maximum != null
        ? [result.scalar_field.minimum, result.scalar_field.maximum]
        : undefined,
    [result],
  );
  const probe = useMemo<[number, number] | undefined>(
    () =>
      result
        ? [result.point.longitude_deg, result.point.latitude_deg]
        : undefined,
    [result],
  );
  const changed =
    result &&
    (result.request.dataset_id !== dataset.id ||
      result.request.plane !== plane ||
      new Date(result.request.time_utc).getTime() !==
        new Date(time).getTime() ||
      (plane === "isobaric"
        ? result.request.pressure_pa !== pressure
        : result.request.geometric_msl_m !== altitude) ||
      result.request.contour_variable !== variable ||
      result.request.contour_grid_size !== gridSize);
  function exportSlice() {
    if (!result) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(result, null, 2) + "\n"], {
        type: "application/json",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `stratos-weather-${result.inspection_sha256.slice(0, 12)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <section className="weather-explorer" aria-label="Cached forecast explorer">
      <div className="section-heading">
        <div>
          <span className="eyebrow">INSPECT THE ACTUAL INPUT</span>
          <h2>Weather volume explorer</h2>
          <p>
            Altitude or pressure surfaces, scalar contours and a vertical
            column. Cached forecast; no new download.
          </p>
        </div>
        <Wind size={24} />
      </div>
      <div className="form-grid">
        <label className="field span-2">
          <span>Cached forecast</span>
          <select
            aria-label="Explorer forecast"
            value={dataset.id}
            onChange={(e) => {
              ++sequence.current;
              setId(e.target.value);
              setTime(
                datasets.find((d) => d.id === e.target.value)!.valid_start_utc,
              );
              inspect.reset();
              setResult(null);
            }}
          >
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {utc(d.run_utc)} · valid {utc(d.valid_start_utc)} →{" "}
                {utc(d.valid_end_utc)} · {d.id.slice(-8)}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Valid time · UTC</span>
          <input
            aria-label="Explorer valid time · UTC"
            type="datetime-local"
            min={dataset.valid_start_utc.slice(0, 16)}
            max={dataset.valid_end_utc.slice(0, 16)}
            value={time.slice(0, 16)}
            onChange={(e) => {
              if (e.target.value) setTime(e.target.value + ":00Z");
            }}
          />
        </label>
        <label className="field">
          <span>Slice plane</span>
          <select
            aria-label="Weather slice plane"
            value={plane}
            onChange={(e) => setPlane(e.target.value as typeof plane)}
          >
            <option value="geometric_altitude">Geometric altitude · MSL</option>
            <option value="isobaric">Retained pressure surface</option>
          </select>
        </label>
        {plane === "geometric_altitude" ? (
          <NumberField
            label="Explorer altitude · m MSL"
            value={altitude}
            min={-400}
            max={20000}
            step={100}
            onChange={setAltitude}
          />
        ) : (
          <label className="field">
            <span>Pressure surface · hPa</span>
            <select
              aria-label="Explorer pressure surface · hPa"
              value={pressure}
              onChange={(e) => setPressure(Number(e.target.value))}
            >
              {levels.map((p) => (
                <option key={p} value={p}>
                  {p / 100} hPa · {p.toLocaleString()} Pa
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="field">
          <span>Contour variable</span>
          <select
            aria-label="Contour variable"
            value={variable}
            onChange={(e) => setVariable(e.target.value as typeof variable)}
          >
            <option value="wind_speed">Horizontal wind speed · m/s</option>
            <option value="temperature">Temperature · K</option>
          </select>
        </label>
      </div>
      <details className="weather-probe-settings">
        <summary>Probe coordinates & display resolution</summary>
        <div className="form-grid">
          <label className="field">
            <span>Display sample grid</span>
            <select
              aria-label="Contour display sample grid"
              value={gridSize}
              onChange={(e) =>
                setGridSize(Number(e.target.value) as typeof gridSize)
              }
            >
              {[17, 25, 33].map((size) => (
                <option key={size} value={size}>
                  {size} × {size} samples
                </option>
              ))}
            </select>
          </label>
          <NumberField
            label="Probe latitude · °N"
            value={lat}
            step={0.0001}
            min={-89.5}
            max={89.5}
            onChange={setLat}
          />
          <NumberField
            label="Probe longitude · °E"
            value={lon}
            step={0.0001}
            min={-180}
            max={180}
            onChange={setLon}
          />
        </div>
      </details>
      <div className="form-actions">
        <button
          className="button primary"
          onClick={() => inspect.mutate(undefined)}
          disabled={inspect.isPending}
        >
          {inspect.isPending
            ? "Sampling forecast slice…"
            : "Inspect cached forecast"}
        </button>
        {result && (
          <button className="button secondary" onClick={exportSlice}>
            <Download size={14} />
            Export inspected slice
          </button>
        )}
        <span className="muted">
          No extrapolation · at most two hourly files decoded
        </span>
      </div>
      {inspect.error && (
        <div className="notice error" role="alert">
          <ShieldAlert size={16} />
          {inspect.error.message}
          {result &&
            " — Last valid forecast view retained below; no new sample was accepted."}
        </div>
      )}
      {changed && (
        <p className="slice-pending" role="status">
          Inputs changed. The map below retains the last inspected slice until
          you apply these inputs.
        </p>
      )}
      {result && (
        <>
          <div className="notice neutral">
            <Wind size={16} />
            <span>
              <strong>FORECAST, NOT MEASURED.</strong> Cycle{" "}
              {utc(result.provenance.run_utc)} · valid{" "}
              {utc(result.point.time_utc)} ·{" "}
              {result.plane.kind === "isobaric"
                ? `${result.point.pressure_pa / 100} hPa surface · local height ${(result.point.geometric_msl_m / 1000).toFixed(2)}km MSL`
                : `${(result.point.geometric_msl_m / 1000).toFixed(2)}km geometric MSL`}
              . Lines point toward the dot; length represents ten minutes of
              wind advection. {result.unavailable_cells} invalid vector samples
              omitted.
            </span>
          </div>
          <div className="scalar-legend" aria-label="Forecast contour legend">
            <div>
              <strong>
                {result.scalar_field.variable === "wind_speed"
                  ? "Wind speed"
                  : "Temperature"}{" "}
                contours
              </strong>
              <span>
                {result.scalar_field.grid_size} ×{" "}
                {result.scalar_field.grid_size} display samples · native GFS{" "}
                {result.scalar_field.native_grid_deg}°
              </span>
            </div>
            <div className="scalar-scale">
              <div className="scalar-ramp" />
              <div>
                <span>
                  {result.scalar_field.minimum?.toFixed(1) ?? "—"}{" "}
                  {result.scalar_field.units}
                </span>
                <span>
                  {result.scalar_field.maximum?.toFixed(1) ?? "—"}{" "}
                  {result.scalar_field.units}
                </span>
              </div>
            </div>
            <span className="scalar-mask">
              Isolines:{" "}
              {result.scalar_field.levels.length
                ? result.scalar_field.levels
                    .map((v) =>
                      v.toLocaleString("en", { maximumSignificantDigits: 5 }),
                    )
                    .join(" · ") +
                  " " +
                  result.scalar_field.units
                : "none"}
            </span>
            <span className="scalar-mask">
              {result.scalar_field.masked_cells} masked grid cells · no contour
              across missing data
              {result.scalar_field.status === "flat" &&
                " · constant field: no isolines"}
              {result.scalar_field.status === "unavailable" &&
                " · no valid scalar field"}
            </span>
          </div>
          <TrajectoryMap
            samples={EMPTY_SAMPLES}
            index={0}
            synthetic={false}
            onSelect={() => {}}
            windVectors={result.wind_vectors}
            windTips={result.wind_tips}
            contours={result.contours}
            contourRange={range}
            probePoint={probe}
            weatherBounds={result.bounds}
            onLocationSelect={(y, x) => {
              setLat(Number(y.toFixed(4)));
              setLon(Number(x.toFixed(4)));
              inspect.mutate({ lat: y, lon: x });
            }}
          />
          <div className="probe-readout" aria-label="Selected forecast sample">
            <span>
              <small>LOCAL GEOMETRIC HEIGHT</small>
              <strong>{result.point.geometric_msl_m.toFixed(0)} m MSL</strong>
            </span>
            <span>
              <small>PRESSURE</small>
              <strong>{(result.point.pressure_pa / 100).toFixed(1)} hPa</strong>
            </span>
            <span>
              <small>U / V WIND</small>
              <strong>
                {result.point.u_ms.toFixed(2)} / {result.point.v_ms.toFixed(2)}{" "}
                m/s
              </strong>
            </span>
            <span>
              <small>TEMPERATURE</small>
              <strong>{result.point.temperature_k.toFixed(2)} K</strong>
            </span>
          </div>
          <div className="profile-heading">
            <h3>
              Vertical profile at {result.point.latitude_deg.toFixed(4)}°,{" "}
              {result.point.longitude_deg.toFixed(4)}°
            </h3>
            <span>Click the map to probe a different column.</span>
          </div>
          <div
            className="profile-table"
            role="region"
            aria-label="Forecast pressure-level profile"
            tabIndex={0}
          >
            <table>
              <thead>
                <tr>
                  <th scope="col">Geometric MSL · m</th>
                  <th scope="col">Pressure · Pa</th>
                  <th scope="col">U / V · m/s</th>
                  <th scope="col">Wind speed · m/s</th>
                  <th scope="col">Temperature · K</th>
                </tr>
              </thead>
              <tbody>
                {result.profile.map((p) => (
                  <tr
                    key={p.pressure_pa}
                    data-selected={
                      Math.abs(p.pressure_pa - result.point.pressure_pa) < 0.05
                    }
                  >
                    <td>{p.geometric_msl_m.toFixed(0)}</td>
                    <td>{p.pressure_pa.toFixed(0)}</td>
                    <td>
                      {p.u_ms.toFixed(2)} / {p.v_ms.toFixed(2)}
                    </td>
                    <td>{p.speed_ms.toFixed(2)}</td>
                    <td>{p.temperature_k.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="fine-print">
            Source bracket: {utc(result.point.valid_before_utc)} →{" "}
            {utc(result.point.valid_after_utc)}. Pressure surfaces have varying
            model heights. Display contours interpolate sampled forecast values
            and add no model resolution. Coarse model terrain can invalidate a
            low-altitude/low-level probe.
          </p>
          <p className="fine-print slice-hash">
            Inspected slice SHA-256 <code>{result.inspection_sha256}</code>
          </p>
        </>
      )}
    </section>
  );
}

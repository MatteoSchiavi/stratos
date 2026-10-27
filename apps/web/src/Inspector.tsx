import { useNow } from "./useNow";
import { MapPin, ShieldAlert } from "lucide-react";
import { utc } from "./api";
import type { Sample, Simulation } from "./types";
export function Inspector({
  sample,
  simulation,
}: {
  sample: Sample | undefined;
  simulation: Simulation | undefined;
}) {
  const now = useNow();
  return (
    <aside className="inspector">
      <div className="inspector-title">
        <span className="eyebrow">SAMPLE INSPECTOR</span>
        <span className="tiny-dot cyan" />
      </div>
      {sample ? (
        <>
          <div className="sample-phase">
            <span>{sample.phase.replaceAll("_", " ")}</span>
            <span>MODELED</span>
          </div>
          <div
            className="inspector-altitude"
            title="Prescribed geometric altitude above mean sea level; not a measured height"
          >
            {(sample.geometric_msl_m / 1000).toFixed(2)}
            <small>km MSL</small>
          </div>
          <p className="inspector-caption">
            Prescribed altitude · uncalibrated
          </p>
          <div className="coordinates">
            <MapPin size={15} />
            <span>
              {sample.latitude_deg.toFixed(4)}° N<br />
              {sample.longitude_deg.toFixed(4)}° E
            </span>
          </div>
          <dl className="sample-values">
            <div title="Horizontal speed computed from sampled U/V; not observed GNSS speed">
              <dt>Horizontal wind</dt>
              <dd>
                {sample.speed_ms.toFixed(1)} <small>m/s</small>
              </dd>
            </div>
            <div title="Eastward / northward interpolated wind components">
              <dt>U / V</dt>
              <dd>
                {sample.u_ms.toFixed(1)} / {sample.v_ms.toFixed(1)}{" "}
                <small>m/s</small>
              </dd>
            </div>
            <div title="Interpolated ambient model temperature, displayed in kelvin">
              <dt>Temperature</dt>
              <dd>
                {sample.temperature_k.toFixed(1)} <small>K</small>
              </dd>
            </div>
            <div title="Logarithmic pressure interpolation between height surfaces; SI pascals">
              <dt>Pressure</dt>
              <dd>
                {Math.round(sample.pressure_pa).toLocaleString()}{" "}
                <small>Pa</small>
              </dd>
            </div>
            <div title="Geopotential height from geometric altitude using standard reference radius">
              <dt>Geopotential height</dt>
              <dd>
                {sample.geopotential_m.toFixed(0)} <small>gpm</small>
              </dd>
            </div>
            <div title="Prescribed vertical profile">
              <dt>Vertical speed</dt>
              <dd>
                {sample.vertical_ms.toFixed(1)} <small>m/s</small>
              </dd>
            </div>
          </dl>
          <div className="source-card">
            <span className="eyebrow">WEATHER PROVENANCE</span>
            <strong>
              {simulation?.weather_provider === "SYNTHETIC"
                ? "Synthetic constant wind"
                : "NOAA GFS · 0.25°"}
            </strong>
            <span>
              {simulation?.manifest.weather.run_utc
                ? `Cycle ${utc(simulation.manifest.weather.run_utc)}`
                : "Analytic fixture · not observations"}
            </span>
            {simulation?.manifest.weather.run_utc && (
              <span>
                Cycle age:{" "}
                {Math.max(
                  0,
                  (now - Date.parse(simulation.manifest.weather.run_utc)) /
                    3600000,
                ).toFixed(1)}{" "}
                h · forecast, not measured
              </span>
            )}
            {sample.weather_dataset_id && (
              <span>Crop {sample.weather_dataset_id.slice(-12)}</span>
            )}
            <span>
              Bracket {utc(sample.weather_before_utc)}
              <br />→ {utc(sample.weather_after_utc)}
            </span>
          </div>
          <div className="inspector-note">
            <ShieldAlert size={15} />
            <p>
              One deterministic scenario. No validated confidence corridor or
              flight-readiness claim.
            </p>
          </div>
        </>
      ) : (
        <div className="empty-state">
          Run a simulation to inspect calculated weather and trajectory samples.
        </div>
      )}
    </aside>
  );
}

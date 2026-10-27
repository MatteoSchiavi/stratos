import { useId } from "react";
export function NumberField({
  label,
  value,
  onChange,
  step = 1,
  hint,
  min,
  max,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  step?: number | "any";
  hint?: string;
  min?: number;
  max?: number;
}) {
  const hintId = useId();
  return (
    <label className="field">
      <span>{label}</span>
      <input
        aria-label={label}
        aria-describedby={hint ? hintId : undefined}
        type="number"
        required
        step={step}
        min={min}
        max={max}
        value={Number.isFinite(value) ? value : ""}
        onChange={(e) => onChange(e.target.valueAsNumber)}
        title={hint}
      />
      {hint && <small id={hintId}>{hint}</small>}
    </label>
  );
}
export function Metric({
  label,
  value,
  unit,
  note,
  title,
}: {
  label: string;
  value: string;
  unit?: string;
  note: string;
  title: string;
}) {
  return (
    <div className="metric" title={title}>
      <span className="eyebrow">{label}</span>
      <div className="metric-value">
        {value}
        <small>{unit}</small>
      </div>
      <span className="metric-note">{note}</span>
    </div>
  );
}

export type MissionConfig = {
  schema_version: 1 | 2;
  id: string;
  name: string;
  operating_mode: "DEMO" | "HISTORICAL_REPLAY" | "HARDWARE_TEST" | "LIVE";
  origin: "assumed" | "demo";
  calibration_status: "uncalibrated";
  launch: {
    latitude_deg: number;
    longitude_deg: number;
    ground_geometric_m: number;
    start_utc: string;
  };
  flight: {
    model: "L0_prescribed";
    initial_geometric_m: number;
    target_geometric_m: number;
    ascent_ms: number;
    float_duration_hours: number;
    descent_ms: number | null;
    payload_mass_g: number;
    integration_step_s: number;
    sample_interval_s: number;
  };
  weather: { provider: "SYNTHETIC" | "NOAA_GFS"; dataset_id: string | null };
  radio: { enabled: false };
};
export type Mission = {
  id: string;
  name: string;
  latest_revision_id: string;
  operating_mode: string;
};
export type Revision = {
  id: string;
  config_sha256: string;
  config: MissionConfig;
};
export type Job = {
  id: string;
  kind: string;
  status: string;
  progress: number;
  message: string;
  result_id: string | null;
};
export type Sample = {
  time_utc: string;
  elapsed_s: number;
  latitude_deg: number;
  longitude_deg: number;
  geometric_msl_m: number;
  geopotential_m: number;
  vertical_ms: number;
  phase: string;
  u_ms: number;
  v_ms: number;
  speed_ms: number;
  temperature_k: number;
  pressure_pa: number;
  distance_m: number;
  weather_before_utc: string;
  weather_after_utc: string;
  weather_time_weight: number;
  weather_dataset_id?: string | null;
};
export type SimulationSummary = {
  id: string;
  name: string;
  created_utc: string;
  weather_provider: string;
  revision_id: string;
  distance_m: number;
  duration_s: number;
  model: string;
  quality: string;
  operating_mode: string;
  solver_version?: string | null;
  horizontal_air_distance_m?: number | null;
};
export type Simulation = SimulationSummary & {
  samples: Sample[];
  limitations: string[];
  manifest: {
    sha256: string;
    config_sha256: string;
    output_sha256: string;
    config: MissionConfig;
    weather: {
      provider: string;
      run_utc?: string;
      retrieved_utc?: string;
      source_uri?: string;
      files?: { sha256: string; source_uri: string }[];
    };
    code: {
      git_commit: string | null;
      source_tree_sha256: string;
      packages: Record<string, string>;
    };
  };
};
export type Dataset = {
  id: string;
  run_utc: string;
  valid_start_utc: string;
  valid_end_utc: string;
  retrieved_utc: string;
  sha256: string;
  files: { size_bytes: number }[];
};
export type WeatherRun = {
  run_utc: string;
  published_leads_hours: number[];
  age_hours: number;
  source_uri: string;
};
export type DownloadInput = {
  run_utc: string;
  first_lead_hour: number;
  last_lead_hour: number;
  west_deg: number;
  east_deg: number;
  south_deg: number;
  north_deg: number;
};
export type Estimate = {
  files: number;
  estimated_bytes: number;
  minimum_filter_wait_seconds: number;
  unpacked_array_bytes: number;
  cache_limit_bytes: number;
  memory_limit_bytes: number;
};

export type WeatherInspection = {
  point: {
    latitude_deg: number;
    longitude_deg: number;
    geometric_msl_m: number;
    time_utc: string;
    u_ms: number;
    v_ms: number;
    temperature_k: number;
    pressure_pa: number;
    valid_before_utc: string;
    valid_after_utc: string;
  };
  profile: {
    pressure_pa: number;
    geometric_msl_m: number;
    u_ms: number;
    v_ms: number;
    speed_ms: number;
    temperature_k: number;
  }[];
  request: {
    dataset_id: string;
    time_utc: string;
    plane: "geometric_altitude" | "isobaric";
    pressure_pa: number | null;
    geometric_msl_m: number;
    contour_variable: "wind_speed" | "temperature";
    contour_grid_size: 17 | 25 | 33;
  };
  plane: {
    kind: "geometric_altitude" | "isobaric";
    pressure_pa: number | null;
    geometric_msl_m: number | null;
  };
  available_pressure_levels_pa: number[];
  wind_vectors: import("geojson").FeatureCollection<ContourGeometry>;
  wind_tips: import("geojson").FeatureCollection<import("geojson").Point>;
  contours: import("geojson").FeatureCollection<ContourGeometry>;
  scalar_field: {
    variable: "wind_speed" | "temperature";
    units: string;
    minimum: number | null;
    maximum: number | null;
    grid_size: number;
    invalid_nodes: number;
    masked_cells: number;
    valid_cells: number;
    levels: number[];
    status: "available" | "flat" | "unavailable";
    native_grid_deg: number | null;
  };
  provenance: { id: string; run_utc: string; grid_deg: number; sha256: string };
  inspection_sha256: string;
  bounds: [number, number, number, number];
  unavailable_cells: number;
  quality: string;
};

export type ContourGeometry =
  import("geojson").LineString | import("geojson").MultiLineString;

export type ComparisonPosition = {
  latitude_deg: number;
  longitude_deg: number;
  geometric_msl_m: number;
  elapsed_s: number;
  time_utc: string;
};
export type StudyComparison = {
  comparison_sha256: string;
  alignment: "elapsed" | "utc";
  alignment_description: string;
  duration_s: number;
  sample_count: number;
  request: {
    reference_id: string;
    candidate_id: string;
    alignment: "elapsed" | "utc";
    sample_count: number;
  };
  sources: {
    id: string;
    name: string;
    weather_provider: string;
    solver_version: string;
    weather_run_utc: string | null;
    forecast_dataset_id: string | null;
    output_sha256: string;
    saved_sample_count: number;
  }[];
  metrics: {
    maximum_sampled_separation_m: number;
    mean_sampled_separation_m: number;
    shared_window_end_separation_m: number;
    maximum_absolute_sampled_height_difference_m: number;
    maximum_separation_sample_index: number;
  };
  points: {
    comparison_elapsed_s: number;
    reference: ComparisonPosition;
    candidate: ComparisonPosition;
    horizontal_separation_m: number;
    height_difference_m: number;
  }[];
  configuration_differences: {
    field: string;
    reference: unknown;
    candidate: unknown;
  }[];
};

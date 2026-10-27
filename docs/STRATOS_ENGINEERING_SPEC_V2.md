# STRATOS — Mission Engineering Platform
## Implementation specification v2.0 — 27 October 2026

**Audience:** Codex / software engineering agent. **Language:** English (code, interfaces and documentation); UI may offer Italian later. **Status:** engineering specification, not an authorization to launch. **Mission:** ONE affordable, long-duration, solar-powered atmospheric pico-balloon, potentially with a downward-facing camera. **Primary measure of software value:** better decisions and validated telemetry delivery, not dashboard beauty.

> IMPLEMENTATION INSTRUCTION: Inspect any supplied existing repository, preserve functioning code, and report what already exists. Build working software incrementally. Do not claim models, APIs, hardware, radios or forecasts are validated until real tests substantiate them. If an external dependency is temporarily inaccessible, preserve a real adapter plus a clearly named fixture; NEVER quietly substitute fake output. Do not implement all features in one shot: complete, run, test and document one vertical slice at a time. No paid cloud or AI API may be required.

## 0. Executive architecture decisions (hard constraints)

1. **Mission lifecycle:** Concept -> Design -> Desktop simulation -> Bench validation -> Readiness review -> Authorized launch -> Live operation -> Post-flight science -> Public release. One versioned mission record spans the entire lifecycle.
2. **Four operating modes:** `DEMO` (explicit synthetic scenarios), `HISTORICAL_REPLAY` (time-frozen historical forecast and observations), `HARDWARE_TEST` (actual bench instruments), `LIVE` (actual received packets). Persistent display of mode and freshness. Never mix demo and real telemetry in a flight record.
3. **Flight model fidelity:** Three explicitly different models: A. kinematic fixed-altitude/ascent-profile predictor (build first); B. approximate buoyancy/drag float simulator (research model); C. calibrated probabilistic model (ONLY after envelope and flight data). Each exposes limitations. Accuracy of weeks-long balloon paths cannot be guaranteed by an initial weather forecast.
4. **Communications fidelity:** Four different states: `geometrically_visible`, `RF_margin_sufficient`, `compatible_receiver_present`, `observed_decode_success`. A gateway coordinate can establish only a potential contact. It NEVER proves an actual link. Model predicted contacts and packet delivery separately. TTN public Fair Use is distinct from legal duty-cycle limitations. No worldwide band compatibility assumed.
5. **Weather provenance:** Operational forecasts use exact model run (initialization, valid time, member, grid, parameters). ERA5 can score past estimates, but must NEVER be introduced as a historical operational forecast. Avoid look-ahead bias. Missing forecast lead times are missing, not silently extrapolated.
6. **Power model:** Hardware-supervised cold start, threshold hysteresis, finite energy, cold derating, transient energy and load shedding. Firmware may not rely on itself to avoid an under-voltage reboot loop.
7. **Computer use:** Local-first; works on Windows development laptop and modest Linux self-hosting. CPU and RAM budget are explicit. Favor incremental weather subsetting and a tiny database over big-data infrastructure.
8. **Hardware-neutral software:** Flight core likely STM32WL/RAK3172; camera perhaps SPI OV2640 or switched ESP32-S3 copro. Do not couple mission logic or storage schema to either chip. The eventual hardware architecture is an unresolved trade study.
9. **Regulatory design:** Track approvals with issuer, scope, expiry and supporting documents. GNSS geofencing can enforce configured permission, never create permission. Unknown/stale fixes or unknown radio jurisdictions default to radio-off (logging continues) for flight-like test profiles.
10. **No false authority:** Readiness checks indicate engineering evidence and unresolved hazards; they cannot legally certify airworthiness or flight authorization.
11. **Single-flight focus:** Avoid fleet controls, microservices and social media dashboards in MVP. A recoverable record or image matters more than generating a large unrecoverable backlog.

## 1. Outcome definition and go/no-go criteria

The system should answer quantitatively, with traceable assumptions:
- For a candidate launch point/time/payload, what plausible paths and float altitudes occur, within the forecast's *actual* horizon?
- Which *verified compatible* receivers might hear our radio, at which simulated times, and how much valid data could arrive?
- Does the simulated harvest/storage support GNSS, weather sampling, imaging and transmissions? What happens under worst-case shadowing and cold start?
- Which single parameter (payload mass, panel tilt, capacitor, SF, sampling interval, image quality, radio policy, launch time) most improves **unique scientifically useful bytes received** per € and per gram?
- If everything goes wrong (unplanned descent, bad GPS, cloudy day, weeks offline, corrupted packet), can the instrument continue safely and preserve earlier valid records?
- What authorization and bench-test evidence remains missing?

**Flight-readiness gate examples** (initial proposed test gates, editable and not regulatory endorsements): no software-reproducible brownout loop in 1000 scripted start/stop cycles; journal recovers all previously committed records after injected power loss; telemetry decoder survives packet corruption; radio duty-cycle accounting passes independent reference vectors; cold-test observations are within qualified component range or explicitly risk-accepted by human reviewer; a complete small test image is captured, archived, packetized and reconstructed; local receiver detects real repeated packets in field tests; applicable launch/radio approvals attached.

## 2. Delivery phases (must be implemented in this order)

**P0: foundation (1 vertical slice).** Monorepo, typed configs, DB migration, reproducibility manifest, fixtures, UI shell, API, task queue, test CI. A `DEMO` mission must load entirely offline.

**P1: true weather and trajectory.** NOAA GFS adapter, partial GRIB downloader/cache, pressure-level interpolation, kinematic winds at a specified altitude, maps, chart, saved prediction, manifest. Include synthetic constant-wind reference test and actual recent downloaded cycle. This is the first shippable useful app.

**P2: replay and forecast verification.** Forecast issued-at-time rule, archive adapter or provided historical GRIB test set, observed balloon track import, error metrics and uncertainty caveats. Strict train/test split by time and flight ID. Add GEFS when proven working.

**P3: connectivity and recovered-data budget.** Packet Broker Mapper adapter (gateway freshness, band, indoor/outdoor); LoRa airtime; terrain/horizon and RF link budget; schedule, missing receivers, deduplication, TTN constraints; onboard log/backlog/image packet reconstruction. Report contact opportunities as ranges, not invented coverage probabilities.

**P4: sun/energy/float coupling.** Solar vector geometry, panel attitudes, basic irradiance scenarios, capacitor and harvester state machine, energy loads with measurable parameters, nominal balloon ascent/float and failure. Scenario sweeps, rankings with uncertainty and feasibility.

**P5: Virtual Flight Computer / hardware testing.** Portable shared C firmware state machines or a formal spec with cross-language golden vectors, instrument import, failure injection, serial receiver, SWD build and optional HIL.

**P6: imaging, launch optimization, readiness.** JPEG/SSDV-inspired packet lab, photo-coverage timing with IMU constraints, selectable launch-window scoring, versioned approvals, documentary launch checklists, risk register.

**P7: live mission operations and post-flight analysis.** Raw packet ingestion, parsing, live map, alerts, contact observations, image mosaics, descent recovery, data export and public read-only flight story. Actual images only if acquired.

For each phase: run the implementation, add deterministic tests, publish screenshots, save real input/output samples, document what remains unimplemented in `PROJECT_STATUS.md`. Avoid placeholder UI controls. Stop and correct basic accuracy issues before adding next modules.

## 3. Stack and repository structure

**Backend:** Python 3.12+ compatible, FastAPI, Pydantic v2, NumPy/SciPy, xarray, cfgrib/ecCodes, pyproj/GeographicLib, shapely, SQLite WAL via SQLAlchemy/Alembic, filesystem/Zarr/GRIB cache, optional Polars/Pandas. Simple durable worker/job state (process-based with SQLite records) before adopting Redis/Celery. Background operations must be cancellable/resumable when possible. Avoid downloading global datasets unnecessarily.

**Frontend:** React + TypeScript + Vite, MapLibre GL JS + deck.gl only where helpful, lightweight charting (e.g. ECharts/uPlot), TanStack Query. Optional lazy-loaded Cesium for 3D; the 2D map must remain functional. Styling: CSS design tokens and accessible components; no requirement for paid UI libraries. Local map style/tile-provider terms disclosed. Time displayed in UTC with optional local conversion.

**Firmware:** portable C11/C++17 domain logic, CMake native test harness, ARM cross build after actual board chosen; HAL for GNSS, flash, radio, harvester signals, sensor bus, camera. STM32Cube IDE/toolchain may be used but no premature hardware dependency.

**Suggested repo:**
```
stratos/
  apps/web/                  # front end
  services/api/              # HTTP, models, migrations, telemetry
  packages/domain/           # schemas, shared Python domain
  packages/meteo/            # forecasts, GRIB/cache/interpolation
  packages/flight/           # physics + trajectory
  packages/energy/           # solar + hardware power states
  packages/radio/            # nodes, propagation, contact, airtime
  packages/transport/        # packet queues, flash, delivery
  packages/imaging/          # JPEG/fragmentation/footprints
  packages/replay/           # frozen-time backtesting
  firmware/core/             # portable C state machine
  firmware/hal/              # interfaces; no board commitments
  firmware/simulator/        # native executable + JSON protocol
  tests/fixtures/            # synthetic + permitted real samples
  data/cache/                # gitignored external files
  docs/                      # ADRs, model limitations, sources
  scripts/                   # test commands and import helpers
  docker-compose.yml
  .env.example
  README.md
  PROJECT_STATUS.md
```

**Resource targets:** ordinary UI responsive while simulations run; optional 8GB RAM Linux deployment; capped cache size and disk usage; initial 48-72-hour cropped GFS forecast downloads; dynamic segment fetching for trajectories leaving initial bounding box; limits on ensemble scenarios; show estimated download MB and disk before starting. Large global 16-day runs are advanced mode, not P1 default.

## 4. Domain schemas, units, data integrity

Define versioned Pydantic/TypeScript schema exchange. Primary entities: `Mission`, `MissionRevision`, `PayloadComponent`, `EnvironmentSource`, `ForecastRun`, `WeatherGrid`, `Scenario`, `SimulationRun`, `TrajectorySample`, `EnergySample`, `Receiver`, `RFProfile`, `ContactWindow`, `Transmission`, `RawPacket`, `DecodedObservation`, `FlashRecord`, `Image`, `ImageFragment`, `PermissionProfile`, `TestEvidence`, `Risk`, `ReadinessCheck`, `FlightEvent`.

Mandatory common fields: stable UUID, schema version, created UTC, origin (`measured|forecast|assumed|manufacturer|derived|demo`), source URI or identifier, configuration revision hash, units, validity time, and calibration status where relevant. Preserve raw bytes of actual packets. All analysis runs pin a SHA-256 manifest of configs, file hashes, model run timestamps, package versions, code commit and deterministic RNG seeds. Imported files have source and licence metadata. No implicit unit conversions.

Conventions: UTC internally; geodetic WGS84 lat/lon; identify altitude explicitly (`ellipsoidal_m`, `geometric_msl_m`, `geopotential_m`), pressure Pa, temperature K internally, energy J, power W, RF frequency Hz, gain dBi and dB loss, SNR dB, RSSI dBm, data MiB versus MB, timestamp integer or ISO-8601 UTC. Document atmospheric conversion assumptions and do not equate a pressure level with an exact altitude.

Create at least one `mission.yaml` editable and round-trip schema. Example (illustrative assumptions ONLY):
```yaml
schema_version: 1
mission:
  id: "stratos-ground-demo"
  operating_mode: "DEMO"
launch:
  latitude_deg: 45.05
  longitude_deg: 9.70
  ground_geometric_m: 80
  start_utc: "2026-11-05T12:00:00Z"
balloon:
  model: "prescribed_float_unvalidated"
  payload_mass_g: 23
  ascent_ms: 1.5
  target_geometric_m: 12500
  float_duration_hours: 72
weather:
  provider: "NOAA_GFS"
  run_utc: null   # pinned only after download
radio:
  profile_id: "simulation-only-eu868"
  enabled: false  # no automatic legal authorization
energy:
  storage_type: "supercapacitor"
  capacitance_f: 1.0
  wake_voltage_v: 4.4
  sleep_voltage_v: 3.5
  values_provenance: "illustrative_not_validated"
```

The UI must warn when assumptions are synthetic or inconsistent (e.g. energy storage min voltage below supported load; missing supported temperature range; weight inconsistent with gas lift).

## 5. Meteorological engine (P1/P2)

### Reliable data sources
- Primary: [NOAA GFS on NOMADS](https://www.nco.ncep.noaa.gov/pmb/products/gfs/nomads/) with GRIB filter for selected fields, pressure levels and geographic extents. Explicit 00/06/12/18 UTC cycle; supported forecasts extend to 384 h in products where documented. Use only published leads and respect download limits.
- Ensemble: [NOAA GEFS](https://nomads.ncep.noaa.gov/) from documented cycles and members, enabling actual weather spread rather than made-up Gaussian confidence bands.
- Verification: [Copernicus CDS ERA5](https://cds.climate.copernicus.eu/) reanalysis for scoring past observed trajectories, never for time-frozen operational forecast.
- Optional: [Tawhiri](https://github.com/cuspaceflight/tawhiri) predictor reference/test oracle, with clear licence review; [Open-Meteo](https://open-meteo.com/en/docs) as convenient provisional adapter only under correct non-commercial/licensing conditions.

### Data flow
1. Provider-agnostic interface: `list_available_runs()`, `estimate_download()`, `fetch_subset(request)`, `open_cached()`, `get_state(lat,lon,geometric_alt,time,member)`, `data_provenance()`.
2. Download with retry/backoff, cancellation, checksum, fail-on-HTML/404; no silent newest-cycle substitution if selected run unavailable. For current operations, explicitly show cycle age and valid horizon.
3. Cache GRIB metadata per run/member/variable/pressure-level, size and geographic ROI. Move ROI as trajectories leave initial tile; no automatic multi-gigabyte files for basic runs.
4. Interpolate spatially (handle dateline and polar grid), between pressure levels (prefer log-pressure for thermodynamic vertical interpolation as appropriate), and temporally. Convert geopotential/geometric height correctly; check model's source units and coordinate directions.
5. Reject/expose missing pressure levels, below-terrain states, outside-run timing, invalid grids; optional explicit bounded extrapolation ONLY in separate sensitivity experiment.
6. Efficient multidimensional array integration: chunked/lazy xarray; avoid reading entire global file repeatedly per particle. Track memory use and warnings.
7. 3D weather explorer: selectable altitude/pressure layer, UTC time, U/V wind arrows, speed contours, vertical atmospheric profile at cursor; model issue time/valid time prominently visible.

### Validation
- Synthetic constant wind and vertical gradient arrays with known analytic interpolations.
- Comparison of sampled winds against independent GRIB point extraction for chosen real samples.
- Dateline and wrap-around, high latitudes, missing/NaN cells, pressure-to-height conversion, below ground.
- Frozen-forecast test rejects the use of datasets issued after simulated launch time.
- Frontend never labels ERA5 as a prospective forecast.

## 6. Flight physics and trajectory engine (P1/P4)

### Levels of fidelity
- **L0 kinematic:** prescribed ascent m/s, float altitude / duration, optional descent rate; advection with gridded U,V. Implement first and label it clearly. [Tawhiri float profile](https://github.com/cuspaceflight/tawhiri/blob/master/docs/api.rst) is a precedent but does not model multiweek envelope behavior.
- **L1 approximate physical:** dry/moist-air density, helium partial density, buoyancy, gas thermal assumptions, envelope max volume, drag coefficient and projected area, envelope mass, suspension/payload masses, drag descent; numerical integration with event detection (`float`,`burst`,`ground`,`thermal or pressure threshold`). Explicit unknown envelope leakage and strain.
- **L2 calibrated:** introduce measured gas leak, envelope deformation, diurnal lift, sun/IR gas temperature differential, drag and failure distributions only after lab experiments or defensible independent flight references. L2 is research, not P1.

### Numerics
Use SI. Buoyancy `F_net_buoyancy = (rho_air - rho_He)*g*gas_volume - (m_envelope+m_payload+m_suspension)*g` as an initial term, with consistent gas mass treatment, variable drag and vertical integration. Geographic integration through an ellipsoidal/geodesic solution, not `lon += meters/111km` globally. Fixed-step RK4 baseline, adaptive option with tolerances and convergence tests. Avoid integrating into invalid wind volume. Terrain intersection uses public elevation product with attribution, optional synthetic flat earth test. Snapshot every e.g. 1–5 min, integrate at smaller time step where needed.

### Outputs
Per sample: true forecast data timestamp, lat/lon, MSL and geopotential altitude, vertical/horizontal speed, pressure, ambient temperature, U/V, balloon radius/volume, lift, float phase, model member, scenario ID, provenance. On map show predicted median/representative track and envelope of actual ensemble members, not made-up Gaussian corridor. At lead > forecast max, stop or mark explicit climatological extrapolation with degraded validity.

### Scenario strategy
- Small deterministic smoke test in seconds.
- 10–50 scenario sensitivity run in modest hardware.
- Larger calibrated ensembles with job progress, RAM quota and cancelation.
- Vary launch time, target altitude, payload mass, helium fill, sun-shading scenarios, gas leakage and weather member separately, with sensitivity ranking.
- Each scenario's inputs/outputs stored for exact reproduction.

## 7. Radio coverage, node mapping, packet budget and real reception (P3)

**Critical design principle:** a node does not equate to a coverage circle. The UI must separate `known gateway positions`, `possibly reachable`, and `actually received`. Radio simulation must be possible offline with a cached receiver snapshot.

### Gateway data
- Primary adapter: [Packet Broker Mapper API](https://packetbroker.net/getting-started/api/), documented `GET https://mapper.packetbroker.net/api/v2/gateways` and gateway detail responses. Verify endpoint, paging/filtering, access, rate limits and licence against live responses before shipping. Do not presume every gateway is public, correctly positioned, operational or hearing our channel.
- Fields: network ID, gateway/EUI (hash or redact for public if appropriate), lat/lon/elevation/accuracy, last update, online indicator, antenna placement INDOOR/OUTDOOR if present, regional freq plan, supported channel frequencies, receiver types and capabilities where provided.
- Secondary/manual: opt-in volunteer ground stations; actual captured packet reception (RSSI/SNR/channel/data rate/time). Optional import from SondeHub Amateur's documented public APIs after verifying integration rights; SondeHub is not an unconfigured arbitrary-LoRa cloud forwarder.
- Unknown antenna height, cable loss, feeder, RF filter, gain, service uptime and noise must remain unknown, surfaced in uncertainty mode.
- Every gateway snapshot has downloaded-at timestamp; automatic freshness warnings, filters for indoor and stale nodes; counts do NOT imply total worldwide coverage.

### Link model per trajectory point and receiver
1. Identify candidate gateways by geographic index, NOT iterating all gateways against every particle/time-step.
2. Check frequency/channel/LoRaWAN-region compatibility and whether the radio profile has a permitted/approved simulated scope.
3. Compute ellipsoidal geometric radio horizon and true slant range, receiver elevation angle, balloon/ground heights. Optional SRTM/Copernicus DEM terrain LOS and first-Fresnel obstruction. Warn DEM unavailable or incomplete.
4. Compute link margin `P_rx[dBm] = P_tx[dBm] + G_tx[dBi] + G_rx[dBi] - L_free_space[dB] - L_feeder - L_polarization - L_obstruction - L_other`, compare with modulation-specific receiver sensitivity and chosen fade margin. Estimate ranges for unknown values.
5. Antenna patterns: start isotropic/ideal dipole, configurable vertical polarization, boresight and arbitrary yaw/pitch/roll distributions, balloon metallization/solar-panel detuning as uncertain additional loss, not exact prediction. Imported measured patterns possible later.
6. Determine candidate time windows and payload throughput. LoRaWAN gateway reception needs channel, data rate and network-server compatibility; having enough link margin doesn't imply a data packet is forwarded to the user's backend.
7. **Model packet success as scenario assumption** (optimistic/nominal/pessimistic margin and noise) until calibrated from real measured reception. Do not report a scientific percentage link success from coordinates alone.
8. Provide map of receiver markers, stale/online/freq-plan filters, radius candidates, elevation plots, time contact matrix, per-gateway link margin, candidate packets, bytes.

### Legal/network airtime
- Separate layers: government/regional RF rules and approvals; LoRaWAN regional parameters; public network provider restrictions such as TTN's 30 s uplink/day and 10 downlink/day, per documented TTN Sandbox fair-use policy. Never allow a simulator to convert 10%-duty band into approval to use it in flight.
- Exact LoRa time-on-air formula with SF7-12, BW, CR, CRC, preamble, explicit/implicit headers and low-rate optimization; include LoRaWAN PHY/MAC overhead, OTAA join cost, RX windows, retries and duty-cycle ledger by sub-band/region. Test against [TTN airtime calculator](https://www.thethingsnetwork.org/airtime-calculator) for multiple EU868 vectors.
- For one-radio architecture, prohibit simultaneous LoRaWAN and direct-LoRa use or simultaneous reception/transmission. Model switching latency/energy and lack of connectivity to custom direct-LoRa receivers unless volunteers actively decode and forward compatible packets.
- If no fresh GPS or authorized RF profile, enforce simulated radio-off and local logging; stop-and-report unknown crossing permissions. Spectrum regulations differ by country and water/air jurisdiction; simple land polygons are only a visualization, not a complete legal solution.

### Expected data delivery, not only possible RF contacts
Implement a **time-driven packet queue simulator**:
- Inputs: producer events (weather every X seconds; GNSS every Y; event flags; photo capture); priority queue; flash log; radio modes; legal airtime; predicted/observed contact; net energy reserve.
- Strategies A fixed beacon, B demand-driven contact prediction, C energy-adaptive and blackout-aware, D robust repetition/fragment/FEC schedule; compare equal budgets.
- Packet manifest: protocol version, mission ID, boot counter, packet sequence, UTC validity timestamp or reconstruction source, message type, length, CRC, FEC encoding (when used). Storage event identifiers can avoid repeating full photo metadata per fragment but still require image and fragment IDs to reconstruct.
- Loss/out-of-order/duplicate models, backoff, sparse acknowledgements and fallback to broadcast-only. Queue aging, garbage collection, overwriting policy and flash endurance. No assumption of positive ACK if uplinks are unconfirmed.
- Metrics: generated bytes, stored bytes, attempted/transmitted/received bytes, unique received bytes, scientific observations delivered, newest position age, time in outage, image thumbnail bytes received, full image completeness, energy spent per useful delivered byte, pending backlog, checksum failures.
- Show **three bounds**: theoretical under favorable ideal contact, empirical-calibrated where available, conservative using unknown receiver factors. Distinguish results by uncertainty quality.
- Add **contact window opportunity explorer**: for a candidate 20-min contact, show whether a tiny grayscale photo can fit in legal and energy budgets, at selectable SF, CR, packet lengths and missing-fragment assumptions.

### Critical acceptance tests
- Path with no receivers never reports image delivered.
- Receiver incompatible with channel or modulation cannot receive packet.
- An indoor stale node is not equal confidence to an observed decoding station.
- Duplicates from multiple gateways count as one useful uplink.
- Contact opportunity shorter than air-time and receive windows cannot transfer a full packet.
- TTN restrictions and legal duty-cycle enforced independently.
- Packet loss with SSDV-like transport can yield intentionally partial image if decoder supports it; no invented recovered imagery.

## 8. Sun, solar panels, power budget and brownout digital twin (P4)

### Illumination and attitude
- Use sky/solar geometry from `pvlib` or accurate solar-position algorithm with known UTC and flight lat/lon. Derive solar direction in ENU and transform using payload attitude quaternion and panel normal vectors.
- Compare coplanar, two upward-splayed panels (0/30/45/60 deg), and opposing-fold geometry from user's CAD reference; specify which surface is photovoltaic and what reference axis defines angle. Implement random yaw, slow spin, pitch sway and worst-case persistent shadow.
- Direct irradiance as a function of panel normal and incoming sun direction, plus configurable diffuse and albedo (not zero above cloud deck). Shadow masking from balloon/PCB only with a simplified disclosed geometry model first; real 3D ray tracing optional.
- The default `pvlib` terrestrial irradiance model is **not** a validated 12–14 km stratospheric solar model. Use simplified upper-atmosphere/direct solar forcing with explicit assumptions and uncertainty bounds; validation requires test or published datasets.

### Electrical hardware model
- Harvesting/charging source: panel I–V approximation / measured curves, MPPT assumption, BQ25570 cold-start constraints (model from verified datasheet and hardware characterization; no unrealistic regulated ideal voltage), charge threshold, supercapacitor voltage and leakage.
- Regulator/PMIC efficiency depends on load, voltage and temperature; optional lookup tables from experiments, not one magical efficiency constant.
- Capacitor energy `E=0.5*C*V^2` with ESR transient drop `V_drop≈I*ESR`, voltage-limited operation, measured cold C/ESR/leakage. Preserve hardware hysteresis `wake > shutdown`, main load disconnected until upper threshold, high impedance when off.
- Load profiles: sleep, RTC, boot, GNSS warm/cold fix, sensor read, flash page program & erase, LoRa transmit at given RF power, LoRa RX, camera boot/capture/readback, IMU window, optional imaging copro power. Work in joules per event plus transient current/time curves.
- If insufficient energy, scheduler skips camera first, then archives, and preserves safety beacon/GNSS if physically possible. Avoid claiming reserve when harvester physically cannot support the load.
- Overnight and cloud/weather shadow cases, subzero component qualification limits, extreme boundary cases, false power-state transitions.

### Results/UI
Joules generated/consumed, storage V timeline, load waterfall, sunrise/sunset, cold starts, device uptime, GPS/photo success counts, packet deliverability vs solar panel angles. Simultaneously show payload mass impact (panel weight, storage weight, resulting lift changes). Execute multi-objective parameter sweeps.

### Tests
- No sun, finite cap -> physically consistent discharge/off; cap voltage never negative.
- Marginal sun cannot induce unlimited rapid boot loop because hardware gate waits for high threshold.
- Measured high transient current can trigger supervisor if ESR causes drop; model reports fault.
- Stored energy conservation within tolerance with known panel/load fixture.
- Invalid capacitor voltage/polarity/thresholds rejected.
- Relative energy vs panel orientation compared with analytic dot-product cases.

## 9. Balloon sizing, mass, mechanical and RF integration lab (P4/P6)

- Import current component candidates with mass, dimensions and mounting position; assemble BOM live mass/center of gravity/center of projected area with tolerances, plus balloon envelope and suspension.
- Helium fill, envelope compliance (stretching vs superpressure), max radius/volume, gas leak, night thermal contraction, free-lift assumptions; physics level selection. Warn physical envelope unknown: do not assign a guaranteed float altitude or weeks-long life.
- Input panel vectors/area and boom geometry to share with sun model; antenna position/orientation/obstacles to share with radio model; camera optical axis/FOV/obstacles to share with imaging model. Camera and antenna obstruction warnings from simple geometry, not photorealistic CFD.
- Make payload model visually compare flat wings vs splayed wings, mass versus predicted harvest, no fabricated optimized answer before calibration.
- Add air-density and thermal envelope variation sensitivity; storm and atmospheric-icing assumptions; safe recovery/landing risk zone, aviation and environmental warnings.

## 10. Imaging and image recovery lab (P6)

Hardware still open: candidate light SPI+FIFO OV2640 (Arducam Mini/new revision), alternative Arducam Mega 3MP, third option a *switched* ESP32-S3 with bare OV2640 and enough PSRAM. Model power, boot, mass, optics, buffer and cold rating as distinct modules. Avoid choosing the sensor simply from pixel count or sticker price. Camera only activated if power and delivered-image test gates pass.

### Ground footprint and pointing
- Camera nominal horizontal/vertical field of view, lens distortion, 2D optical axis/attitude, geographic position, MSL altitude, terrain height -> polygon footprint with uncertainty.
- Flat, nadir approximation `footprint_width=2*h_agl*tan(HFOV/2)` for early UI; real ray/terrain intersections for tilted lens; proper ellipsoid and terrain when available.
- Simulate IMU fusion: accelerometer supplies gravity direction only when dynamic acceleration limited; gyro rotational rate; yaw unobservable without further sensor/reference. Don't report perfect georeferencing.
- Capture window user-configurable (e.g. planned time ±10 s). Opportunistic low angular-rate/near-nadir trigger. If never ideal, select best acceptable view or skip with reason. Capture frequency based on footprint movement, intended overlap and marginal energy; zero overlap is not a recommended default (tilt/wind/terrain create gaps).
- Night, cloud, lens condensation/icing, mechanical obstruction and sun-glint checks as modeled risk flags. No fake inference that weather forecast tells us local cloud-free view with certainty.

### Compression/transmission bench
- **Use real user-uploaded pictures** (including public Earth imagery with proper permission) for codec experiments. Decode to grayscale JPEG at various Q/width/height, RGB JPEG comparison, PNG/lossless baseline, empirical output size/PSNR/SSIM. Important: convert to grayscale *before* JPEG encode; do not assume converting an already compressed color JPEG saves bytes without recompression.
- Distinguish full-resolution archival JPEG, standalone tiny thumbnail, and packets for radio. Benchmark image encoding/capture energy experimentally when hardware arrives; desktop CPU times do not equal MCU energy.
- [SSDV](https://codeberg.org/fsphil/ssdv) source for error-tolerant packet concepts; standard SSDV packet framing may be too large for certain LoRaWAN application payload limits. Build separately versioned `image_manifest`, `image_fragment` with monotonically indexed chunks and CRC; optional FEC profiles after baseline working; no unsupported progressive refinement claim.
- Given link-contact schedule, send thumbnail/important image fragments without interfering with safety beacons. Allow partial fragments to be shown ONLY if decoder can actually reconstruct them (do not fabricate pixel tiles). Show predicted packets/airtime/energy vs measured received fragments.
- Image IDs link to the latest timestamped observation, with explicit clock and association tolerance; repeat image ID & fragment index per packet, not full metadata.

### Geolocation analysis
- Default: original GNSS+time+orientation rough footprint; matching to [Copernicus Sentinel](https://dataspace.copernicus.eu/) reference images via OpenCV feature matching or learned matcher behind optional dependency.
- Reference data may have lower resolution, clouds, different season and geometric distortions. Use RANSAC and quality/confidence; permit `UNMATCHABLE` output instead of hallucinating location. No Google Earth imagery scraping. All images stored with licence and provenance.

### Verification
- Input a real test JPEG; fragment it, drop 30% under seeded scenario, reconstruct the actually supported partial image, report recovered fraction and corruption.
- Compare RGB/grayscale compression tradeoffs; run sizes and SSIM on multiple photographs, not a single image.
- Check capture timing and orientation for analytic attitude examples.

## 11. Firmware, digital flight computer, fault injection (P5)

**Goal:** exercise actual decision logic before hardware exists. Firmware logic is a portable library linked by native test executable and eventually the STM32 target. If an ESP32-S3 is added, it is a separately power-gated camera accessory with a minimal serial/SPI command protocol, unless measured evidence justifies replacing the main MCU.

### Finite-state machines
- POWER: `OFF_HARVESTING -> READY_BOOT -> BOOTING -> ACTIVE -> CONSERVE -> SHUTDOWN_PENDING -> OFF_HARVESTING`. Gate hardware power state independent from firmware; watchdog unexpected reset cause captured.
- FLIGHT: `GROUND_TEST -> ASCENT -> FLOAT -> DESCENT_SUSPECTED -> DESCENT_CONFIRMED -> LANDED / LOST`, with debounce and evidence thresholds; never interpret one negative velocity sample as verified descent.
- DATA: `APPEND -> VERIFY -> QUEUED -> TX_ATTEMPTED -> ACKED_IF_PRESENT`, separate from receipt truth; flash journal with CRC, commit marker, wear/erase constraints, sector recovery and reboot counter.
- RADIO: `DISABLED_NO_AUTH -> ARMED -> TX -> RX_WINDOW -> IDLE`, enforce resource and region profile constraints. Separate regulatory and network quotas.
- CAMERA: `OFF -> POWERED -> INITIALIZING -> WAIT_ORIENTATION -> CAPTURE -> STORE -> OFF`; power/timeout safeguards, no blocking whole flight computer.

### Deterministic HIL-like virtual transport
- Native executable accepts `scenario.json`, e.g. arrays or callbacks for GNSS fixes, weather samples, power source and receiver opportunities; yields `events.jsonl` with reproducible timestamps.
- Hardware abstraction interface includes read_voltage, read_gps, read_sensors, flash_append, flash_read, tx_packet, request_rx_window, camera_capture, monotonic_clock, set_power_domain, store_boot_reason. Provide fake drivers and tests. Mark unsimulatable actual RF and electrical behavior clearly.
- Fault injector: lost/stale GPS, time rollback, repeated radio/no ACK, flash program interruption, storage full, extreme reset, wrong sensor, unexpected descent, cold cap loss, panel shaded, camera crash, missing server, boundary crossing.
- Enforce watchdog, bounded retry count, backoff, and failure priorities. Radio/image cannot block periodic local data logging indefinitely.
- Firmware deploy package must capture git hash, RF profile allowlist hash, tested hardware rev, firmware version, checksums and configuration; test all functions without flash wear surprises.

### Native test acceptance
1000 deterministic power restarts; corruption/write power cut at every major journal transition; ring buffer conservation and no invalid overwrite; mode and transmit enforcement; stale GNSS never marked current; no GPS data used after timestamp invalid; camera failure cannot stop normal telemetry; no negative storage or energy.

## 12. Ingestion, actual packet processing and Mission Control (P7)

Adapters: local USB serial receiver (custom packet protocol), The Things Stack application MQTT/webhook when registered, optional SondeHub Amateur ingestion/publication after validating supported formats and policies, import of raw logged bytes and authorized manual station. Maintain receiver identity, RX timestamp, channel, RSSI, SNR and decoder provenance per copy of uplink, then deduplicate in separate `observations` table. Never delete raw packet evidence. Private satellite backhaul is a different architecture: GNSS-only does not transmit telemetry to navigation satellites.

UI must show:
- Last received *confirmed* position and fix age versus last model forecast position; data freshness color/wording.
- Packet decoder success, unique bytes, contact event history, radio airtime, last receiver ID, current storage/energy telemetry, boot/restart count and reset cause.
- Line plots pressure/temp/altitude (measured) and expected environment (modeled), data-gaps deliberately visible.
- Image progress (N/M known chunks, thumbnail/frame reconstruction), no fake imagery.
- Alerting with context: 'No beacon in 8 h' not necessarily 'balloon dead'; evaluate predicted contacts and prior outage patterns. Alert severity relates to uncertainty.
- Fast one-click export of all raw and normalized data and contact evidence.
- Local buffered ingest if WAN down; simple TLS/API key handling for community receivers; rate limits, signatures where possible, no secrets in public frontend.

Recovery module: detect sustained descent with uncertainty, run descent physics and wind ensemble, show last true fix distinct from landing estimate; label approximate radius and refresh from new observations. Personal recovery page with opt-in report, avoid prompting hazardous access, and no broadcast of personal contact info.

Postflight: replay actual packets against preflight forecast snapshots; wind estimate from GNSS motion; trajectory skill at 6/12/24/48 h; residuals by altitude/location and model cycle; measure delivery performance per receiver, unique bytes/J, recovery completeness; scientific anomaly flags, evidence graphs. Export CSV/Parquet/GeoJSON/NetCDF/KML where appropriate and complete simulation manifest.

## 13. Launch Window Lab and mission optimization (P6)

- Candidate location and date/time slider, daylight, predicted local surface conditions, upper-air wind transport, candidate gateway encounters, energy supply, airspace flags and end-of-life risk.
- For each candidate time, run identical hardware assumptions and ensemble settings. Show Pareto frontier: `useful_received_bytes`, `position_freshness`, `energy_headroom`, `radio opportunity`, `uncertain landing exposure`, `risk`, `cost`. Do not optimize raw air distance blindly.
- User chooses weighting but hard constraints (authorizations missing, unsupported RF region, tested envelope incompatible) remain blocking. Invalid model period never ranks as better due to missing data.
- Sensitivity analysis: +/- 2–10 g mass; +/- capacitor size; panel angle; beacon period; SF; image frequency; satellite data availability assumptions; gateway subsets. Show tornado chart and confidence level.
- **Golden launch-day replay:** iterate over dozens of previous launch days using ONLY archived forecasts available on those dates; score against available historical observations. Explicit historical receiver-network coverage source or mark today's gateway map as an optimistic counterfactual. No cheating with ERA5 or later weather forecasts.
- Provide a human-readable decision card 'Why this date?' with top three favorable factors, top three risks and evidence.

## 14. Mission assurance and costs (P6)

- Risk register FMEA style: failure type, evidence, severity, plausible occurrence, detection, mitigation, test status and owner. Avoid bogus numerical mission-success probability until modeled uncertainties are calibrated.
- Required documents: ENAC launch request/status; radio permissions for profiles/geographies; NOTAM coordination as applicable; liability/recovery/environmental plan; proof of compliance for all attempted cross-border operations; tests and calibration log. Operators make legal decisions: software merely records and blocks unconfigured transmit profiles.
- Component candidate matrix with mass, electrical specs, thermal rating, RF notes, supplier link, price timestamp, VAT/shipping caveat, availability, confirmed/estimated/unknown; change one hardware candidate -> invalidate relevant simulations.
- Planning cost ledger: one-launch expendables, reusable test equipment, PCB boards and stencil, components, helium, shipping, authority fees, optional camera, spare electronics; explicitly show optimistic/nominal/pessimistic ranges. No assumption €5 populated board.
- Readiness checklist sections: firmware, power, radio, GNSS, optical, envelope, lift, weather forecast validity, ground network, authorizations, bench tests, cold tests, end-of-life. Each has evidence URL/file, version, reviewer acknowledgment, date and open blocker; export briefing PDF later only if needed.

## 15. UX/visual design contract — user's INAI diagnostic reference + Apex-style clarity

**Visual direction:** premium and restrained engineering diagnostic software. Inspired by user's uploaded reference: near-black floating panels, extremely clean typography, large precise numbers, tiny status indicators, thin neutral rules, small segmented controls, amber warning strips, white text on charcoal, very limited saturated accents. Inspired by Apex Health's focus on direct daily insights, NOT its crowded sidebar. Desktop-first, fully responsive and readable on mobile. Avoid shiny sci-fi gradients, huge glowing globe backgrounds, generic admin templates, emoji, cards filled with filler metrics or animations that obscure real results.

### Design tokens
- Background `#0B0B0D`; primary surface `#131316`; hover surface `#1B1B20`; borders `#2B2B30` (subtle 1px).
- Primary text `#F5F5F5`; secondary `#A1A1AA`; tertiary `#71717A`.
- Accent reserved for measured/selected path `#6CB7C6` (subtle muted cyan); caution `#FFC34D`; serious issue `#D86565`; success `#7FBBA1`.
- Radius 18px main canvas and 10px inner panels; compact status pills 5px radius. Typography: Inter, Geist or system sans (do not redistribute fonts); number font with tabular figures; use 48–72px sparingly for headline readings, 12–14px small metadata never below 11px for essential UI.
- Grid 12 columns, nav rail 220px desktop collapses to 64px icons; page title, mission selector, mode+live status and one primary action at top. On mobile bottom nav or navigation drawer; charts scroll deliberately.
- Alert color conveys a semantic event, not decorative preference. Show confidence with text and state, not color alone. AA contrast target, keyboard focus visible, reduced motion, colors not sole status signal.

### Information hierarchy
Top bar: `STRATOS / [Mission]`, `SIMULATED | REPLAY | TEST | LIVE`, last updated UTC, data provenance, user action `RUN`/`EXPORT`.

Side navigation with just 6 sections, expandable: **Overview, Plan, Simulate, Test, Flight, Analyze.** Contextual subnav within each; no 14 simultaneous pages in the sidebar.

**Overview:** a large mission status title, short meaningful subheading, up to 4 real KPIs (validated forecast horizon, probable/possible contact count with confidence qualifier, energy safety margin, unresolved critical blockers). A single ‘Why this outcome?’ expandable panel; recent events and next engineering action. Do not invent percentage success score.

**Plan / Mission builder:** clean split form with edit panel + live derived totals; user sees mass, lift estimates and dependency warnings as they change settings. Special pane with compact visual payload model and solar vectors.

**Simulate / Flight:** central 2D map showing track, dashed predictions, thin uncertainty corridors and gateways; right contextual inspector. Timeline scrubbing synchronizes altitude, sunlight, voltage, packets and forecast time. 3D globe is secondary toggle/lazy-loaded.

**Simulate / Connectivity:** left map, right receiver inspector; choose 'candidate visibility', 'link-margin', 'actual decoded'. Hover contact in timeline -> show link budget components, receiver freshness, compatible channels, theoretical transferable bytes and likely missing data. Color/legend must disclose uncertainty.

**Simulate / Energy:** one focus graph (storage voltage with wake/shutdown thresholds), compact breakdown of harvested vs spent joules, event markers (camera/radio/GNSS), control for panel orientation and capacitor. Small side-by-side alternatives with differences, not cluttered gauges.

**Simulate / Camera:** drag/drop actual photograph, high-quality preview and recovered-packet visualization, controls for gray/RGB, JPEG Q, dimensions, loss seed, radio mode; indicate objective size, quality and airtime; never pretend sample is real aerial capture.

**Test:** hardware log, plots, calibrations with green/warning/red only for actual thresholds; recorded evidence links.

**Flight:** live location, latest packet age, GNSS fix, power, flight phase, last ground receiver, backlog and image stream. Time-series graph and raw packet log via segmented control like reference.

**Analyze:** trajectory model errors, telemetry recovery, scientific measurements, actual images and export.

### Concrete UI microinteractions
- Every number tooltip: definition, unit, status, source, last update, model assumption.
- A 'compare' tray allows selecting at most 3 scenarios to avoid excessive cognitive load.
- Profile presets: `Barebones beacon`, `Science`, `Camera`; editable and visibly assumed. No hidden profile side effects.
- Empty state says *why* no data: `No NOAA forecast available for selected date; load a supported cycle`, `No compatible gateway snapshot`, etc.
- When downloading 100s MB GRIB: show estimated bytes, subregion, progress, retry and cancel; never freeze UI.
- Save views/shareable simulation URL with mission revision IDs (no private tokens embedded).
- Provide realistic pre-seeded DEMO fixture but clear `DEMO DATA` watermark and no fake live feed.
- Image aspect ratio and maps responsive; screenshot reference is a *design reference*, not a set of specific buttons to reproduce.

### Browser performance
- Debounced scenario sliders, off-main-thread heavy processing, job status stream; avoid full trajectory reruns on every slider tick until user commits for expensive models.
- 3D Cesium on demand; charts downsampled for display while raw points preserved in back end.
- Render only visible list rows for large telemetry logs; server-side pagination.

## 16. APIs and runtime behavior

Suggested endpoints, names may be refined only with documentation:
```
GET    /api/health
GET    /api/providers/weather
GET    /api/weather/runs?provider=GFS
POST   /api/weather/downloads
GET    /api/weather/downloads/{job_id}
POST   /api/missions
GET    /api/missions/{id}
POST   /api/missions/{id}/revisions
POST   /api/simulations
GET    /api/simulations/{id}
POST   /api/simulations/{id}/cancel
GET    /api/simulations/{id}/events   # SSE
GET    /api/simulations/{id}/trajectory
GET    /api/simulations/{id}/energy
GET    /api/simulations/{id}/contacts
GET    /api/simulations/{id}/delivery
GET    /api/receivers?bbox=...
POST   /api/receivers/sync
POST   /api/telemetry/ingest          # token protected
GET    /api/telemetry/latest?mission_id=...
GET    /api/telemetry/packets?mission_id=...
POST   /api/imaging/compression-benchmark
POST   /api/tests/import
GET    /api/readiness/{mission_id}
GET    /api/exports/{job_id}
```

All long requests create a durable job with progress/failure details and timeout; no oversized synchronous compute. Return meaningful validation errors (field/unit/time). Expose OpenAPI schema. Protect write operations and file imports, set upload size limits. Keep secrets server-side.

Streaming message types: `job_started`, `download_progress`, `sim_step_summary`, `warning`, `job_completed`, `job_failed`, `telemetry_packet_received`, `image_fragment_received`. Store the finalized results so page refresh does not lose work.

## 17. Scientific validation and quality gates

### Core tests
1. **Weather:** 3D interpolation analytic synthetic arrays, time interpolation, varying pressure levels, dateline, latitude wrap, missing data, no look-ahead. Pin a real selected NOAA run in fixture metadata.
2. **Trajectory:** no-wind stationary; constant wind known geodesic displacement to within reasonable discretization; time-step convergence; pressure/geometric height conversion; onset of float/descent; stop at ground; no unsupported extrapolation.
3. **Radio:** FSPL independent textbook cases; horizon scaling; Fresnel approximation; channel and modulation compatibility; packet time-on-air vs TTN calculator vectors; independent regulatory/public policy quotas; multi-gateway deduplication.
4. **Data:** no receiver yields 0 received bytes, impossible contact yields 0, fragment lost corrupt never silently reconstructed full; consistent flight packet IDs, storage journaling power cut at any record boundary.
5. **Energy:** unit-test V² capacitor math; power conservation within defined tolerance; brownout hysteresis; regulator/ESR drops; panel normal analytic cos angle; photo skipped under energy reserve.
6. **Firmware:** deterministic native state machine, stale fix rejected, battery-low forces passive charge mode, watchdog recovery, flash journal CRC.
7. **UI:** four modes explicit, mock watermark, missing-provider errors, basic screen reader and keyboard nav, risk alert distinction.

### Credibility review
Every metric has `measured | validated_forecast | modeled_uncalibrated | hypothetical` quality. The words **probability of contact** or **probability of mission success** must not appear numerically unless calibrated statistically on independent data. Report scenario spread otherwise. An AR model should not learn from a future balloon observation when predicting past time.

### Acceptance demonstrations
A. Fresh NOAA forecast -> route on map -> save -> reopen -> identical result with hashes.
B. Given same route, switch solar panel tilt -> energy outcome changes physically with sun attitude.
C. Add a gateway on right compatible band -> candidate contact changes; change it to incompatible band -> disappears.
D. Generate 100 sensor packets and image fragments -> inject packet losses -> accurate number of unique recovered bytes and actual partial/full image status.
E. Inject power failure during archive write -> old committed data survives restart.
F. Simulated legal unknown region -> radio stops but flash sampling continues.
G. Compare two candidate launch times -> explain differences with model run and actual forecast data.
H. Import bench current CSV -> calibrated load curve re-run changes energy estimates with traceable provenance.

## 18. Nice-to-have features only AFTER science core passes

- Global receiver community portal with opt-in volunteer uploads and receiver health monitoring; could show expected contact in their local time and link to technical setup.
- Offline precomputed on-board contact atlas, small and versioned, to help postpone archive transfers over open ocean. No blind assumption the current gateway map remains accurate for weeks.
- Smart sensor scheduling / **value of information**: prioritize GNSS/samples whose marginal scientific benefit exceeds energy and airtime costs, while retaining minimum safety beacons.
- Auto-created mission operations briefing and paper-trail pack, including source run ID, risk register and open launch authorization tasks.
- Project blog update generator from *real* milestones and measurements, with opt-in public mission page. No auto-publishing or fake social proof.
- Public reference-image geolocation from actual camera shots with verified confidence.
- Integrated cost optimizer using best-effort component mass and availability estimates; trade hardware alternatives under budget constraints without implying they are flight-qualified.
- Scenario change impact graph: flag all simulations invalidated by changing the power store, camera, envelope or RF layout.
- Latency-aware scheduling / benefit curve: plot expected useful bytes/J against beacon and image retransmission policies.
- Flight data forensic mode: after unplanned reset, visualize last successful flash commit, watchdog reason and last known healthy state.

## 19. Hardware decisions Codex must NOT silently settle

- **Main MCU:** RAK3172/STM32WLE5 baseline (256KB flash, 64KB RAM, single sub-GHz radio) because low-power LoRa needs; this is NOT an ESP32. No assumption stock RAK3172-8 EU868 board can switch to 434 MHz through software, even though its silicon supports wide tuning: filter/matching/antenna/module-specific assembly matter.
- **Camera candidates:** modern Arducam Mini 2MP SPI OV2640/FIFO has advertised 5.7g module mass and peak up to 0.7W, but actual temperature/weight/power must be tested. Arducam Mega 3MP SPI: 33x33mm, roughly 0.185–0.585W depending on operation, development-friendlier than flight-light. ESP32-S3+bare OV2640/PSRAM option: independent higher-energy processor and external radio unless separate STM32WL retained. Evaluate both by *total grams, joules/image, dependable JPEG output and safe cold start*. Beware older Arducam Mini datasheets describing ~20g different hardware.
- **PCB:** manufacturer $2/5 bare 2-layer boards is a promotional baseline excluding special thickness, white mask surcharge, shipping, stencil, paste, components and scrap; assembly by user is possible but QFN fine-pitch components and RF matching need reliable reflow + inspection. Use a dedicated vented electronics oven/hotplate; NEVER reuse a kitchen oven for cooking after solder paste reflow. Stencil is for solder paste; solder mask is PCB coating, not a placement stencil. Plan to test soldering on cheap practice boards.
- **Instruments:** no requirement to BUY PPK2/NanoVNA initially. Low-cost INA226/INA219 can measure slow current but misses fast peaks and may be inaccurate at µA sleep, so borrow power analyzer/shunt-scope for final energy qualification. Likewise borrow calibrated VNA or licensed operator's RF bench for antenna return loss/isolation; don't sign off RF performance from software simulation alone.
- **Camera operating temperature:** manufacturer ratings often only to -20°C or warmer; not automatically qualified for -40/-55°C stratospheric ambient. Need insulation/sun exposure/thermal testing, not a fabricated guarantee.
- **International operation:** GPS jurisdiction profile checks are a conservative enforcement mechanism ONLY. Written aviation and airborne radio authority clearance remains necessary. No automatic legal right based on inferred meteorological purpose.

## 20. References and research starting points (verify in current upstream)

1. NOAA GFS cycles/GRIB: https://www.nco.ncep.noaa.gov/pmb/products/gfs/nomads/ ; https://nomads.ncep.noaa.gov/info.php?page=gribfilter
2. NOAA GEFS: https://nomads.ncep.noaa.gov/
3. Tawhiri models including float: https://github.com/cuspaceflight/tawhiri/blob/master/docs/api.rst
4. Stratolink full project: https://github.com/Stratolink-hq/Stratolink
5. Copernicus CDS/ERA5: https://cds.climate.copernicus.eu/
6. Packet Broker Mapper: https://packetbroker.net/getting-started/api/ ; https://mapper.packetbroker.net/api/v2/gateways
7. SondeHub Amateur: https://amateur.sondehub.org/ ; https://github.com/projecthorus/sondehub-infra/blob/main/swagger.yaml
8. TTN airtime calculator: https://www.thethingsnetwork.org/airtime-calculator
9. TTN limits: https://thethingsnetwork.github.io/docs/lorawan/duty-cycle/
10. RAK3172 MCU/RF: https://store.rakwireless.com/products/wisduo-lpwan-module-rak3172
11. ST STM32WL datasheet: https://www.st.com/resource/en/datasheet/stm32wle5cb.pdf
12. Espressif camera driver/memory: https://github.com/espressif/esp32-camera
13. Arducam newer Mini 2MP SPI: https://www.arducam.com/arducam-new-2mp-mini-spi-camera-module-for-arduino-uno-raspberry-pi-pico-and-other-mcu.html
14. Arducam Mega 3MP: https://docs.arducam.com/Arduino-SPI-camera/MEGA-SPI/MEGA-SPI-Camera/
15. JLC PCB promo, assembly and stencil: https://jlcpcb.com/help/article/how-do-i-place-an-order ; https://jlcpcb.com/help/article/pcb-assembly-price ; https://jlcpcb.com/help/article/how-to-order-a-stencil
16. ENAC launch admin: https://www.enac.gov.it/app/uploads/2024/04/ATM-05B_130521_web.pdf ; https://www.enac.gov.it/spazio-aereo/gestione-dello-spazio-aereo/riserva-di-spazio-aereo/tariffe-per-segregazione-spazio-aereo/autorizzazioni-vds-spettacoli-pirotecnici-palloni-manifestazioni-notam-lanci-paracadutisti
17. SSDV: https://codeberg.org/fsphil/ssdv
18. Copernicus satellite imagery: https://dataspace.copernicus.eu/
19. pvlib: https://pvlib-python.readthedocs.io/
20. Batteryless LoRa academic model: https://arxiv.org/abs/2402.07528

## 21. Exact instructions for Codex right now

1. **Audit this specification and the local repo**. Make `ARCHITECTURE.md`, `DECISIONS.md` (ADR format) and `PROJECT_STATUS.md` that each distinguish verified, implementable-but-uncalibrated, research-only, and blocked by third party/hardware/legal authority.
2. **Do not immediately implement all of P0–P7.** First implement P0+P1 as an end-to-end real application: real NOAA GFS download/cache -> physical kinematic trajectory -> visible and usable MapLibre UI -> saved exact configuration and run manifest -> tests -> README. Then evaluate in practice.
3. At every phase completion, run lint/typecheck/tests, exercise a real input route, and describe exactly which external API was called with which dataset cycle and reproducibility info. Surface limitations.
4. If network access is missing in development, use checked-in tiny verified reference GRIB or generated synthetic field labeled synthetic, never pretend the source is live.
5. Keep costs at €0 for software and services; no paid third-party APIs and no unverifiable dependencies. Linux/Windows developer friendly; 8GB RAM baseline.
6. Deliver clear working UI in reference-inspired dark style; do not prioritize design over scientific correctness.
7. End each implementation milestone with an explicit `NEXT_CODEx_TASK.md` containing only the next implementable vertical slice, blockers and test commands.

**Done is demonstrated behavior, not generated source code.**

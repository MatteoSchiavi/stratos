# Reliability research and implementation review

Started 27 October 2026 after the first demonstrated P0/P1 slice. Scope remains weather, trajectory, persistence and their usable UI, before expanding into unqualified RF/power/hardware models.

## Sources checked

- NOAA official GRIB filter documentation: https://nomads.ncep.noaa.gov/info.php?page=gribfilter (HTTP200). Cropped, field-selective requests are supported; the filter is a shared public resource, so the documentation explicitly requires a ten-second wait between automated fetches. The earlier half-second delay was insufficient; it has been replaced with cancellable pacing, including retries and adjacent crops.
- NOAA official GFS product inventory: https://www.nco.ncep.noaa.gov/pmb/products/gfs/nomads/ (HTTP200), and the actual 2026-10-27 12UTC atmos listing (HTTP200). Initialization is not publication; some cycles can still be filling. No assumption of complete hourly availability follows from the cycle directory.
- Installed SciPy numerical/interpolation API documentation and source; GeographicLib's WGS84 reference calculations. Independent GeographicLib arc/root-reference tests, not visual plausibility, validate the implemented solver change.
- ECMWF ecCodes metadata on retained actual GFS records and cfgrib/xarray extraction. Exact variable units, valid times and encoding remain part of data validation.

## Findings selected for implementation

1. **Height curvature:** old solver transports winds on the reference ellipsoid and discloses its omitted height correction. Implement a versioned WGS84 curvature solver using `phi_dot=v/(M+h)` and `lambda_dot=u/((N+h)*cos(phi))`. Preserve schema1 replay instead of rewriting old results. Do not interpret this numerical refinement as calibrated balloon physics.
2. **Path-length decimation:** old distance is a sum between exported samples, so changing snapshot cadence can change the result. Accumulate ground distance at integration steps and horizontal air distance by RK4 quadrature, independently from display sampling.
3. **Unusable weather default:** the previous 48h ROI can exceed the declared384MiB array bound. Use a smaller explicit default and validate estimates before a job is queued.
4. **Weather escape:** add opt-in bounded adjacent/time-segment fetching, pinned to the same run, with overlap checks, quotas, LRU decoded arrays and explicit failure. No global download, newer-cycle substitution or wind extrapolation.
5. **Weather inspection:** add actual cached-grid map vectors and vertical profiles, with time/altitude controls, forecast provenance and below-terrain/missing data errors.
6. **Local reliability:** atomic job claims, worker heartbeat, request/import boundaries, output integrity on export, reproducible backup and archive pagination. Database status alone must not imply a running worker.
7. **Usability:** clearly distinguish edited mission inputs from an opened archived run, show solver version/freshness, make latest-job progress and cancellation observable, and avoid repeatedly decoding all cached weather for a cursor request.

## Validation plan

Retain all earlier fixtures/outputs; add independent scientific references and failure-injection regressions. Exercise small actual NOAA requests first, then a48h cropped case with measured process memory and reproducible outputs. Recheck real browser workflows at desktop/mobile sizes. Hardware, receiver compatibility, power cycling, legal permissions, observed-flight calibration and a native Windows qualification remain outside this software pass; do not fabricate their evidence.

## Implemented outcome

All seven selected findings above have functioning implementations. Additional failure analysis led to immutable finalized weather-cache metadata, fixed source precedence independent of LRU recency, per-sample segment IDs and a loaded-code guard: hashing on-disk source at result time alone can falsely attribute already-loaded Python to later edits. The worker now pins startup scientific/dependency identity, checks before/after jobs and reports restart_required through its heartbeat.

The multi-channel vectorized weather interpolator measured about2.5x faster than repeated scalar interpolators in a1000-query local microbenchmark (5.40s versus2.14s). This is a local sampler measurement, not a universal end-to-end speed claim. The independent48h study then demonstrated bounded memory and a repeatable complete route. The archive selects newly completed job results explicitly, rather than relying on newest-list timing. A consistent SQLite backup includes checksummed input/output files; missing/uninitialized sources cannot produce a successful backup.

Final commands, actual numerical values, browser results, source hashes and remaining limits are recorded in [REVIEW_VERIFICATION.md](REVIEW_VERIFICATION.md). These changes improve numerical correctness and traceability; balloon physics, meteorological forecast skill and hardware reliability remain uncalibrated.

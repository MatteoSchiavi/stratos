# Install, configure and use STRATOS

STRATOS runs locally with a browser, a Python API and one background worker. No STRATOS/NOAA account, API key, subscription, Docker or balloon hardware is required. GitHub authentication is needed only if repository access is private. New weather downloads require Internet access to NOAA; saved calculations, bundled reference forecasts and the map work offline after installation.

This release provides P0/P1 engineering tools: configuration, GFS forecasts, prescribed-profile trajectories, pressure/altitude weather inspection, saved-study comparison and verified local evidence recovery. It does not qualify a balloon, receiver, power system or launch.

## 1. Requirements

- Git: https://git-scm.com/downloads
- Node.js24 LTS and npm: https://nodejs.org/ . Node24 is tested; the frontend requires at least22.12.
- uv: https://docs.astral.sh/uv/getting-started/installation/ . uv can install the required Python3.12 automatically.
- A current browser with WebGL2 for the map. An ordinary browser is sufficient; Playwright is only needed for development tests.
- Internet for the first dependency installation. Keep a local disk with sufficient space for dependencies, weather and backups.

Linux is verified. On Windows, the recommended route is Ubuntu under WSL2, using the Linux commands in the Ubuntu terminal. Native Windows/ecCodes and macOS have not been qualified in this environment. Store the WSL checkout/data in the Linux home filesystem. Installing WSL from an administrator PowerShell is `wsl --install -d Ubuntu`; follow its reboot/first-user prompts before continuing.

Check prerequisites in your terminal:
```sh
git --version
node --version
npm --version
uv --version
```

## 2. Download and install

```sh
git clone https://github.com/MatteoSchiavi/stratos.git
cd stratos
```

On Linux/WSL/macOS with Bash:
```sh
bash scripts/install.sh
```

The script finds its own checkout, installs the locked Python3.12 environment, installs/builds the client and migrates the local database. It does not erase existing mission records.

Equivalent individual commands, also useful for troubleshooting:
```sh
uv sync --frozen --python 3.12
npm --prefix apps/web ci
npm --prefix apps/web run build
uv run --frozen python -m services.api.storage
```

Confirm the native decoder:
```sh
uv run --frozen python -c "import eccodes; print(eccodes.codes_get_api_version())"
```
The locked Linux environment uses native ecCodes2.50.0. If a native-platform decoder fails, use the verified Linux/WSL route; disabling TLS or substituting synthetic weather does not solve installation problems.

## 3. Start and stop

From the checkout:
```sh
uv run --frozen python -m scripts.dev
```

Open `http://127.0.0.1:8000` **on the computer running the command**. This is the local application address, not a public cloud preview. Keep the terminal open. Ctrl+C stops both API and worker cleanly. Restart with the same command to reopen saved work.

If8000 is occupied:
```sh
uv run --frozen python -m scripts.dev --port 8002
```
Open the matching local port. Do not start duplicate workers against the same data directory.

The API health response at `/api/health` must show database statusok and worker state`ready`. The UI serves from the same process. `restart_required` means scientific source/dependencies changed: stop and restart **both** services. Rebuild the client after frontend changes. Rebuilding during a browser test can invalidate its loaded assets.

## 4. Choose the data directory

Default state lives in the checkout's ignored `data/` directory: SQLite, cached raw forecasts and saved results. It is not uploaded by Git.

For another directory, copy `.env.example` to `.env`, uncomment `STRATOS_DATA_DIR` and set an **absolute local path**. Start with:
```sh
uv run --frozen --env-file .env python -m scripts.dev
```
The launcher passes the same environment to API and worker. Use the same environment file for backup commands. `.env` is not loaded automatically when `--env-file` is omitted.

`mission.yaml` is a first-start template. Once a workspace has a mission, changing that file does not overwrite its immutable database revisions. Use Plan, YAML import/export or a separate data directory for another workspace.

## 5. First offline test

1. Start the app and wait for the initial synthetic calculation to finish. The map uses local Natural Earth geography.
2. Open **Simulate → Trajectory**. Scrub the timeline; arrow keys/Home/End work. Check altitude, wind, pressure, temperature and exact UTC brackets.
3. The watermark **DEMO DATA** identifies synthetic winds. It is a functioning constant-wind reference calculation, not an observation or live flight.
4. Open **Weather inputs → Inspect cached forecast**. Startup imports checksummed **dated NOAA references from27 October2026**, including06UTC and12UTC cycles with a common18–19UTC window. It demonstrates the decoder/interpolator offline; it is not a current operational forecast on later days.
For a complete offline NOAA calculation, select that bundled forecast in Plan, set initial and target altitude to12,500m and float duration to1h, and retain its valid-time start. This is a dated float-only reference, not an attainable-altitude or current-weather claim.

5. In Plan, change inputs, save a revision and run. In Analyze, reopen results. Export complete JSON/CSV/GeoJSON and mission YAML. Refresh/restart and confirm the same saved manifest/hash.

## 6. Configure a mission

All launch and weather times are **UTC**, independent of your browser timezone. Convert the intended local launch time before entering it.

- Keep modeDEMO for simulations. Other mission modes are schema-representable but not supported for P1 calculations.
- Use solver schema2 for new studies. Schema1 preserves older numerical replay.
- Enter coordinates and geometric MSL heights. Ground elevation is an assumption until surveyed; coarse GFS terrain is a weather boundary, not a site survey or recovery map.
- Initial altitude equal to target altitude gives a float-only study. Otherwise ascent rate prescribes the climb. Float duration, ascent and optional descent must fit the72h total-profile cap.
- Payload mass is recorded but does not change this L0 model. Lift, leakage, burst, thermal behavior and power endurance are not calculated.
- Default numerical step is30s; default saved snapshots are120s. Changing saved cadence does not change the numerical path. Use smaller numerical steps for convergence checks.
- Descent ends at configured flat ground, not terrain-derived landing coordinates.

Continuous fields accept fractional values; integer numerical controls remain restricted. Save completion preserves edits made while a request was pending. Each run stores an exact immutable revision; viewing an archive does not silently replace the editable plan. Use **Load these exact inputs** explicitly.

## 7. Use a new real GFS forecast

1. Open **Simulate → Weather inputs** and discover available cycles, or enter an exact published00/06/12/18UTC initialization. Initialization is not the exact publication timestamp.
2. Choose a cropped ROI and consecutive hourly leads within0–120. A download window spans at most72h/73files. Ensure the **entire** planned profile fits those valid times.
3. Example: a launch at initialization+6h with48h prescribed duration needs leads6–54. A72h duration at that start needs6–78. These are horizon examples, not recommended launch conditions.
4. Estimate first. The UI shows packed/array estimates and a pacing lower bound. NOAA requires10s between automated filter fetches, including retries. A73-file window requires at least12min of pacing alone; network/decode time is additional. Downloads have a30min job budget and retain verified files for explicit retry.
5. Download, select the dataset in Plan, review proposed start/profile and run. The API rejects invalid initial terrain/altitude, time look-ahead, missing inputs and out-of-volume sampling.
6. Optional adjacent acquisition stays on the exact same cycle/member/grid, compares overlap and is limited to16 source segments and128MiB verified inputs. The default limit is8segments/64MiB; cached bytes also count. A long study can correctly exhaust these limits. Missing data/quota exhaustion is a failure, never a successful partial forecast.

The supplied80m example is below coarse GFS terrain and is correctly rejected with NOAA at that point. Use an explicitly labelled float-only study to test the pipeline; do not invent a surveyed ground elevation or lift capability to suppress the error.

The managed cloud currently has the official NOAA domains saved in a draft; new discovery/download requires that policy to be applied/published. A proxy error is shown explicitly. On your local installation, normal Internet access to `nomads.ncep.noaa.gov` is required. Cached inputs remain usable, and no automatic provider/cycle substitution occurs.

## 8. Inspect weather and compare studies

**Weather inputs:** choose valid UTC and either a geometric-altitude slice or a retained pressure surface. Pressure planes use their actual varying model heights; select the level in hPa, while exports retain Pa. Wind-speed/temperature contours mask invalid cells and show native versus display sampling. Their displayed range belongs to sampled values, not a guaranteed native-grid global extreme. Click the map for a vertical column and point readout. Export the exact inspected slice with source/code/content hashes.

For a controlled offline forecast-cycle example, save two1h float-only studies at12,500m, both starting27 October2026 18UTC. Select the bundled06UTC/18–19UTC window for one and12UTC/18–19UTC for the other; keep all other inputs equal. These past reference forecasts demonstrate sensitivity between cycles.

**Analyze → Compare saved studies:** choose reference/candidate, elapsed-time or absolute-UTC alignment and a bounded sample count. Compare over their shared interval, scrub the separation chart and inspect changed inputs. Paths interpolate saved snapshots; the tool does not rerun weather or physics. Horizontal separation and height differences express scenario sensitivity between uncalibrated predictions. Export the comparison and retain both original simulation exports for reproduction.

Neither comparison spread nor a successful trajectory supplies measured forecast accuracy, a landing-confidence region or launch-success probability.

## 9. Back up, verify and restore

Finish/cancel queued or running jobs first. Choose a **new** backup directory outside live data:
```sh
uv run --frozen python -m scripts.backup --output /absolute/path/stratos-backup-001
uv run --frozen python -m scripts.verify_backup --backup /absolute/path/stratos-backup-001
```
If using `.env`, include `--env-file .env` after `uv run --frozen` in the backup command too.

Backup validates database/result identities and all required raw forecasts. A verified database can reconstruct a missing redundant result JSON; missing/corrupt raw weather cannot be invented. Failed snapshots are marked explicitly.

Restore into a **new, nonexistent** directory:
```sh
uv run --frozen python -m scripts.verify_backup --backup /absolute/path/stratos-backup-001 --restore-to /absolute/path/stratos-restored
```
Then set `STRATOS_DATA_DIR` to that restored directory before starting both services. Verification checks before and after copying and refuses overwrite. Keep the original archive closed/unchanged; do not run the app directly inside your only backup. Copying only a live SQLite main file without its WAL is not a consistent backup.

Keep raw caches referenced by saved studies. To reclaim a whole historical workspace, first verify/archive it, then use another data directory and import the desired mission YAML. Automatic eviction and numeric checkpoint continuation remain deferred.

## 10. Test and update

Backend checks and exact retained real-data replay:
```sh
uv run --frozen pytest -q
uv run --frozen python -m scripts.reproduce
```
Optional browser checks:
```sh
cd apps/web
npx playwright install --with-deps chromium
npm run test:e2e
```
Browser tests own a temporary database and loopback port8001, leaving planning data on8000 untouched. `STRATOS_E2E_PORT` selects another test port. `STRATOS_E2E_DATA_DIR` may specify a dedicated test-only directory. In the prepared cloud, use `STRATOS_CHROMIUM=/usr/bin/chromium` instead of downloading another browser. Native Windows qualification is still open.

To update: create a verified backup, stop the launcher, run `git pull --ff-only`, repeat installation/build, and restart. Existing data is preserved. Do not reset or overwrite your own tracked edits to force an update.

See `PROJECT_STATUS.md`, `DECISIONS.md` and `docs/P1_SECOND_REVIEW.md` for exact evidence and remaining work. Full72h, native Windows, an independent8GB host and hardware/flight calibration remain unqualified. The long endurance resource procedure is Linux-only; it must not report macOS RSS bytes as Linux KiB.

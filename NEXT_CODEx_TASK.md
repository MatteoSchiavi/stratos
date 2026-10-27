# Next vertical slice: real72h qualification (remaining P1)

## Goal
Measure one complete72h real-GFS prescribed-profile study and document its resource/coverage limits, without extrapolation or a flight-readiness claim. Pressure surfaces, contours, verified archive restore and UI race protection are already implemented. Do not begin P2–P7.

## Work
1. Read PROJECT_STATUS.md, DECISIONS.md and docs/P1_SECOND_REVIEW.md. Use the existing checkout. Confirm NOAA domain policy/service access; cached fixtures are sufficient for regression but must not be presented as a new72h forecast.
2. Select exact cycle, prospective start and72h valid-time window. Hourly leads may extend to120, but a crop window spans at most72h/73files. Initialization is not publication. Respect NOAA's10s request spacing and30min download budget; retain verified partial files for explicit retry.
3. Choose a crop within the384MiB decoded estimate and512MiB cache bound. Run the actual API/worker with explicit expansion/input quotas. If16 segments or15min cannot complete the route, record that limit; evaluate measured evidence before changing budgets. Never report a partial track as successful.
4. Repeat from verified cache, measure process memory/wall time and test API/UI responsiveness. Check timestep convergence and saved/reopened/exported hashes. Native Windows and an independent8GB host remain separate qualification gates.
5. Create and verify a quiet-state backup and restore into a new directory. Retain exact inputs/source identity, update status and choose one subsequent slice. Full3D weather volume, automatic disk eviction, SSE and numeric checkpoints remain open.

## Checks
```sh
export UV_CACHE_DIR=/workspace/stratos/.cache/uv
uv run --frozen ruff check packages services scripts tests
uv run --frozen ruff format --check packages services scripts tests
uv run --frozen mypy packages services --explicit-package-bases
uv run --frozen pytest -q
uv run --frozen python -m scripts.reproduce
cd apps/web
npm ci
npm run lint
npm run build
STRATOS_CHROMIUM=/usr/bin/chromium npm run test:e2e
```
Restart both services after scientific Python/dependency changes. Never rebuild the client during browser verification. The native Windows,8GB-host and launch/hardware gates are not established by a Linux process limit.

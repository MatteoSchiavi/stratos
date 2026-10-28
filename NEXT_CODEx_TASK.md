# Next vertical slice: receiver-contact evidence and packet replay

## Goal
Replace at least one assumed contact/loss input with traceable receiver evidence, without introducing a live transmitter or claiming RF/power qualification. Keep P0/P1 and the completed telemetry tools working; do not implement every remaining phase.

## Work
1. Read PROJECT_STATUS.md, DECISIONS.md, docs/TELEMETRY_AUDIT.md, docs/TELEMETRY_PROTOCOL.md and docs/TELEMETRY_VERIFICATION.md.
2. Define/import a small bounded receiver-evidence format carrying receiver identity, raw uplink bytes, UTC receive time, regional frequency/DR, source/licence and external MIC-verification status. Preserve every raw packet/copy. Use actual supplied/permitted receiver data when available; otherwise label a generated fixture synthetic and leave measured qualification open.
3. Replay the versioned codec and deduplicate by session/time/sequence plus receiver-copy identity, respecting emergency sequence/time quantization. Never infer authenticated transport from CRC or decoder success. Compare entered contact windows against observed decodes; non-reception outside a logged observation interval is unknown, not a measured failed link.
4. Add a compact evidence-import/replay screen linked to recovery inputs. Expose data gaps, unsupported settings and source hashes. Keep radio/network transmission disabled. No Gaussian coverage probabilities, unverified gateway compatibility or look-ahead leakage.
5. Run focused scientific/API/browser regressions, exercise a real available input, verify backup/restore of new records, and update exact evidence/remaining limitations.

## Remaining separate gates
Full real72h NOAA study, independent8GB host, native Windows, authoritative regional/channel/airborne permissions, measured compatible receiver/antenna/link margin, cold/ESR/power qualification and flash journal/firmware testing remain open. The synthetic72h scheduler stress case does not close these gates.

## Checks
```sh
export UV_CACHE_DIR=/workspace/stratos/.cache/uv
uv run --frozen ruff check packages services scripts tests
uv run --frozen ruff format --check packages services scripts tests
uv run --frozen mypy packages services --explicit-package-bases
uv run --frozen pytest -q
uv run --frozen python -m scripts.reproduce
uv run --frozen python -m scripts.reproduce_telemetry --output /absolute/new/evidence-directory
cd apps/web
npm run lint
npm run build
STRATOS_CHROMIUM=/usr/bin/chromium npm run test:e2e
```
Restart API and worker after scientific source/dependency changes. Never rebuild while browser tests run. Keep test data isolated from planning state.

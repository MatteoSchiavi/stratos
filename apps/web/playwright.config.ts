import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Verification owns its own API, worker and data directory. It must never
// reuse the operator's planning database merely because port8000 is healthy.
const port = Number(process.env.STRATOS_E2E_PORT ?? "8001");
if (!Number.isInteger(port) || port < 1024 || port > 65535)
  throw new Error("STRATOS_E2E_PORT must be an integer1024–65535");
const baseURL = `http://127.0.0.1:${port}`;
const data =
  process.env.STRATOS_E2E_DATA_DIR ??
  mkdtempSync(join(tmpdir(), "stratos-e2e-"));
const python =
  process.platform === "win32"
    ? '".venv\\Scripts\\python.exe"'
    : ".venv/bin/python";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: {
    baseURL,
    viewport: { width: 1440, height: 1100 },
    launchOptions: {
      executablePath: process.env.STRATOS_CHROMIUM || undefined,
      args: [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
      ],
    },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `${python} -m scripts.dev --port ${port}`,
    cwd: "../..",
    env: { STRATOS_DATA_DIR: data },
    url: baseURL + "/api/health",
    reuseExistingServer: false,
    timeout: 60000,
  },
});

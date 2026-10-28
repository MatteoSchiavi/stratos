import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";

test("offline map, timeline, boundaries and visible provenance", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  const external: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("**/*", (route) => {
    const u = new URL(route.request().url());
    if (u.protocol.startsWith("http") && u.hostname !== "127.0.0.1") {
      external.push(u.hostname);
      return route.abort();
    }
    return route.continue();
  });
  const existing = await (await request.get("/api/simulations")).json();
  const demo = existing.find(
    (r: { weather_provider: string }) => r.weather_provider === "SYNTHETIC",
  );
  await page.goto(demo ? `/?simulation=${demo.id}` : "/");
  await expect(
    page.getByRole("heading", { name: "Trajectory workspace" }),
  ).toBeVisible();
  await expect(page.locator('[data-map-ready="true"]')).toBeVisible({
    timeout: 30000,
  });
  await expect(page.getByText("DEMO DATA", { exact: false })).toBeVisible();
  await expect(page.locator(".map-error")).toHaveCount(0);
  const first = await page.locator(".coordinates").innerText();
  await page.getByRole("slider", { name: "Trajectory timeline" }).focus();
  await page.keyboard.press("End");
  await expect(page.locator(".coordinates")).not.toHaveText(first);
  await expect(page.locator(".inspector-altitude")).toContainText("12.50");
  await page.getByRole("button", { name: "Toggle country boundaries" }).click();
  await expect(
    page.getByRole("button", { name: "Toggle country boundaries" }),
  ).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "Toggle country boundaries" }).click();
  await page.getByRole("button", { name: "Fit predicted track" }).click();
  await page.getByRole("slider", { name: "Trajectory timeline" }).focus();
  await page.keyboard.press("ArrowLeft");
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
  if (process.env.STRATOS_CAPTURE) {
    await mkdir("../../docs/screenshots", { recursive: true });
    await page.screenshot({
      path: "../../docs/screenshots/trajectory-desktop.png",
      fullPage: true,
    });
  }
});

test("edit mission, compute, save, export, refresh and reopen identical results", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Plan", exact: true }).click();
  await page.getByLabel("Float duration · h", { exact: true }).fill("0.1");
  await page
    .getByLabel("Initial altitude · m MSL", { exact: true })
    .fill("12500");
  await page
    .getByRole("button", { name: "Run simulation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Trajectory workspace" }),
  ).toBeVisible();
  await expect(page.locator(".metric").nth(2)).toContainText("0h 6m", {
    timeout: 30000,
  });
  await page.getByRole("tab", { name: "Run evidence" }).click();
  const hash = await page.locator(".evidence-values dd").first().innerText();
  const id = new URL(page.url()).searchParams.get("simulation");
  expect(id).toBeTruthy();
  const response = await request.get(`/api/simulations/${id}/export`);
  expect(response.ok()).toBeTruthy();
  const result = await response.json();
  expect(result.manifest.output_sha256).toBe(hash);
  expect(result.samples.length).toBeGreaterThan(2);
  await page.reload();
  await page.getByRole("tab", { name: "Run evidence" }).click();
  await expect(page.locator(".evidence-values dd").first()).toHaveText(hash);
  await page.getByRole("button", { name: "Analyze", exact: true }).click();
  await page.locator(".archive-row").first().click();
  await page.getByRole("tab", { name: "Run evidence" }).click();
  await expect(page.locator(".evidence-values dd").first()).toHaveText(hash);
  // Restore original mission configuration without altering its saved evidence.
  const missions = await (await request.get("/api/missions")).json();
  const rev = await (
    await request.get(`/api/revisions/${missions[0].latest_revision_id}`)
  ).json();
  rev.config.flight.initial_geometric_m = 80;
  rev.config.flight.float_duration_hours = 6;
  expect(
    (
      await request.post(`/api/missions/${rev.config.id}/revisions`, {
        data: rev.config,
      })
    ).ok(),
  ).toBeTruthy();
});

test("NOAA unavailable is an explicit error, and download requires estimate", async ({
  page,
}) => {
  await page.route("**/api/weather/runs", (route) =>
    route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({
        detail:
          "NOAA discovery unavailable — explicit browser-test failure response; no synthetic fallback.",
      }),
    }),
  );
  await page.goto("/");
  await page.getByRole("tab", { name: "Weather inputs" }).click();
  await page
    .getByRole("tab", { name: "Acquire new forecast", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Download selected subset" }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Estimate download", exact: true })
    .click();
  await expect(page.locator(".download-estimate")).toContainText("MiB");
  await expect(
    page.getByRole("button", { name: "Download selected subset" }),
  ).toBeEnabled();
  await page.getByLabel("Last forecast lead · h").fill("12");
  await expect(
    page.getByRole("button", { name: "Download selected subset" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Discover published cycles" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "NOAA discovery unavailable",
  );
});

test("mobile layout stays within viewport and remains keyboard accessible", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator('[data-map-ready="true"]')).toBeVisible({
    timeout: 30000,
  });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.getByRole("slider", { name: "Trajectory timeline" }).focus();
  await page.keyboard.press("End");
  await expect(page.locator(".inspector-altitude")).toContainText("12.50");
  if (process.env.STRATOS_CAPTURE)
    await page.screenshot({
      path: "../../docs/screenshots/trajectory-mobile.png",
      fullPage: true,
    });
  await page.getByRole("button", { name: "Plan", exact: true }).click();
  await expect(page.getByLabel("Mission name")).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

test("inspect a real cached NOAA wind field and pressure-level column offline", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Weather inputs" }).click();
  await page
    .getByRole("button", { name: "Inspect cached forecast", exact: true })
    .click();
  await expect(page.locator(".weather-explorer .profile-table")).toBeVisible({
    timeout: 30000,
  });
  await expect(page.locator(".weather-explorer .notice")).toContainText(
    "FORECAST, NOT MEASURED",
  );
  expect(await page.locator(".profile-table tbody tr").count()).toBeGreaterThan(
    15,
  );
  await expect(
    page.locator('.weather-explorer [data-map-ready="true"]'),
  ).toBeVisible();
  const first = await page.locator(".profile-heading").innerText();
  const map = page.locator(".weather-explorer .map-canvas");
  const bounds = await map.boundingBox();
  await map.click({
    position: { x: bounds!.width / 2, y: bounds!.height / 2 },
  });
  await expect(page.locator(".profile-heading")).not.toHaveText(first, {
    timeout: 15000,
  });
});

test("oversized weather estimates cannot be submitted", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Weather inputs" }).click();
  await page
    .getByRole("tab", { name: "Acquire new forecast", exact: true })
    .click();
  await page.getByLabel("West boundary · °", { exact: true }).fill("0");
  await page.getByLabel("East boundary · °", { exact: true }).fill("60");
  await page.getByLabel("South boundary · °", { exact: true }).fill("0");
  await page.getByLabel("North boundary · °", { exact: true }).fill("40");
  await page
    .getByRole("button", { name: "Estimate download", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "exceeds the declared memory or cache budget",
  );
  await expect(
    page.getByRole("button", { name: "Download selected subset" }),
  ).toBeDisabled();
});

test("pressure surfaces, temperature contours and exact inspected-slice export", async ({
  page,
}) => {
  test.setTimeout(90000);
  await page.goto("/");
  await page.getByRole("tab", { name: "Weather inputs" }).click();
  await page
    .getByLabel("Weather slice plane", { exact: true })
    .selectOption("isobaric");
  await page
    .getByLabel("Explorer pressure surface · hPa", { exact: true })
    .selectOption("50000");
  await page
    .getByLabel("Contour variable", { exact: true })
    .selectOption("temperature");
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/weather/explore") &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Inspect cached forecast", exact: true })
    .click();
  const data = await (await response).json();
  expect(data.plane.kind).toBe("isobaric");
  expect(data.point.pressure_pa).toBe(50000);
  expect(data.contours.features.length).toBeGreaterThan(0);
  expect(data.scalar_field.units).toBe("K");
  await expect(
    page.locator('.weather-explorer [data-map-ready="true"]'),
  ).toBeVisible({ timeout: 30000 });
  await expect(page.getByLabel("Forecast contour legend")).toContainText(
    "Temperature contours",
  );
  await expect(page.locator(".weather-explorer .notice")).toContainText(
    "500 hPa surface",
  );
  await expect(
    page.locator('.profile-table tr[data-selected="true"]'),
  ).toHaveCount(1);
  await expect(page.getByLabel("Selected forecast sample")).toContainText(
    "500.0 hPa",
  );
  const downloadEvent = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export inspected slice", exact: true })
    .click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toContain(
    data.inspection_sha256.slice(0, 12),
  );
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  expect(JSON.parse(Buffer.concat(chunks).toString())).toEqual(data);
  await page
    .getByLabel("Explorer pressure surface · hPa", { exact: true })
    .selectOption("20000");
  await expect(page.locator(".slice-pending")).toContainText(
    "last inspected slice",
  );
  await expect(page.locator(".weather-explorer .notice")).toContainText(
    "500 hPa surface",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

test("an older forecast response cannot overwrite a newly selected dataset", async ({
  page,
}) => {
  test.setTimeout(90000);
  await page.goto("/");
  await page.getByRole("tab", { name: "Weather inputs" }).click();
  const selector = page.getByLabel("Explorer forecast", { exact: true });
  const options = await selector
    .locator("option")
    .evaluateAll((nodes) => nodes.map((n) => (n as HTMLOptionElement).value));
  expect(options.length).toBeGreaterThan(0);
  // Hold the genuine backend response, switch datasets, then deliver it late.
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let captured!: () => void;
  const fetched = new Promise<void>((resolve) => {
    captured = resolve;
  });
  let delivered!: () => void;
  const completed = new Promise<void>((resolve) => {
    delivered = resolve;
  });
  await page.route(
    "**/api/weather/explore",
    async (route) => {
      const response = await route.fetch();
      captured();
      await gate;
      await route.fulfill({ response });
      delivered();
    },
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Inspect cached forecast", exact: true })
    .click();
  await fetched;
  // Even a same-dataset reselection invalidates the old inspection token.
  await selector.selectOption(options.length > 1 ? options[1] : options[0]);
  release();
  await completed;
  await expect(page.locator(".weather-explorer .profile-table")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Inspect cached forecast", exact: true })
    .click();
  await expect(page.locator(".weather-explorer .profile-table")).toBeVisible({
    timeout: 30000,
  });
});

test("a delayed estimate stays tied to its original download inputs", async ({
  page,
}) => {
  test.setTimeout(90000);
  await page.goto("/");
  await page.getByRole("tab", { name: "Weather inputs" }).click();
  await page
    .getByRole("tab", { name: "Acquire new forecast", exact: true })
    .click();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let fetched!: () => void;
  const captured = new Promise<void>((resolve) => {
    fetched = resolve;
  });
  await page.route(
    "**/api/weather/estimate",
    async (route) => {
      const response = await route.fetch();
      fetched();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Estimate download", exact: true })
    .click();
  await captured;
  await page.getByLabel("Last forecast lead · h", { exact: true }).fill("12");
  release();
  await expect(
    page.getByRole("button", { name: "Estimate download", exact: true }),
  ).toBeEnabled();
  await expect(page.locator(".download-estimate")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Download selected subset", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Estimate download", exact: true })
    .click();
  await expect(page.locator(".download-estimate")).toContainText("13 files");
  await expect(
    page.getByRole("button", { name: "Download selected subset", exact: true }),
  ).toBeEnabled();
});

test("a delayed revision save preserves edits made while it was in flight", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const missions = await (await request.get("/api/missions")).json();
  const original = await (
    await request.get(`/api/revisions/${missions[0].latest_revision_id}`)
  ).json();
  try {
    await page.goto("/");
    await page.getByRole("button", { name: "Plan", exact: true }).click();
    await expect(page.locator("form input:invalid")).toHaveCount(0);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let fetched!: () => void;
    const captured = new Promise<void>((resolve) => {
      fetched = resolve;
    });
    await page.route(
      `**/api/missions/${original.config.id}/revisions`,
      async (route) => {
        const response = await route.fetch();
        fetched();
        await gate;
        await route.fulfill({ response });
      },
      { times: 1 },
    );
    await page
      .getByLabel("Mission name", { exact: true })
      .fill("Saved revision label");
    await page.getByLabel("Float duration · h", { exact: true }).fill("0.125");
    await page.getByLabel("Latitude · °N", { exact: true }).fill("45.050123");
    const invalid = await page
      .locator("form input:invalid")
      .evaluateAll((nodes) => nodes.map((n) => n.getAttribute("aria-label")));
    expect(invalid).toEqual([]);
    await page
      .getByRole("button", { name: "Save mission revision", exact: true })
      .click();
    await captured;
    const savedMission = (await (await request.get("/api/missions")).json())[0];
    const savedRevision = await (
      await request.get(`/api/revisions/${savedMission.latest_revision_id}`)
    ).json();
    expect(savedRevision.config.name).toBe("Saved revision label");
    expect(savedRevision.config.launch.latitude_deg).toBe(45.050123);
    expect(savedRevision.config.flight.float_duration_hours).toBe(0.125);
    await page
      .getByLabel("Mission name", { exact: true })
      .fill("Newer unsaved mission edit");
    release();
    await expect(
      page.getByRole("button", { name: "Save mission revision", exact: true }),
    ).toBeEnabled();
    await expect(page.getByLabel("Mission name", { exact: true })).toHaveValue(
      "Newer unsaved mission edit",
    );
  } finally {
    const restored = await request.post(
      `/api/missions/${original.config.id}/revisions`,
      { data: original.config },
    );
    expect(restored.ok()).toBeTruthy();
  }
});

test("compare two saved predictions, inspect aligned paths and export source hashes", async ({
  page,
}) => {
  test.setTimeout(90000);
  await page.goto("/");
  await page.getByRole("button", { name: "Analyze", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Saved-study comparison",
    exact: true,
  });
  // The preceding workflow produced a second genuine worker result in this isolated workspace.
  const responseEvent = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/simulations/compare") &&
      r.request().method() === "POST",
  );
  await panel
    .getByRole("button", { name: "Compare studies", exact: true })
    .click();
  const response = await responseEvent;
  expect(response.ok()).toBeTruthy();
  const result = await response.json();
  expect(result.points.length).toBe(241);
  expect(result.sources.length).toBe(2);
  expect(
    result.metrics.maximum_absolute_sampled_height_difference_m,
  ).toBeGreaterThan(0);
  await expect(panel.locator('[data-map-ready="true"]')).toHaveAttribute(
    "data-secondary-sample-count",
    "241",
    { timeout: 30000 },
  );
  await expect(
    panel.getByLabel("Compared configuration differences", { exact: true }),
  ).toContainText("flight.initial_geometric_m");
  const first = await panel.locator(".comparison-times").innerText();
  await panel
    .getByRole("slider", { name: "Comparison timeline", exact: true })
    .focus();
  await page.keyboard.press("End");
  await expect(panel.locator(".comparison-times")).not.toHaveText(first);
  await expect(panel.locator(".notice")).toContainText(
    "MODELED SCENARIO SENSITIVITY",
  );
  const downloadEvent = page.waitForEvent("download");
  await panel
    .getByRole("button", { name: "Export comparison", exact: true })
    .click();
  const download = await downloadEvent;
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  expect(JSON.parse(Buffer.concat(chunks).toString())).toEqual(result);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

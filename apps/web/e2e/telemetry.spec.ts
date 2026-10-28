import { test, expect } from "@playwright/test";

test("regional packet validation, real codec decode and batching tradeoffs", async ({
  page,
}) => {
  await page.goto("/?view=telemetry");
  await page
    .getByRole("tab", { name: "1 · Packet & airtime", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Encode & validate", exact: true })
    .click();
  const result = page.getByLabel("Packet validation result", { exact: true });
  await expect(result).toContainText("24 bytes");
  await expect(result).toContainText("Fits selected profile");
  await page.getByLabel("Radio region", { exact: true }).selectOption("US915");
  await expect(result).toContainText("Inputs changed");
  await page
    .getByRole("button", { name: "Encode & validate", exact: true })
    .click();
  await expect(result).toContainText("Does not fit selected profile");
  await expect(result).toContainText("exceeds 11 B");
  await page
    .getByLabel("Packet family", { exact: true })
    .selectOption("EMERGENCY");
  await page
    .getByRole("button", { name: "Encode & validate", exact: true })
    .click();
  await expect(result).toContainText("11 bytes");
  await expect(result).toContainText("Fits selected profile");
  await expect(result).toContainText("external LoRaWAN MIC required");
  await page.getByText("Decode a received packet", { exact: true }).click();
  await page
    .getByRole("button", { name: "Decode packet", exact: true })
    .click();
  await expect(page.locator("pre").last()).toContainText('"sequence_bits": 8');
  await page.getByLabel("Radio region", { exact: true }).selectOption("EU868");
  await page.getByText("Batching trade study", { exact: true }).click();
  await page
    .getByRole("button", { name: "Compare batch sizes", exact: true })
    .click();
  await expect(
    page.getByRole("columnheader", { name: "Lost / failure", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".engineering-table tbody tr")).toHaveCount(16);
  await page.getByLabel("Available airtime · s", { exact: true }).fill("10");
  await expect(
    page.getByText(
      "Inputs changed. Compare again to update this trade study.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

test("recovery workflow uses the worker, preserves edits, reopens and exports exact evidence", async ({
  page,
}) => {
  await page.goto("/?view=telemetry");
  await page
    .getByLabel("Fresh tracking interval · s", { exact: true })
    .fill("240");
  await page.getByRole("button", { name: "Plan", exact: true }).click();
  await page.getByRole("button", { name: "Telemetry", exact: true }).click();
  await expect(
    page.getByLabel("Fresh tracking interval · s", { exact: true }),
  ).toHaveValue("240");
  await page
    .getByRole("button", { name: "Calculate recovery", exact: true })
    .click();
  const budget = page.getByLabel("Recovery results", { exact: true });
  await expect(
    budget.getByRole("heading", { name: "Recovery budget", exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await expect(page).toHaveURL(/recovery=/);
  await expect(
    page.getByRole("img", {
      name: "Recovery backlog and received records over mission time",
      exact: true,
    }),
  ).toBeVisible();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export study", exact: true }).click();
  const download = await downloadEvent;
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  const data = JSON.parse(Buffer.concat(chunks).toString());
  expect(data.configuration.fresh_interval_s).toBe(240);
  expect(data.output.metrics.transmissions).toBeGreaterThan(0);
  expect(Math.abs(data.output.metrics.energy_balance_residual_j)).toBeLessThan(
    1e-8,
  );
  for (const event of data.output.events)
    expect(event.decision).toMatch(/fresh_position_due|priority_history/);
  await page.locator(".study-inputs > summary").click();
  await page.getByLabel("Study duration · s", { exact: true }).fill("1800");
  await expect(budget).toContainText("Inputs differ from this saved study");
  await page.reload();
  await expect(budget).toContainText(data.sha256);
  await page.getByText("Why the scheduler waited", { exact: true }).click();
  await expect(budget).toContainText("no compatible contact");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

test("lossless archive download/import verifies original records and rejects corruption", async ({
  page,
}) => {
  await page.goto("/?view=telemetry");
  await page
    .getByRole("tab", { name: "3 · Archive & summaries", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Create & verify archive", exact: true })
    .click();
  await expect(
    page.getByLabel("Archive verification result", { exact: true }),
  ).toContainText("Lossless round trip verified");
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download .stla", exact: true }).click();
  const stream = await (await downloadEvent).createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  const raw = Buffer.concat(chunks);
  expect(raw.subarray(0, 5).toString("hex")).toBe("53544c4101");
  const restored = page.waitForEvent("download");
  await page
    .getByLabel("Import binary archive", { exact: true })
    .setInputFiles({
      name: "verified.stla",
      mimeType: "application/octet-stream",
      buffer: raw,
    });
  const decodedStream = await (await restored).createReadStream();
  const decoded: Buffer[] = [];
  for await (const chunk of decodedStream!) decoded.push(Buffer.from(chunk));
  const source = JSON.parse(Buffer.concat(decoded).toString());
  expect(source.observations).toHaveLength(61);
  expect(source.context.epoch_utc).toContain("2026-10-27");
  await expect(page.getByRole("status")).toContainText(
    "Verified and decoded 61 original records",
  );
  const damaged = Buffer.from(raw);
  damaged[damaged.length - 1] ^= 1;
  await page
    .getByLabel("Import binary archive", { exact: true })
    .setInputFiles({
      name: "corrupt.stla",
      mimeType: "application/octet-stream",
      buffer: damaged,
    });
  await expect(page.getByRole("alert")).toContainText(
    /Corrupt|mismatch|invalid/i,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

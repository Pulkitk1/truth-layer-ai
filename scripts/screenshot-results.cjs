/* eslint-disable @typescript-eslint/no-require-imports */
// Visual smoke test: opens /results for a processed document in Edge at desktop and mobile widths,
// checks for horizontal overflow and browser errors, downloads the PDF report, and saves screenshots.
// Needs both servers running and a file_id whose claims were extracted, searched and verified.
const { createRequire } = require("module");
const req = createRequire(require("path").join(__dirname, "..", "package.json"));
const { chromium } = req("playwright-core");
const fs = require("fs");

const id = process.argv[2];
// The document's access token (returned once by /api/upload). Pass it as the 4th argument or in TL_TOKEN.
const token = process.argv[4] || process.env.TL_TOKEN || "";
// TL_NO_AI=1 answers the dashboard's automatic AI-summary request with the stored report, so no Groq credits are used.
const noAi = process.env.TL_NO_AI === "1";
if (!id) {
  console.error("Usage: node scripts/screenshot-results.cjs <file_id> [out_dir] [access_token]");
  process.exit(1);
}
const out = process.argv[3] || "screenshots";
fs.mkdirSync(out, { recursive: true });

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const errors = [];
  for (const [name, w, h] of [["desktop", 1366, 900], ["mobile", 390, 844]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    const page = await ctx.newPage();
    if (token) {
      await page.addInitScript(
        ([fid, tok]) => window.localStorage.setItem("truthlayer:access-tokens", JSON.stringify({ [fid]: tok })),
        [id, token],
      );
    }
    if (noAi) {
      await page.route("**/api/reports/*/summary*", async (route) => {
        const plain = route.request().url().replace(/\/summary.*$/, "");
        await route.fulfill({ response: await route.fetch({ url: plain, method: "GET" }) });
      });
    }
    page.on("pageerror", (e) => errors.push(`${name} pageerror: ${e.message}`));
    page.on("console", (m) => m.type() === "error" && errors.push(`${name} console: ${m.text()}`));
    await page.goto(`http://localhost:3000/results?file=${id}`, { waitUntil: "networkidle" });
    await page.waitForSelector('[data-testid="document-name"]', { timeout: 30000 });
    await page.waitForTimeout(6000); // let the AI narrative arrive
    await page.screenshot({ path: `${out}/${name}-top.png`, fullPage: false });
    await page.screenshot({ path: `${out}/${name}-full.png`, fullPage: true });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    console.log(name, "horizontal overflow:", overflow);

    // the PDF report button must be present and, on desktop, really download a PDF
    const pdfButton = page.getByRole("button", { name: /Download PDF Report/ });
    console.log(name, "PDF button enabled:", await pdfButton.isEnabled());
    if (name === "desktop") {
      const [download] = await Promise.all([page.waitForEvent("download", { timeout: 60000 }), pdfButton.click()]);
      const file = `${out}/${download.suggestedFilename()}`;
      await download.saveAs(file);
      const header = fs.readFileSync(file).subarray(0, 5).toString();
      console.log("downloaded:", download.suggestedFilename(), fs.statSync(file).size, "bytes, starts with", header);
      if (header !== "%PDF-") throw new Error("The downloaded file is not a PDF");
    }

    // click the Verified card, then open a claim
    await page.getByRole("button", { name: /^Verified/ }).first().click();
    const rows = await page.locator('[data-testid^="row-"]').count();
    console.log(name, "rows after clicking Verified:", rows);
    await page.locator('[data-testid^="row-"]').first().click();
    await page.waitForSelector('aside[aria-label="Claim details"]');
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${out}/${name}-details.png`, fullPage: false });
    await ctx.close();
  }
  console.log("browser errors:", errors.length ? errors : "none");
  await browser.close();
})().catch((e) => {
  console.error("FAILED", e.message);
  process.exit(1);
});

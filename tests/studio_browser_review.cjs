// Browser regression against the local studio; API responses are controlled, no inference runs.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const root = path.resolve(__dirname, "..");
const output = path.join(root, ".publishing", "review-browser");
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.EDGE_EXE || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = []; page.on("pageerror", error => errors.push(error.message));
    const jobs = [];
    let serial = 0, cropGate = null, cropStarted = false;
    const reference = (name = "prepared.wav") => ({ path: name, name, seconds: 2, start: 0, end: 2, waveform: [] });
    await page.route("**/studio/app.js", route => route.fulfill({ contentType: "text/javascript", body: fs.readFileSync(path.join(root, "studio/app.js"), "utf8") }));
    await page.route("**/api/**", async route => {
      const request = route.request(), url = new URL(request.url());
      let value = {};
      if (url.pathname === "/api/voices") value = { ...JSON.parse(fs.readFileSync(path.join(root, "ming_t8/assets/voices.json"))), saved: [{ id: "review-saved", ...reference("saved.wav"), text: "收藏声音的对应文字" }] };
      else if (url.pathname === "/api/status") value = { model: { ready: true, download_fraction: 1 }, asr: { available: true }, download: { status: "idle" }, data_root: "review", python: "3.12" };
      else if (url.pathname === "/api/audio/upload") value = reference(`upload-${++serial}.wav`);
      else if (url.pathname === "/api/audio/prepare") {
        if (cropGate) { cropStarted = true; await cropGate; }
        value = reference(`prepared-${++serial}.wav`);
      } else if (url.pathname === "/api/jobs" && request.method() === "POST") {
        const payload = request.postDataJSON();
        value = { id: `job-${++serial}`, status: "queued", payload, created_at: Date.now(), message: "已排队" };
        jobs.unshift({ ...value, status: "complete", result: { text: "旧录音的自动转写" } });
      } else if (url.pathname === "/api/jobs") value = jobs;
      else if (url.pathname === "/api/audio/file") return route.fulfill({ status: 204 });
      await route.fulfill({ json: value });
    });
    await page.goto(process.env.MING_STUDIO_URL || "http://127.0.0.1:7863/");
    await page.locator("#task").selectOption("seed");
    const upload = () => page.locator("#reference-upload").setInputFiles({ name: "reference.wav", mimeType: "audio/wav", buffer: Buffer.from("test audio") });
    const createPendingTranscript = async () => {
      await upload();
      await page.locator("#reference-detail").waitFor({ state: "visible" });
      await page.locator("#transcript").fill("手工核对后的文字");
      await page.locator("#transcribe-reference").click();
      await page.locator("#adopt-machine").waitFor({ state: "visible" });
      assert.equal(await page.locator("#transcript").inputValue(), "手工核对后的文字");
    };
    await createPendingTranscript();
    await page.locator("#crop-end").fill("1");
    await page.locator("#apply-crop").click();
    await page.waitForFunction(() => document.getElementById("transcript").value === "");
    assert.equal(await page.locator("#adopt-machine").isVisible(), false);
    await createPendingTranscript();
    await page.locator("#clear-reference").click();
    assert.equal(await page.locator("#reference-detail").isVisible(), false);
    await upload();
    await page.locator("#reference-detail").waitFor({ state: "visible" });
    assert.equal(await page.locator("#adopt-machine").isVisible(), false);
    await page.locator('[data-view="library"]').click();
    await page.locator('#saved-voices [data-saved-voice="review-saved"]').click();
    assert.equal(await page.locator("#transcript").inputValue(), "收藏声音的对应文字");
    assert.match(await page.locator("#reference-player").getAttribute("src"), /saved.wav/);
    await page.locator('[data-view="dialogue"]').click();
    await page.locator("[data-role-saved]").first().click();
    await page.locator("#saved-dialog").waitFor({ state: "visible" });
    await page.keyboard.press("Escape");
    await page.locator('[data-view="library"]').click();
    await page.locator('#saved-voices [data-saved-voice="review-saved"]').click();
    assert.equal(await page.locator("#reference-player").isVisible(), true);
    assert.equal(await page.locator("#transcript").inputValue(), "收藏声音的对应文字");
    let releaseCrop;
    cropGate = new Promise(resolve => { releaseCrop = resolve; });
    await page.locator("#apply-crop").click();
    await page.waitForTimeout(100);
    assert.equal(cropStarted, true);
    await page.locator("#clear-reference").click();
    releaseCrop();
    await page.waitForTimeout(150);
    assert.equal(await page.locator("#reference-detail").isVisible(), false);
    await page.screenshot({ path: path.join(output, "desktop.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: path.join(output, "mobile.png"), fullPage: true });
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, "result.json"), JSON.stringify({ passed: true, browser: await browser.version(), cases: ["manual transcript protected", "crop clears stale ASR", "clear and replacement clear stale ASR", "saved voice wins over existing draft", "closed role picker cannot redirect a later choice", "late crop cannot resurrect reference", "390px layout", "no page errors"], inference: "not run; controlled API responses" }, null, 2));
    console.log("Browser review passed: reference state, saved voice, late responses, desktop/mobile, no page errors");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

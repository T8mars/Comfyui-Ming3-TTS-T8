// Run with Node and JSDOM_MODULE pointing to an installed jsdom package.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require(process.env.JSDOM_MODULE || "jsdom");
const root = path.resolve(__dirname, "..");
const dom = new JSDOM(fs.readFileSync(path.join(root, "studio/index.html"), "utf8"), {
  url: "http://127.0.0.1:7863", runScripts: "outside-only",
});
const w = dom.window;
w.setInterval = () => 0;
w.requestAnimationFrame = fn => fn();
w.HTMLCanvasElement.prototype.getContext = () => ({ clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {} });
w.HTMLMediaElement.prototype.pause = () => {};
w.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
w.HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new w.Event("close")); };
let preparedPath = "cropped.wav";
let prepareGate = null;
w.fetch = async (url, options = {}) => ({
  ok: true,
  json: async () => url === "/api/voices"
    ? { ...JSON.parse(fs.readFileSync(path.join(root, "ming_t8/assets/voices.json"))), saved: [] }
    : url === "/api/status" ? { model: { ready: true }, asr: { available: true } }
    : url === "/api/jobs" ? []
    : url === "/api/audio/prepare" ? (prepareGate ? await prepareGate : { path: preparedPath, seconds: 1, start: 0, end: 1, waveform: [] })
    : url === "/api/audio/upload" ? { path: "new.wav", seconds: 1 }
    : url === "/api/audio/inspect" ? {path:JSON.parse(options.body).path,seconds:2,waveform:[]}
    : {},
});
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
(async () => {
  const source = fs.readFileSync(path.join(root, "studio/app.js"), "utf8");
  await w.eval(`(async()=>{${source}\nglobalThis.__app={state,showReference,uploadReference,updateTask,setView,chooseSaved,populateRequest};})()`);
  const { state, showReference, uploadReference, updateTask, setView, chooseSaved, populateRequest } = w.__app;
  const $ = id => w.document.getElementById(id);
  $("task").value = "seed"; updateTask();
  function pendingTranscript() {
    state.reference = { path: "old.wav", source_path: "original.wav", seconds: 2, waveform: [] };
    state.machineText = "旧录音的识别结果";
    state.transcriptTouched = true;
    $("transcript").value = "手动修改的文字";
    $("adopt-machine").hidden = false;
    showReference();
  }
  pendingTranscript();
  $("crop-start").value = 0; $("crop-end").value = 1;
  $("apply-crop").click(); await tick();
  assert.equal(state.reference.path, "cropped.wav");
  assert.equal(state.machineText, "", "crop must invalidate the old ASR result");
  assert.equal($("adopt-machine").hidden, true);
  $("adopt-machine").click();
  assert.equal($("transcript").value, "");
  pendingTranscript();
  $("clear-reference").click(); await tick();
  assert.equal(state.machineText, "");
  assert.equal(state.transcriptTouched, false);
  assert.equal($("adopt-machine").hidden, true);
  pendingTranscript();
  await uploadReference(new w.File(["audio"], "new.wav"));
  assert.equal(state.machineText, "");
  assert.equal($("adopt-machine").hidden, true, "upload must hide the old adoption action");
  // A saved voice must replace the existing seed draft, rather than being overwritten by it.
  pendingTranscript();
  setView("library");
  state.saved = [{ id: "saved-new", path: "saved.wav", text: "收藏录音的文字", seconds: 1 }];
  chooseSaved("saved-new");
  assert.equal(state.reference.path, "saved.wav");
  assert.equal($("transcript").value, "收藏录音的文字");
  assert.equal(state.machineText, "");
  pendingTranscript();
  await populateRequest({task:"seed",text:"工程正文",prompt_wav:"project.wav",prompt_text:"工程录音文字",target_language:"Chinese"});
  assert.equal(state.machineText, "", "loading an independent project must discard the previous ASR result");
  assert.equal($("adopt-machine").hidden, true);
  assert.equal($("transcript").value, "工程录音文字");
  // Finishing an old crop after the user clears it must not resurrect that reference.
  pendingTranscript();
  let finishCrop;
  prepareGate = new Promise(resolve => { finishCrop = resolve; });
  $("crop-start").value = 0; $("crop-end").value = 1;
  $("apply-crop").click(); await tick();
  $("clear-reference").click();
  finishCrop({ path: "obsolete-crop.wav", seconds: 1, waveform: [] });
  await tick();
  assert.equal(state.reference, null, "late crop must not restore a cleared reference");
  setView("dialogue");
  w.document.querySelector("[data-role-saved]").click(); await tick();
  assert.ok(state.voiceTarget);
  w.document.querySelector('[data-close-dialog="saved-dialog"]').click(); await tick();
  assert.equal(state.voiceTarget, null, "closing the picker clears its role destination");
  setView("library"); chooseSaved("saved-new");
  assert.equal(state.view, "single");
  assert.equal(state.reference.path, "saved.wav");
  console.log("Reference crop, clear and replacement invalidate stale ASR results: passed");
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => dom.window.close());

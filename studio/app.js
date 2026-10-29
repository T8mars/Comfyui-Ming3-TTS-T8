const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ],
  );
const state = {
  view: "single",
  voice: "灵小柔",
  reference: null,
  transcriptTouched: false,
  machineText: "",
  voices: [],
  favoriteVoices: new Set(),
  saved: [],
  roles: [],
  lines: [],
  dialogueMode: "joint",
  batch: [],
  jobs: [],
  focusJob: null,
  activeJob: null,
  callbacks: new Map(),
  audioSeen: new Set(),
  audioContext: null,
  audioTime: 0,
  audioSources: new Set(),
  audioEpoch: 0,
  streamingJob: null,
  voiceTarget: null,
  catalogLimit: 36,
  recording: null,
  taskBeforeDialogue: "ip",
  status: null,
  asrOptions: {language:"Auto",context:"",hotwords:""},
  modeDrafts: {},
  modeKey: null,
};
const terminal = new Set([
  "complete",
  "needs_review",
  "failed",
  "cancelled",
  "interrupted",
]);
const labels = {
  ip: "内置音色",
  seed: "声音克隆",
  multilingual: "多语种克隆",
  paralinguistic: "声音标签",
  podcast: "联合对话",
  basic: "基础属性",
  emotion: "情绪配音",
  dialect: "方言配音",
  freeform: "自由指令",
  voice_design: "声音设计",
};
const help = {
  ip: "直接选择喜欢的声音，无需准备参考录音。",
  seed: "用一段录音克隆中英文声音。参考文字应与录音一致。",
  multilingual:
    "用参考声音朗读德语、西语、法语、韩语或日语。请填写对应语言的正文。",
  paralinguistic: "在中文或英文中插入笑声、叹气等声音标签。",
  basic: "同时设置语速、音高和音量，以参考录音的音色进行配音。",
  emotion: "从七种情绪中选择一种，参考录音只提供音色。",
  dialect: "用参考音色说川渝话或广粤话，正文请使用适合该方言的表达。",
  freeform: "用自然语言描述演绎方式，默认无需参考录音；也可添加参考音色。",
  voice_design: "描述声音的年龄、音色和表达特点，无需参考录音。",
};
const tags = {
  "[Breathing]": "呼吸",
  "[Cough]": "咳嗽",
  "[Sigh]": "叹气",
  "[Laughter]": "笑声",
  "[Surprise-ah]": "惊讶啊",
  "[Surprise-oh]": "惊讶哦",
  "[Dissatisfaction-hnn]": "不满哼",
  "[Uhm]": "犹豫",
  "[Confirmation-en]": "肯定嗯",
  "[Question-ei]": "疑问诶",
  "[Question-ah]": "疑问啊",
  "[Question-en]": "疑问嗯",
  "[Question-oh]": "疑问哦",
  "[Question-huh]": "疑问 huh",
};

async function api(path, options = {}) {
  const config = { ...options };
  if (config.body && !(config.body instanceof FormData)) {
    config.body = JSON.stringify(config.body);
    config.headers = { "Content-Type": "application/json", ...config.headers };
  }
  const response = await fetch(path, config);
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "请求未完成，请查看任务提示" }));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : JSON.stringify(error.detail),
    );
  }
  return response.json();
}
let toastTimer;
function fieldError(message,field) { return Object.assign(new Error(message),{field}); }
function clearFieldErrors() {
  document.querySelectorAll("[data-field-error]").forEach(message=>message.remove());
  document.querySelectorAll('[aria-invalid="true"]').forEach(element=>{
    element.removeAttribute("aria-invalid");
    const described=element.getAttribute("aria-describedby");
    if(described?.startsWith("ming-error-"))element.removeAttribute("aria-describedby");
  });
}
function showFieldError(error) {
  const field=$(error.field);if(!field)return;
  clearFieldErrors();
  const message=document.createElement("p");message.className="field-error";message.dataset.fieldError="true";
  message.id=`ming-error-${field.id}`;message.setAttribute("role","alert");message.textContent=error.message;
  field.setAttribute("aria-invalid","true");field.setAttribute("aria-describedby",message.id);
  (field.closest("label")||field).after(message);
  field.focus();
}
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("toast").hidden = true), 5500);
}
function run(action) {
  return async (event) => {
    try {
      await action(event);
    } catch (error) {
      showFieldError(error);
      toast(error.message);
      console.error(error);
    }
  };
}
function bind(id, action, event = "click") {
  $(id).addEventListener(event, run(action));
}
function selectedTask() {
  return $("task").value;
}
const modeFields=["main-text","language","style","instruction","emotion","dialect","speed","pitch","volume","transcript","seed","cfg","flow-steps","temperature","sigma","stop-threshold","minimum","maximum","log-every","chunk-size","pause-ms"];
const cloneDraft=value=>value==null?value:JSON.parse(JSON.stringify(value));
function editingModeKey() {
  if(state.view==="dialogue")return `dialogue:${state.dialogueMode}`;
  if(["single","batch"].includes(state.view))return `${state.view}:${selectedTask()}`;
  return null;
}
function rememberMode() {
  if(!state.modeKey)return;
  state.modeDrafts[state.modeKey]={fields:Object.fromEntries(modeFields.map(id=>[id,$(id).value])),
    voice:state.voice,reference:cloneDraft(state.reference),transcriptTouched:state.transcriptTouched,machineText:state.machineText,
    ...(state.modeKey.startsWith("batch:")?{batch:cloneDraft(state.batch),batchImported:cloneDraft(state.batchImported),batchSignature:state.batchSignature}:{})};
}
function restoreMode(key) {
  const draft=state.modeDrafts[key];
  if(draft){
    for(const [id,value] of Object.entries(draft.fields))if($(id))$(id).value=value;
    Object.assign(state,{voice:draft.voice,reference:cloneDraft(draft.reference),transcriptTouched:draft.transcriptTouched,machineText:draft.machineText});
    if(key.startsWith("batch:"))Object.assign(state,{batch:cloneDraft(draft.batch)||[],batchImported:cloneDraft(draft.batchImported),batchSignature:draft.batchSignature});
  }else if(key.startsWith("batch:")){state.batch=[];state.batchImported=null;state.batchSignature=null;}
  state.modeKey=key;
  showSelectedVoice();showReference();
  if(state.view==="batch")renderBatch();
}
function setView(view) {
  const previousMode=state.modeKey;
  rememberMode();state.modeKey=null;
  const wasDialogue = state.view === "dialogue";
  if (view === "dialogue" && !wasDialogue) {
    state.taskBeforeDialogue =
      selectedTask() === "podcast" ? (previousMode?.split(":")[1]||state.taskBeforeDialogue||"ip") : selectedTask();
    $("task").value = "podcast";
  }
  if (wasDialogue && view !== "dialogue")
    $("task").value = state.taskBeforeDialogue;
  state.view = view;
  if (view === "dialogue" && !wasDialogue && $("seed").value === "1234") $("seed").value = "1235";
  if (wasDialogue && view !== "dialogue" && $("seed").value === "1235") $("seed").value = "1234";
  document
    .querySelectorAll(".nav-button")
    .forEach((button) =>
      button.classList.toggle("active", button.dataset.view === view),
    );
  const names = {
    single: ["从一句话开始创作", "写好文字，选一个声音，其余的交给明。"],
    dialogue: ["让不同的声音，相遇", "安排角色与台词，制作属于你的对话场景。"],
    batch: [
      "长篇灵感，也能从容完成",
      "分段制作、一起排队，保留每一段的创作记录。",
    ],
    library: ["收藏那些喜欢的声音", "把清晰的参考录音与文字，留给下一次灵感。"],
    history: [
      "每一次创作，都有迹可循",
      "回听作品、继续调整，或重做未完成的片段。",
    ],
  };
  $("view-title").textContent = names[view][0];
  $("view-description").textContent = names[view][1];
  $("creation-workspace").hidden = ["library", "history"].includes(view);
  $("library-page").hidden = view !== "library";
  $("history-page").hidden = view !== "history";
  $("writing-card").hidden = view === "dialogue";
  $("voice-card").hidden = view === "dialogue";
  $("dialogue-card").hidden = view !== "dialogue";
  $("batch-card").hidden = view !== "batch";
  $("generate").innerHTML =
    view === "dialogue"
      ? "<span>✦</span> 生成对话"
      : view === "batch"
        ? "<span>✦</span> 生成全部片段"
        : ["library", "history"].includes(view)
          ? "回到配音工作台"
          : "<span>✦</span> 生成语音";
  if (view === "dialogue" && !state.roles.length) {
    addRole();
    addRole();
    addLine();
    addLine();
  }
  updateTask();
  renderRoles();
  renderHistory();
  renderSaved();
  saveDraft();
}
function updateTask(options={}) {
  const task = selectedTask();
  if (task === "podcast" && state.view !== "dialogue") {
    setView("dialogue");
    return;
  }
  const modeKey=editingModeKey();
  if(modeKey&&modeKey!==state.modeKey){
    rememberMode();
    if(options.preserveInputs)state.modeKey=modeKey;
    else restoreMode(modeKey);
  }
  const fields = {
    "builtin-fields": task === "ip",
    "style-field": task === "voice_design",
    "instruction-field": task === "freeform",
    "emotion-field": task === "emotion",
    "dialect-field": task === "dialect",
    "basic-fields": task === "basic",
    "reference-fields": [
      "seed",
      "multilingual",
      "paralinguistic",
      "basic",
      "emotion",
      "dialect",
      "freeform",
    ].includes(task),
    "transcript-field": ["seed", "multilingual", "paralinguistic"].includes(
      task,
    ),
    "language-field": ["seed", "multilingual", "paralinguistic"].includes(task),
    "tag-toolbar": task === "paralinguistic",
  };
  for (const [id, visible] of Object.entries(fields)) $(id).hidden = !visible;
  const allowed =
    task === "multilingual"
      ? ["German", "Spanish", "French", "Korean", "Japanese"]
      : ["Chinese", "English"];
  [...$("language").options].forEach(
    (option) => (option.hidden = !allowed.includes(option.value)),
  );
  if (!allowed.includes($("language").value)) $("language").value = allowed[0];
  $("task-help").textContent = help[task] || "";
  $("context-tip").textContent =
    task === "ip"
      ? "内置音色无需准备录音。先生成一句短句，找到喜欢的声音，再开始长篇创作。"
      : "参考录音中的背景音乐、长时间静音或不一致的文字，都会影响结果。生成前先试听和检查。";
  saveDraft();
}
function advanced() {
  const value = {
    seed: Number($("seed").value),
    cfg_scale: Number($("cfg").value),
    flow_steps: Number($("flow-steps").value),
    temperature: Number($("temperature").value),
    sigma: Number($("sigma").value),
    stop_threshold: Number($("stop-threshold").value),
    log_every_n_steps: Number($("log-every").value),
  };
  const minimum = Number($("minimum").value),
    maximum = Number($("maximum").value);
  if (state.view === "dialogue" && state.dialogueMode === "joint") {
    if (minimum || maximum) {
      value.min_generation_frames = minimum;
      value.max_generation_frames = maximum;
    }
  } else {
    if (minimum) value.min_decode_steps = minimum;
    if (maximum) value.max_decode_steps = maximum;
  }
  return value;
}
function request(text = $("main-text").value) {
  if (!text.trim()) throw fieldError("请先写下要说的话","main-text");
  const task = selectedTask(),
    value = { task, text, ...advanced() };
  if (
    [
      "seed",
      "multilingual",
      "paralinguistic",
      "basic",
      "emotion",
      "dialect",
    ].includes(task) &&
    !state.reference
  )
    throw fieldError("请先添加参考录音","reference-drop");
  if (["seed", "multilingual", "paralinguistic"].includes(task)) {
    if (!$("transcript").value.trim())
      throw fieldError("请填写或识别参考录音中的文字","transcript");
    value.prompt_wav = state.reference.path;
    value.prompt_text = $("transcript").value;
    value.target_language = $("language").value;
  }
  if (["basic", "emotion", "dialect"].includes(task))
    value.prompt_wav = state.reference.path;
  if (task === "basic")
    Object.assign(value, {
      speed: $("speed").value,
      pitch: $("pitch").value,
      volume: $("volume").value,
    });
  if (task === "emotion") value.emotion = $("emotion").value;
  if (task === "dialect") value.dialect = $("dialect").value;
  if (task === "ip") value.ip = state.voice;
  if (task === "voice_design") {
    value.style = $("style").value;
    if (!value.style.trim()) throw fieldError("请描述你希望听到的声音","style");
  }
  if (task === "freeform") {
    value.instruction = $("instruction").value;
    if (!value.instruction.trim()) throw fieldError("请填写演绎方式","instruction");
    if (state.reference) value.prompt_wav = state.reference.path;
  }
  return value;
}
async function submit(payload, callback) {
  clearFieldErrors();
  if (payload.streaming) {
    state.audioContext ||= new AudioContext();
    await state.audioContext.resume();
  }
  if (
    payload.operation !== "transcribe" &&
    state.status &&
    !state.status.model.ready
  )
    throw new Error("模型仍在下载或校验中，进度可在页面上方查看");
  const job = await api("/api/jobs", { method: "POST", body: payload });
  stopStreaming();
  state.activeJob = job.id;
  state.focusJob = job.id;
  state.streamingJob = payload.streaming ? job.id : null;
  state.audioSeen.clear();
  state.audioTime = 0;
  if (callback) state.callbacks.set(job.id, callback);
  $("result-audio").pause();
  $("result-audio").removeAttribute("src");
  $("result-detail").hidden = true;
  $("transcript-result").hidden = true;
  $("empty-result").hidden = false;
  $("result-badge").textContent = "已加入队列";
  toast("已加入生成队列");
  await refreshJobs();
  return job;
}
async function generate() {
  if (["history", "library"].includes(state.view)) return setView("single");
  if (state.view === "dialogue") {
    return submit({...dialoguePayload(),...dialogueMetadata()});
  }
  if (state.view === "batch") {
    if (state.batch.length && state.batchSignature !== JSON.stringify(request("批量模板"))) state.batch=[];
    if (!state.batch.length) await previewSegments(state.batchImported);
    return submit({
      operation: "batch",
      segments: state.batch,
      streaming: $("streaming").checked,
    });
  }
  if ($("streaming").checked) {
    state.audioContext ||= new AudioContext();
    await state.audioContext.resume();
  }
  return submit({
    operation: "generate",
    request: request(),
    streaming: $("streaming").checked,
  });
}

function directorRequest(line) {
  const role = state.roles.find(item => item.id === line.role);
  if (!role || !line.text.trim()) throw new Error("请先选择角色并填写台词");
  const value = {text:line.text,...advanced()};
  if (line.variation) value.seed += line.variation;
  if (role.mode === "ip") return {...value,task:"ip",ip:role.ip || "灵小柔"};
  if (role.mode === "voice_design") {
    if (!role.style?.trim()) throw new Error(`${role.name} 还没有填写声音设计`);
    return {...value,task:"voice_design",style:role.style};
  }
  if (!role.reference) throw new Error(`${role.name} 还没有参考录音`);
  const task = line.task || "seed";
  Object.assign(value,{task,prompt_wav:role.reference.path});
  if (["seed","multilingual","paralinguistic"].includes(task)) {
    if (!role.text?.trim()) throw new Error(`${role.name} 还缺参考录音的对应文字`);
    value.prompt_text = role.text;
    value.target_language = task === "multilingual" ? (["German","Spanish","French","Korean","Japanese"].includes(line.language) ? line.language : "Japanese") : (["Chinese","English"].includes(line.language) ? line.language : /[\u3400-\u9fff]/.test(line.text)?"Chinese":"English");
  }
  if (task === "emotion") value.emotion = line.emotion || "高兴";
  if (task === "dialect") value.dialect = line.dialect || "川渝话";
  if (task === "basic") Object.assign(value,{speed:line.speed||"中速",pitch:line.pitch||"中",volume:line.volume||"中"});
  if (task === "freeform") {value.instruction=line.instruction||"";if(!value.instruction.trim())throw new Error("请填写这句台词的演绎指令");}
  return value;
}

function dialoguePayload() {
  if (state.roles.length < (state.dialogueMode === "joint" ? 2 : 1)) throw new Error("请先添加对话角色");
  const lines = state.lines.filter(line=>line.text.trim());
  if (!lines.length) throw new Error("请添加至少一行台词");
  if (state.dialogueMode === "director") return {operation:"batch",streaming:$("streaming").checked,dialogue_mode:"director",segments:lines.map(line=>({
    request:directorRequest(line),pause_ms:line.pause??250,line_id:line.id,role_id:line.role,...(line.take?{reuse_from:{job_id:line.take.job_id,segment_index:0}}:{})}))};
  const used = new Set(lines.map(line=>line.role));
  for (const role of state.roles) {
    if (!role.reference || !role.text.trim()) throw new Error(`${role.name} 还缺参考录音或对应文字`);
    if (!used.has(role.id)) throw new Error(`${role.name} 还没有台词，请补充台词或移除该角色`);
  }
  return {operation:"generate",streaming:$("streaming").checked,request:{task:"podcast",
    text:lines.map(line=>`speaker_${state.roles.findIndex(role=>role.id===line.role)+1}: ${line.text}`).join("\n"),
    prompt_wav:state.roles.map(role=>role.reference.path),prompt_text:state.roles.map(role=>role.text),...advanced()}};
}

function dialogueMetadata() {
  return {characters:state.roles.map(role=>({id:role.id,name:role.name,mode:role.mode||"reference",ip:role.ip,style:role.style,prompt_wav:role.reference?.path,prompt_text:role.text})),
    ui:{lines:state.lines.map(({take,...line})=>line),dialogue_mode:state.dialogueMode,generation_settings:advanced()}};
}
function drawWave(info,canvas=$("reference-wave")) {
  const context = canvas.getContext("2d");
  canvas.width = Math.max(canvas.clientWidth, 300) * 2;
  canvas.height = 128;
  context.clearRect(0, 0, canvas.width, 128);
  context.strokeStyle = "#ee8bb2";
  context.lineWidth = 2;
  const samples = info.waveform || [];
  samples.forEach((value, index) => {
    const x = (index * canvas.width) / samples.length;
    const height = Math.max(2, value * 100);
    context.beginPath();
    context.moveTo(x, 64 - height / 2);
    context.lineTo(x, 64 + height / 2);
    context.stroke();
  });
}
async function uploadReference(file, roleId = null) {
  toast("正在读取录音…");
  const form = new FormData();
  form.append("file", file);
  const info = await api("/api/audio/upload", { method: "POST", body: form });
  const prepared = await api("/api/audio/prepare", {
    method: "POST",
    body: { path: info.path, start: 0, end: info.seconds },
  });
  const reference = { ...info, ...prepared, source_path: info.path };
  if (roleId) {
    const role = state.roles.find((item) => item.id === roleId);
    if (role) {
      role.reference = reference;
      role.text = "";
      role.manual = false;
    }
    renderRoles();
  } else {
    state.reference = reference;
    state.transcriptTouched = false;
    state.machineText = "";
    $("transcript").value = "";
    showReference();
  }
  saveDraft();
  toast("参考录音已准备好");
}
function showReference() {
  const info = state.reference;
  $("reference-detail").hidden = !info;
  if (!info) return;
  $("reference-name").textContent = info.name || "我的参考声音";
  $("reference-duration").textContent = `${Number(info.seconds || 0).toFixed(1)} 秒`;
  let player = $("reference-player");
  if (!player) {
    player = document.createElement("audio"); player.id = "reference-player"; player.controls = true;
    player.style.width = "100%"; player.style.marginTop = "10px";
    $("reference-wave").after(player);
  }
  player.src = `/api/audio/file?path=${encodeURIComponent(info.path)}`;
  $("crop-start").value = info.start || 0;
  $("crop-end").value = info.end || info.seconds;
  $("reference-quality").textContent =
    (info.warnings || []).join("；") || "片段已就绪，请试听并检查对应文字。";
  requestAnimationFrame(() => drawWave(info));
}
async function transcribeReference(roleId = null) {
  const role = roleId ? state.roles.find((item) => item.id === roleId) : null;
  const reference = role ? role.reference : state.reference;
  if (!reference) throw new Error("请先添加参考录音");
  const path = reference.path;
  await submit(
    { operation: "transcribe", audio_path: path, ...state.asrOptions },
    (job) => {
      const text = job.result?.text || "";
      if (role) {
        if (role.reference?.path !== path) return;
        role.machineText = text;
        if (!role.manual) role.text = text;
        renderRoles();
      } else {
        if (state.reference?.path !== path) return;
        state.machineText = text;
        if (!state.transcriptTouched) {
          $("transcript").value = text;
          $("transcript-state").textContent = "Confucius 已识别，请检查后使用";
        } else {
          $("adopt-machine").hidden = false;
          toast("新的识别结果已保留，你手动修改的文字没有被覆盖");
        }
      }
      saveDraft();
    },
  );
}
async function saveNamed(title, initial = "") {
  return new Promise((resolve) => {
    const dialog = $("name-dialog");
    $("name-title").textContent = title;
    $("name-input").value = initial;
    dialog.returnValue = "";
    dialog.addEventListener(
      "close",
      () =>
        resolve(
          dialog.returnValue === "confirm"
            ? $("name-input").value.trim()
            : null,
        ),
      { once: true },
    );
    dialog.showModal();
    setTimeout(() => $("name-input").focus(), 0);
  });
}
async function saveVoice() {
  if (!state.reference) throw new Error("请先添加参考录音");
  const name = await saveNamed("保存到声音库");
  if (!name) return;
  await api("/api/voices", {
    method: "POST",
    body: {
      ...state.reference,
      name,
      text: $("transcript").value,
      confirmed: true,
    },
  });
  await loadVoices();
  toast("声音已保存，下次可以直接选择");
}
async function loadVoices() {
  const data = await api("/api/voices");
  state.voices = data.voices;
  state.saved = data.saved;
  renderCatalog();
  renderSaved();
  showSelectedVoice();
}
function showSelectedVoice() {
  const voice = state.voices.find((item) => item.id === state.voice);
  $("voice-name").textContent = voice?.name || state.voice;
  $("voice-description").textContent = voice?.description || "官方内置声音";
}
function renderCatalog() {
  const query = $("voice-search").value.toLowerCase(),
    lang = $("voice-filter").value,
    purpose = $("voice-purpose").value,
    favoritesOnly = $("voice-favorites-only").checked;
  const purposes = {
    service: /客服|助手|语音交互|assistant|customer|service/i,
    narration: /有声|旁白|解说|纪录片|narrat|audiobook/i,
    radio: /电台|情感|治愈|radio/i,
    news: /新闻|播报|播音|news|broadcast/i,
    character: /角色|游戏|二次元|童声|儿童|character|game/i,
    promotion: /广告|带货|电商|产品推荐|品牌|advertis|commercial/i,
    daily: /日常|生活|闲聊|邻家|daily|casual|conversat/i,
  };
  const matched = state.voices.filter(
    (voice) =>
      (!lang || voice.language === lang) &&
      (!favoritesOnly || state.favoriteVoices.has(voice.id)) &&
      (!purpose || purposes[purpose]?.test(voice.description || "")) &&
      `${voice.id} ${voice.description} ${voice.age} ${voice.gender}`
        .toLowerCase()
        .includes(query),
  );
  $("voice-catalog").innerHTML =
    matched
      .slice(0, state.catalogLimit)
      .map(
        (voice) =>
          `<div class="voice-option catalog-voice ${state.voice === voice.id ? "selected" : ""}"><button class="voice-pick" data-voice="${esc(voice.id)}"><strong>${esc(voice.name)}</strong><small>${esc(voice.gender)} · ${voice.language === "English" ? "英文" : "中文"} ${voice.variant ? "· 情绪变体" : ""}</small><p>${esc(voice.description)}</p></button><button class="favorite-toggle" data-favorite-voice="${esc(voice.id)}" aria-label="${state.favoriteVoices.has(voice.id) ? "取消收藏" : "收藏"}${esc(voice.name)}" aria-pressed="${state.favoriteVoices.has(voice.id)}" title="${state.favoriteVoices.has(voice.id) ? "取消收藏" : "收藏音色"}">${state.favoriteVoices.has(voice.id) ? "★" : "☆"}</button></div>`,
      )
      .join("") ||
    `<p class='field-note'>${favoritesOnly ? "还没有匹配的收藏。取消“只看收藏”后，点击音色旁的星星即可收藏。" : "没有找到匹配的声音，试试其他关键词或用途。"}</p>`;
  $("more-voices").hidden = matched.length <= state.catalogLimit;
}
function savedCards(picker = false) {
  return (
    state.saved
      .map(
        (voice) =>
          `<div class="voice-option"><strong>${esc(voice.name)}</strong><p>${esc(voice.text || "已保存参考录音")}</p><button class="text-button" data-saved-voice="${esc(voice.id)}">${picker ? "选择这个声音" : "用于配音"}</button>${picker ? "" : `<button class="text-button" data-delete-voice="${esc(voice.id)}" style="margin-left:16px">移除</button>`}</div>`,
      )
      .join("") ||
    "<p class='field-note'>还没有保存声音。添加一段参考录音，检查文字后即可保存。</p>"
  );
}
function renderSaved() {
  $("saved-voices").innerHTML = savedCards();
  $("saved-voice-picker").innerHTML = savedCards(true);
}
function chooseSaved(identifier) {
  const voice = state.saved.find((item) => item.id === identifier);
  if (!voice) return;
  const role = state.roles.find((item) => item.id === state.voiceTarget);
  if (role) {
    role.reference = { ...voice };
    role.text = voice.text || "";
    role.manual = true;
    renderRoles();
  } else {
    state.reference = { ...voice };
    $("transcript").value = voice.text || "";
    state.transcriptTouched = true;
    $("task").value = "seed";
    setView("single");
    showReference();
  }
  $("saved-dialog").close();
  state.voiceTarget = null;
  saveDraft();
}
function addRole() {
  state.roles.push({
    id: crypto.randomUUID(),
    name: `角色 ${state.roles.length + 1}`,
    reference: null,
    text: "",
    manual: false,
  });
  renderRoles();
  saveDraft();
}
function addLine() {
  const role =
    state.roles[state.lines.length % Math.max(state.roles.length, 1)];
  state.lines.push({
    id: crypto.randomUUID(),
    role: role?.id,
    text: "",
    pause: 250,
  });
  renderRoles();
  saveDraft();
}
function renderRoles() {
  const director = state.dialogueMode === "director";
  $("roles").innerHTML = state.roles
    .map(
      (role) =>
        `<div class="role-card"><div><input aria-label="角色名称" value="${esc(role.name)}" data-role-name="${role.id}">
        ${director?`<label>角色的声音<select data-role-mode="${role.id}">${[["reference","参考声音"],["ip","内置音色"],["voice_design","文字设计"]].map(([id,label])=>`<option value="${id}" ${(role.mode||"reference")===id?"selected":""}>${label}</option>`).join("")}</select></label>`:""}
        ${director&&role.mode==="ip"?`<p>当前：${esc(role.ip||"灵小柔")}</p><button class="button quiet small" data-role-catalog="${role.id}">选择官方音色</button>`:director&&role.mode==="voice_design"?`<textarea rows="3" data-role-style="${role.id}" placeholder="描述这位角色的声音、年龄与语气">${esc(role.style||"")}</textarea>`:`<p>${role.reference ? esc(role.reference.name || "参考录音已就绪") : "还没有选择参考声音"}</p><textarea rows="2" aria-label="参考录音对应文字" placeholder="这段角色录音说了什么" data-role-text="${role.id}">${esc(role.text)}</textarea><div class="role-actions"><button class="text-button" data-role-upload="${role.id}">上传录音</button><button class="text-button" data-role-saved="${role.id}">声音库</button><button class="text-button" data-role-asr="${role.id}">识别文字</button></div>`}</div>
        <div class="role-actions"><button class="text-button" data-role-move="${role.id}" data-direction="-1" aria-label="角色上移">↑</button><button class="text-button" data-role-move="${role.id}" data-direction="1" aria-label="角色下移">↓</button><button class="text-button" data-role-remove="${role.id}">移除</button></div></div>`,
    )
    .join("");
  const options = (selected) =>
    state.roles
      .map(
        (role) =>
          `<option value="${role.id}" ${role.id === selected ? "selected" : ""}>${esc(role.name)}</option>`,
      )
      .join("");
  $("dialogue-lines").innerHTML = state.lines
    .map(
      (line) =>
        `<div class="dialogue-line"><select aria-label="台词角色" data-line-role="${line.id}">${options(line.role)}</select><textarea rows="2" aria-label="角色台词" placeholder="写下这位角色的台词…" data-line-text="${line.id}">${esc(line.text)}</textarea><button data-line-remove="${line.id}" aria-label="删除台词">×</button>
        <div class="line-tools"><button class="text-button" data-line-move="${line.id}" data-direction="-1">↑</button><button class="text-button" data-line-move="${line.id}" data-direction="1">↓</button>${director?`<label>句后停顿（毫秒）<input type="number" min="0" max="60000" value="${Number(line.pause??250)}" data-line-field="pause" data-line-id="${line.id}"></label><button class="button quiet small" data-line-preview="${line.id}">${line.take?"重新生成这一句":"试听这一句"}</button>`:""}</div>
        ${director?lineSettings(line):""}${director&&line.take?`<div class="line-take"><audio controls src="/api/artifacts/${esc(line.take.job_id)}/output.wav"></audio><small>上次试听；设置变化后会自动重新生成</small></div>`:""}</div>`,
    )
    .join("");
}

function lineSettings(line) {
  const role = state.roles.find(item=>item.id===line.role);
  if (role && ["ip","voice_design"].includes(role.mode)) return "";
  const task=line.task||"seed";
  const select=(name,choices,value)=>`<select data-line-field="${name}" data-line-id="${line.id}">${choices.map(item=>`<option value="${item}" ${item===value?"selected":""}>${labels[item]||item}</option>`).join("")}</select>`;
  let extra="";
  if (["seed","multilingual","paralinguistic"].includes(task)) {
    const languages=task==="multilingual"?["German","Spanish","French","Korean","Japanese"]:["Auto","Chinese","English"];
    extra=select("language",languages,languages.includes(line.language)?line.language:task==="multilingual"?"Japanese":"Auto");
  }
  if (task==="emotion")extra=select("emotion",["中性","高兴","悲伤","愤怒","惊讶","恐惧","厌恶"],line.emotion||"高兴");
  if (task==="dialect")extra=select("dialect",["川渝话","广粤话"],line.dialect||"川渝话");
  if (task==="basic")extra=select("speed",["慢速","中速","快速"],line.speed||"中速")+select("pitch",["低","中","高"],line.pitch||"中")+select("volume",["低","中","高"],line.volume||"中");
  if (task==="freeform")extra=`<input data-line-field="instruction" data-line-id="${line.id}" value="${esc(line.instruction||"")}" placeholder="这一句希望怎样演绎">`;
  return `<details class="line-settings"><summary>这一句的演绎设置</summary><div class="form-row">${select("task",["seed","multilingual","paralinguistic","emotion","dialect","basic","freeform"],task)}${extra}</div></details>`;
}

function renderBatch() {
  $("batch-preview").innerHTML=state.batch.map((segment,index)=>`<div class="batch-item"><span>${index+1}</span><div><small>${esc(labels[segment.request.task]||segment.request.task)} · ${esc(segment.request.ip||segment.request.emotion||segment.request.dialect||segment.request.target_language||"当前片段的独立设置")}</small><textarea rows="2" data-batch-index="${index}" aria-label="第${index+1}段文字">${esc(segment.request.text)}</textarea></div></div>`).join("");
}
async function previewSegments(imported = null) {
  const base = request(imported ? "批量内容" : $("main-text").value);
  const body = {
    template: base,
    text: imported?.text || $("main-text").value,
    format: imported?.format || "long",
    max_units: Number($("chunk-size").value),
    pause_ms: Number($("pause-ms").value),
  };
  const data = await api("/api/batch/preview", { method: "POST", body });
  state.batch = data.segments;
  state.batchImported=imported;
  state.batchSignature=JSON.stringify(request("批量模板"));
  if(imported)$("main-text").value=state.batch.map(item=>item.request.text).join("\n\n");
  renderBatch();
  toast(`已准备 ${state.batch.length} 个片段`);
  saveDraft();
}
async function refreshStatus() {
  try {
    state.status = await api("/api/status");
    const model = state.status.model;
    $("model-status").classList.toggle("ready", model.ready);
    $("model-status").textContent = model.ready ? "模型已就绪" : "准备模型";
    $("model-notice").hidden = model.ready;
    const downloading=state.status.download?.status==="downloading";
    $("model-notice").textContent = model.ready ? "" : downloading
      ? `模型正在下载，已完成 ${(model.download_fraction * 100).toFixed(1)}%。你可以先编辑文字或准备参考声音。`
      : `模型尚未准备好。缺少：${(model.missing||[model.path]).join("；")}。${model.download_bytes?`主模型下载约 ${(model.download_bytes/1e9).toFixed(2)} GB。`:""}请在设置中下载模型，或选择已有文件。`;
  } catch (error) {
    $("model-status").textContent = "连接工作台中…";
  }
}
function stopStreaming() {
  state.audioEpoch++;
  for (const source of state.audioSources) { try { source.stop(); } catch {} }
  state.audioSources.clear();
  state.audioTime = 0;
  state.streamingJob = null;
}
async function playChunk(identifier, filename) {
  const epoch = state.audioEpoch;
  const key = `${identifier}/${filename}`;
  if (state.audioSeen.has(key)) return;
  state.audioSeen.add(key);
  state.audioContext ||= new AudioContext();
  await state.audioContext.resume();
  const response = await fetch(`/api/artifacts/${identifier}/${filename}`);
  const buffer = await state.audioContext.decodeAudioData(
    await response.arrayBuffer(),
  );
  if (epoch !== state.audioEpoch) return;
  const source = state.audioContext.createBufferSource();
  source.buffer = buffer;
  source.connect(state.audioContext.destination);
  state.audioSources.add(source);
  source.onended = () => state.audioSources.delete(source);
  state.audioTime = Math.max(
    state.audioTime,
    state.audioContext.currentTime + 0.08,
  );
  source.start(state.audioTime);
  state.audioTime += buffer.duration;
}
function showJob(job) {
  $("result-badge").textContent =
    {
      complete: "已完成",
      needs_review: "请检查尾句",
      failed: "需要调整",
      cancelled: "已取消",
      running: "正在制作",
      queued: "排队中",
      interrupted: "上次中断",
    }[job.status] || job.status;
  $("partial-results").innerHTML =
    terminal.has(job.status) && !job.result
      ? (job.completed_segments || [])
          .map(
            (segment, index) =>
              `<a href="/api/artifacts/${job.id}/${segment.file}" download>下载已完成片段 ${index + 1}</a>`,
          )
          .join("")
      : "";
  if (!job.result) return;
  $("empty-result").hidden = true;
  if (job.result.audio_file) {
    $("result-detail").hidden = false;
    $("transcript-result").hidden = true;
    const url = `/api/artifacts/${job.id}/${job.result.audio_file}`;
    if (!$("result-audio").src.endsWith(url)) $("result-audio").src = url;
    if(state.resultWaveJob!==job.id){
      state.resultWaveJob=job.id;
      if(job.result.waveform)requestAnimationFrame(()=>drawWave(job.result,$("result-wave")));
      else api("/api/audio/inspect",{method:"POST",body:{path:`${state.status.data_root}/jobs/${job.id}/${job.result.audio_file}`}})
        .then(info=>{if(state.resultWaveJob===job.id)drawWave(info,$("result-wave"));}).catch(()=>{});
    }
    const measurements = job.result.metrics || [];
    const elapsed = job.result.seconds ?? measurements.reduce((sum, item) => sum + item.seconds, 0);
    const duration = job.result.audio_seconds;
    $("result-stats").innerHTML =
      `<span>${duration.toFixed(1)} 秒音频</span><span>生成 ${elapsed.toFixed(1)} 秒</span><span>${job.result.sample_rate / 1000} kHz</span>`;
  } else if (typeof job.result.text === "string") {
    $("transcript-result").hidden = false;
    $("result-detail").hidden = true;
    $("transcript-output").value = job.result.text;
  }
}
async function refreshJobs() {
  if (state.polling) return;
  state.polling = true;
  try {
    state.jobs = await api("/api/jobs");
    renderHistory();
    const active = state.jobs.find((job) => ["running", "cancelling"].includes(job.status)) || state.jobs.find((job) => job.status === "queued");
    state.activeJob = active?.id || null;
    $("cancel-job").hidden = !active;
    $("status-orb").classList.toggle("busy", !!active);
    if (active) {
      $("progress-title").textContent =
        active.phase === "transcribing" ? "正在识别录音" : "正在制作你的作品";
      $("progress-message").textContent = active.message;
      if(["loading","verifying","ready"].includes(active.phase)||(active.phase==="generating"&&active.payload.operation!=="batch")){
        $("job-progress").removeAttribute("value");$("progress-percent").textContent=active.phase==="generating"?"正在合成":"准备模型";
      }else if(active.payload.operation==="batch"){
        const completed=active.completed_segments?.length||0,total=active.payload.segments.length;
        $("job-progress").value=completed/total;$("progress-percent").textContent=`${completed}/${total}段`;
      }else{$("job-progress").value=active.progress;$("progress-percent").textContent=`${Math.round(active.progress*100)}%`;}
    } else {
      $("progress-title").textContent = "准备好，把灵感变成声音";
      $("progress-message").textContent = "可以继续调整，或开始新的创作";
      $("job-progress").value = 0;
      $("progress-percent").textContent = "";
    }
    const job = state.jobs.find((item) => item.id === state.focusJob);
    if (job) {
      showJob(job);
      if (["cancelled", "failed", "interrupted", "cancelling"].includes(job.status) && state.streamingJob === job.id) stopStreaming();
      if (job.payload.streaming && state.streamingJob === job.id) {
        for (const filename of job.chunks || [])
          await playChunk(job.id, filename).catch((error) =>
            console.warn(error),
          );
        if (terminal.has(job.status)) state.streamingJob = null;
      }
      if (terminal.has(job.status) && state.callbacks.has(job.id)) {
        const callback = state.callbacks.get(job.id);
        state.callbacks.delete(job.id);
        if (job.result) callback(job);
        else toast(job.message);
      }
      if (job.status === "failed") {
        $("progress-title").textContent = "请检查任务提示";
        $("progress-message").textContent = job.message;
      }
    }
    for (const completed of state.jobs) {
      if (terminal.has(completed.status) && state.callbacks.has(completed.id)) {
        const callback = state.callbacks.get(completed.id); state.callbacks.delete(completed.id);
        if (completed.result) callback(completed); else toast(completed.message);
      }
    }
  } catch (error) {
    console.warn(error);
  } finally {
    state.polling = false;
  }
}

async function downloadFile(url, fallbackName) {
  const response = await fetch(url);
  if (!response.ok) {
    const error = await response.json().catch(() => ({detail:"文件导出失败"}));
    throw new Error(error.detail || "文件导出失败");
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a"); anchor.href = objectUrl; anchor.download = fallbackName;
  document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
}

function renderHistory() {
  const title = (job) =>
    job.payload.operation === "transcribe"
      ? "参考录音转写"
      : job.payload.operation === "batch"
        ? `${job.payload.segments?.length || 0} 段批量配音`
        : job.payload.request?.text || "语音作品";
  const status = (job) =>
    ({
      complete: "已完成",
      needs_review: "需校对",
      failed: "失败",
      cancelled: "已取消",
      interrupted: "已中断",
      queued: "排队中",
      running: "生成中",
      cancelling: "取消中",
    })[job.status] || job.status;
  $("recent-jobs").innerHTML =
    state.jobs
      .slice(0, 5)
      .map(
        (job) =>
          `<div class="recent-item" data-job="${job.id}"><strong>${esc(title(job)).slice(0, 100)}</strong><small>${status(job)} · ${new Date(job.created_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</small></div>`,
      )
      .join("") || "<p class='field-note'>完成的作品会保存在这里。</p>";
  $("history-list").innerHTML =
    state.jobs
      .map(
        (job) =>
          `<div class="history-row"><div><p>${esc(title(job))}</p><small>${esc(job.message || "")} · ${new Date(job.created_at * 1000).toLocaleString()}</small></div><span class="hint-chip">${status(job)}</span><div class="actions"><button class="text-button" data-job="${job.id}">查看</button>${job.payload.operation !== "transcribe" ? `<button class="text-button" data-edit-job="${job.id}">继续编辑</button>` : ""}${terminal.has(job.status) ? `<button class="text-button" data-retry="${job.id}">重做</button>` : `<button class="text-button" data-cancel="${job.id}">取消</button>`}</div></div>`,
      )
      .join("") ||
    "<p class='field-note'>还没有生成任务，先从一句短文开始吧。</p>";
}
async function saveProject() {
  let project;
  if (state.view === "dialogue") {
    project = {
      name: "多人对话",
      ...dialoguePayload(),
      ...dialogueMetadata(),
    };
  } else if (state.view === "batch") {
    if (!state.batch.length) await previewSegments(state.batchImported);
    project = { name: "批量配音", segments: state.batch };
  } else {
    project = { name: "我的配音", request: request() };
  }
  const name = await saveNamed("保存语音工程", project.name);
  if (!name) return;
  project.name = name;
  const result = await api("/api/projects", { method: "POST", body: project });
  await downloadFile(`/api/projects/${result.id}/export`, `${project.name}.mingstudio.zip`);
  toast("工程已保存，并已打包参考音频");
}
async function loadProject(project) {
  if (project.characters?.length) {
    setView("dialogue");
    state.dialogueMode=project.ui?.dialogue_mode||"joint";
    const ids=new Map();
    state.roles=project.characters.map(character=>{const id=crypto.randomUUID();ids.set(character.id,id);return{
      id,name:character.name||"角色",mode:character.mode||"reference",ip:character.ip,style:character.style,
      reference:character.prompt_wav?{path:character.prompt_wav,name:"工程参考录音"}:null,text:character.prompt_text||"",manual:true};});
    state.lines=(project.ui?.lines||[]).map(line=>({...line,id:crypto.randomUUID(),role:ids.get(line.role)||state.roles[0].id,take:null}));
    document.querySelectorAll("[data-dialogue-mode]").forEach(button=>button.classList.toggle("active",button.dataset.dialogueMode===state.dialogueMode));
    renderRoles();
  } else if (project.segments) {
    setView("batch");
    if(project.segments[0]?.request.task!=="podcast")await populateRequest(project.segments[0].request);
    state.batch = project.segments;
    state.batchImported={text:JSON.stringify({segments:project.segments}),format:"json"};
    $("main-text").value = project.segments
      .map((item) => item.request.text)
      .join("\n\n");
    renderBatch();
    state.batchSignature=JSON.stringify(request("批量模板"));
  } else if (project.request?.task === "podcast") {
    setView("dialogue");
    const req = project.request;
    state.roles = req.prompt_wav.map((path, index) => ({
      id: crypto.randomUUID(),
      name: `角色 ${index + 1}`,
      reference: { path, name: `角色 ${index + 1}参考录音` },
      text: req.prompt_text[index],
      manual: true,
    }));
    state.lines = req.text
      .split("\n")
      .filter(Boolean)
      .map((line) => {
        const match = line.match(/^\s*speaker_(\d+)\s*:\s*(.*)$/);
        if (!match) throw new Error("工程对话脚本格式不正确");
        return {
          id: crypto.randomUUID(),
          role: state.roles[Number(match[1]) - 1].id,
          text: match[2],
        };
      });
    renderRoles();
  } else {
    const req = project.request;
    setView("single");
    await populateRequest(req);
  }
  const req = project.ui?.generation_settings || project.request || project.segments?.[0]?.request;
  if (req) {
    const fields = {seed:"seed",cfg_scale:"cfg",flow_steps:"flow-steps",temperature:"temperature",sigma:"sigma",stop_threshold:"stop-threshold",log_every_n_steps:"log-every"};
    for (const [key,id] of Object.entries(fields)) if (req[key] != null) $(id).value = req[key];
    $("minimum").value = req.min_generation_frames ?? req.min_decode_steps ?? 0;
    $("maximum").value = req.max_generation_frames ?? req.max_decode_steps ?? 0;
  }
  if(state.view==="batch")state.batchSignature=JSON.stringify(request("批量模板"));
  saveDraft();
  toast("工程已载入，可以继续编辑");
}

async function populateRequest(req) {
  rememberMode();state.modeKey=null;
  $("main-text").value=req.text;$("task").value=req.task;
  if(req.ip)state.voice=req.ip;
  for(const field of ["style","instruction","emotion","dialect","speed","pitch","volume"])if(req[field]!=null)$(field).value=req[field];
  if(req.target_language)$("language").value=req.target_language;
  state.reference=null;$("transcript").value=req.prompt_text||"";
  if(typeof req.prompt_wav==="string"){
    const audio=await api("/api/audio/inspect",{method:"POST",body:{path:req.prompt_wav}});
    state.reference={...audio,source_path:req.prompt_wav,name:"工程参考录音"};state.transcriptTouched=true;
  }
  updateTask({preserveInputs:true});showSelectedVoice();showReference();
}
function saveDraft() {
  try {
    rememberMode();
    const fields = {};
    document
      .querySelectorAll("textarea[id],input[id]:not([type=file]),select[id]")
      .forEach((element) => {
        if (
          ["transcript-output", "voice-search", "name-input"].includes(
            element.id,
          )
        )
          return;
        fields[element.id] =
          element.type === "checkbox" ? element.checked : element.value;
      });
    localStorage.setItem(
      "ming-t8-draft-v1",
      JSON.stringify({
        fields,
        voice: state.voice,
        reference: state.reference,
        roles: state.roles,
        lines: state.lines,
        dialogueMode: state.dialogueMode,
        asrOptions: state.asrOptions,
        modeDrafts:state.modeDrafts,
        taskBeforeDialogue:state.taskBeforeDialogue,
        batch:state.batch,batchImported:state.batchImported,batchSignature:state.batchSignature,
      }),
    );
  } catch {}
}
function restoreDraft() {
  try {
    const draft = JSON.parse(
      localStorage.getItem("ming-t8-draft-v1") || "null",
    );
    if (!draft) return;
    for (const [id, value] of Object.entries(draft.fields || {})) {
      const element = $(id);
      if (!element) continue;
      if (element.type === "checkbox") element.checked = value;
      else element.value = value;
    }
    Object.assign(state, {
      voice: draft.voice || "灵小柔",
      reference: draft.reference || null,
      roles: draft.roles || [],
      lines: draft.lines || [],
      dialogueMode: draft.dialogueMode || "joint",
      asrOptions: draft.asrOptions || {language:"Auto",context:"",hotwords:""},
      modeDrafts:draft.modeDrafts||{},
      taskBeforeDialogue:draft.taskBeforeDialogue||"ip",
      batch:draft.batch||[],batchImported:draft.batchImported||null,batchSignature:draft.batchSignature,
    });
  } catch {}
}
async function toggleRecording() {
  if (state.recording) {
    const record = state.recording;
    state.recording = null;
    record.processor.disconnect();
    record.source.disconnect();
    record.stream.getTracks().forEach((track) => track.stop());
    clearTimeout(record.timer);
    await record.context.close();
    $("record-reference").textContent = "开始录音";
    const length = record.buffers.reduce((sum, item) => sum + item.length, 0);
    const data = new Float32Array(length);
    let offset = 0;
    for (const buffer of record.buffers) {
      data.set(buffer, offset);
      offset += buffer.length;
    }
    const array = new ArrayBuffer(44 + length * 2),
      view = new DataView(array);
    const write = (position, text) =>
      [...text].forEach((character, index) =>
        view.setUint8(position + index, character.charCodeAt(0)),
      );
    write(0, "RIFF");
    view.setUint32(4, 36 + length * 2, true);
    write(8, "WAVEfmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, record.rate, true);
    view.setUint32(28, record.rate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    write(36, "data");
    view.setUint32(40, length * 2, true);
    data.forEach((sample, index) =>
      view.setInt16(
        44 + index * 2,
        Math.max(-1, Math.min(1, sample)) * 32767,
        true,
      ),
    );
    await uploadReference(
      new File([array], "麦克风录音.wav", { type: "audio/wav" }),
    );
    return;
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    },
  });
  const context = new AudioContext();
  const source = context.createMediaStreamSource(stream),
    processor = context.createScriptProcessor(4096, 1, 1),
    gain = context.createGain();
  gain.gain.value = 0;
  const record = {
    stream,
    context,
    source,
    processor,
    rate: context.sampleRate,
    buffers: [],
    timer: setTimeout(() => { if (state.recording) toggleRecording().catch(error => toast(error.message)); }, 120000),
  };
  processor.onaudioprocess = (event) =>
    record.buffers.push(new Float32Array(event.inputBuffer.getChannelData(0)));
  source.connect(processor);
  processor.connect(gain);
  gain.connect(context.destination);
  state.recording = record;
  $("record-reference").textContent = "停止并使用录音";
  toast("正在录音，读完后点击停止");
}

document
  .querySelectorAll(".nav-button")
  .forEach((button) =>
    button.addEventListener("click", () => setView(button.dataset.view)),
  );
document
  .querySelectorAll("[data-close-dialog]")
  .forEach((button) =>
    button.addEventListener("click", () =>
      $(button.dataset.closeDialog).close(),
    ),
  );
document.querySelectorAll("[data-export]").forEach((button) =>
  button.addEventListener("click", run(async () => {
    if (!state.focusJob) return toast("请先生成一段作品");
    await downloadFile(`/api/export/${state.focusJob}/${button.dataset.export}`, `明语音作品.${button.dataset.export}`);
  })),
);
document.addEventListener(
  "click",
  run(async (event) => {
    const target = event.target.closest(
      "[data-voice],[data-favorite-voice],[data-saved-voice],[data-delete-voice],[data-role-upload],[data-role-saved],[data-role-asr],[data-role-remove],[data-role-catalog],[data-role-move],[data-line-remove],[data-line-move],[data-line-preview],[data-job],[data-edit-job],[data-retry],[data-cancel],[data-tag]",
    );
    if (!target) return;
    if (target.dataset.favoriteVoice) {
      const id = target.dataset.favoriteVoice;
      if (state.favoriteVoices.has(id)) state.favoriteVoices.delete(id);
      else state.favoriteVoices.add(id);
      try { localStorage.setItem("ming-t8-favorite-voices-v1", JSON.stringify([...state.favoriteVoices])); }
      catch { toast("收藏暂时保存在本页，浏览器未允许保存到本机"); }
      renderCatalog();
    }
    if (target.dataset.voice) {
      const role=state.roles.find(item=>item.id===state.catalogRole);
      if(role){role.ip=target.dataset.voice;renderRoles();}else{state.voice = target.dataset.voice;state.batch=[];}
      state.catalogRole=null;
      showSelectedVoice();
      $("voice-dialog").close();
      saveDraft();
    }
    if (target.dataset.savedVoice) chooseSaved(target.dataset.savedVoice);
    if (target.dataset.deleteVoice) {
      await api(`/api/voices/${target.dataset.deleteVoice}`, {
        method: "DELETE",
      });
      await loadVoices();
    }
    if (target.dataset.roleUpload) {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "audio/*,video/*";
      input.onchange = run(() =>
        uploadReference(input.files[0], target.dataset.roleUpload),
      );
      input.click();
    }
    if (target.dataset.roleSaved) {
      state.voiceTarget = target.dataset.roleSaved;
      renderSaved();
      $("saved-dialog").showModal();
    }
    if (target.dataset.roleAsr)
      await transcribeReference(target.dataset.roleAsr);
    if(target.dataset.roleCatalog){state.catalogRole=target.dataset.roleCatalog;renderCatalog();$("voice-dialog").showModal();}
    if(target.dataset.roleMove||target.dataset.lineMove){
      const list=target.dataset.roleMove?state.roles:state.lines;
      const index=list.findIndex(item=>item.id===(target.dataset.roleMove||target.dataset.lineMove));
      const next=index+Number(target.dataset.direction);
      if(next>=0&&next<list.length)[list[index],list[next]]=[list[next],list[index]];
      renderRoles();saveDraft();
    }
    if(target.dataset.linePreview){
      const line=state.lines.find(item=>item.id===target.dataset.linePreview);
      if(line.take)line.variation=(line.variation||0)+1;
      const token=crypto.randomUUID();line.previewToken=token;
      const req=directorRequest(line);
      await submit({operation:"generate",request:req},job=>{if(line.previewToken!==token)return;line.take={job_id:job.id,request:req};renderRoles();saveDraft();});
    }
    if (target.dataset.roleRemove) {
      const id = target.dataset.roleRemove;
      if (state.lines.some((line) => line.role === id && line.text.trim()))
        throw new Error("这个角色还有台词，请先修改或删除对应台词");
      state.roles = state.roles.filter((role) => role.id !== id);
      state.lines = state.lines.filter((line) => line.role !== id);
      renderRoles();
      saveDraft();
    }
    if (target.dataset.lineRemove) {
      state.lines = state.lines.filter(
        (line) => line.id !== target.dataset.lineRemove,
      );
      renderRoles();
      saveDraft();
    }
    if (target.dataset.job) {
      stopStreaming();
      state.focusJob = target.dataset.job;
      setView("single");
      const job = state.jobs.find((item) => item.id === state.focusJob);
      $("result-detail").hidden = true;
      $("transcript-result").hidden = true;
      $("empty-result").hidden = !job?.result;
      if (job) showJob(job);
    }
    if (target.dataset.editJob) {
      const job = state.jobs.find(item => item.id === target.dataset.editJob);
      stopStreaming();
      await loadProject(job.payload);
    }
    if (target.dataset.retry) {
      const job = await api(`/api/jobs/${target.dataset.retry}/retry`, {
        method: "POST",
      });
      state.focusJob = job.id;
      await refreshJobs();
    }
    if (target.dataset.cancel)
      await api(`/api/jobs/${target.dataset.cancel}/cancel`, {
        method: "POST",
      });
    if (target.dataset.tag) {
      const text = $("main-text"),
        start = text.selectionStart;
      text.setRangeText(target.dataset.tag, start, text.selectionEnd, "end");
      text.focus();
      saveDraft();
    }
  }),
);
document.addEventListener("input", (event) => {
  if(event.target.getAttribute("aria-invalid")==="true")clearFieldErrors();
  const target = event.target;
  if (target.dataset.roleName) {
    const role = state.roles.find(
      (item) => item.id === target.dataset.roleName,
    );
    role.name = target.value;
  }
  if (target.dataset.roleText) {
    const role = state.roles.find(
      (item) => item.id === target.dataset.roleText,
    );
    role.text = target.value;
    role.manual = true;
  }
  if(target.dataset.roleStyle)state.roles.find(item=>item.id===target.dataset.roleStyle).style=target.value;
  if(target.dataset.lineField){
    const line=state.lines.find(item=>item.id===target.dataset.lineId);
    line[target.dataset.lineField]=target.dataset.lineField==="pause"?Number(target.value):target.value;
  }
  if(target.dataset.batchIndex!==undefined){state.batch[Number(target.dataset.batchIndex)].request.text=target.value;}
  if (target.dataset.lineText)
    state.lines.find((item) => item.id === target.dataset.lineText).text =
      target.value;
  if (target.id === "transcript") {
    state.transcriptTouched = true;
    $("transcript-state").textContent = "已手动修改，自动识别不会覆盖";
  }
  if(state.view==="batch"&&["task","main-text","transcript","style","instruction","language","emotion","dialect","speed","pitch","volume","seed","cfg","flow-steps","temperature","sigma","stop-threshold","minimum","maximum","log-every","chunk-size","pause-ms"].includes(target.id)){
    state.batch=[];
    if(target.id==="main-text")state.batchImported=null;
  }
  if (target.id === "main-text") {
    $("text-count").textContent = `${target.value.length} 字`;
    state.batch = [];
  }
  saveDraft();
});
document.addEventListener("change",event=>{
  const target=event.target;
  if(target.dataset.roleMode){state.roles.find(item=>item.id===target.dataset.roleMode).mode=target.value;renderRoles();saveDraft();}
  if(target.dataset.lineField){const line=state.lines.find(item=>item.id===target.dataset.lineId);line[target.dataset.lineField]=target.dataset.lineField==="pause"?Number(target.value):target.value;if(["task","language"].includes(target.dataset.lineField))renderRoles();saveDraft();}
});
document.addEventListener("change", (event) => {
  if (event.target.dataset.lineRole) {
    state.lines.find((item) => item.id === event.target.dataset.lineRole).role =
      event.target.value;
    renderRoles();
    saveDraft();
  }
});
document.querySelectorAll("[data-dialogue-mode]").forEach((button) =>
  button.addEventListener("click", () => {
    rememberMode();state.modeKey=null;
    state.dialogueMode = button.dataset.dialogueMode;
    $("minimum").value=0;$("maximum").value=0;
    if(state.dialogueMode==="director"&&$("seed").value==="1235")$("seed").value="1234";
    if(state.dialogueMode==="joint"&&$("seed").value==="1234")$("seed").value="1235";
    if(state.dialogueMode==="director")state.roles.forEach((role,index)=>{if(!role.reference&&!role.mode){role.mode="ip";role.ip=index?state.voices.find(item=>item.id!=="灵小柔"&&item.language==="Chinese")?.id||"灵小柔":"灵小柔";}});
    document
      .querySelectorAll("[data-dialogue-mode]")
      .forEach((item) => item.classList.toggle("active", item === button));
    $("dialogue-help").textContent =
      state.dialogueMode === "joint"
        ? "所有角色一起生成，自然衔接。每位角色都需要参考录音与对应文字。"
        : "逐句生成后组合，适合单句重做与长篇制作。每一段的实际时间会保存在工程记录中。";
    updateTask();
    renderRoles();
    saveDraft();
  }),
);
bind("task", updateTask, "change");
bind("generate", generate);
bind("fill-example", () => {
  $("main-text").value =
    selectedTask() === "multilingual"
      ? "こんにちは。今日はとても良い天気です。"
      : "你好，很高兴在这里遇见你。让我们把今天的灵感，变成一段有温度的声音。";
  $("text-count").textContent = `${$("main-text").value.length} 字`;
  saveDraft();
});
bind("choose-voice", () => {
  state.catalogRole=null;
  $("voice-dialog").showModal();
  renderCatalog();
});
bind(
  "voice-search",
  () => {
    state.catalogLimit = 36;
    renderCatalog();
  },
  "input",
);
bind(
  "voice-filter",
  () => {
    state.catalogLimit = 36;
    renderCatalog();
  },
  "change",
);
bind("more-voices", () => {
  state.catalogLimit += 48;
  renderCatalog();
});
for (const id of ["voice-purpose", "voice-favorites-only"]) bind(id, () => {
  state.catalogLimit = 36;
  renderCatalog();
}, "change");
bind("preview-voice", () =>
  submit({
    operation: "generate",
    request: {
      task: "ip",
      text:
        state.voices.find((item) => item.id === state.voice)?.language ===
        "English"
          ? "Hello, it is lovely to meet you today."
          : "你好，很高兴遇见你。这是我的声音。",
      ip: state.voice,
    },
  }),
);
bind("upload-reference", () => $("reference-upload").click());
bind(
  "reference-upload",
  () => uploadReference($("reference-upload").files[0]),
  "change",
);
bind("record-reference", toggleRecording);
bind("transcribe-reference", () => transcribeReference());
bind("apply-crop", async () => {
  if (!state.reference) throw new Error("请先上传录音");
  const prepared = await api("/api/audio/prepare", {
    method: "POST",
    body: {
      path: state.reference.source_path || state.reference.path,
      start: Number($("crop-start").value),
      end: Number($("crop-end").value),
    },
  });
  state.reference = { ...state.reference, ...prepared };
  $("transcript").value = "";
  state.transcriptTouched = false;
  showReference();
  saveDraft();
  toast("已使用选中片段，请重新检查对应文字");
});
bind("clear-reference", () => {
  state.reference = null;
  $("reference-detail").hidden = true;
  $("transcript").value = "";
  saveDraft();
});
bind("save-reference", saveVoice);
bind("adopt-machine", () => {
  $("transcript").value = state.machineText;
  state.transcriptTouched = false;
  $("adopt-machine").hidden = true;
  saveDraft();
});
bind("choose-saved-voice", () => {
  state.voiceTarget = null;
  renderSaved();
  $("saved-dialog").showModal();
});
bind("new-voice", () => {
  $("task").value = "seed";
  setView("single");
  $("reference-fields").scrollIntoView({ behavior: "smooth" });
});
bind("add-role", addRole);
bind("add-line", addLine);
bind("preview-segments", () => previewSegments());
bind("batch-import", () => $("batch-file").click());
bind(
  "batch-file",
  async () => {
    const file = $("batch-file").files[0];
    if (file)
      await previewSegments({
        text: await file.text(),
        format: file.name.split(".").pop().toLowerCase(),
      });
  },
  "change",
);
bind("reset-defaults", () => {
  const values = {
    seed: state.view === "dialogue" ? 1235 : 1234,
    cfg: 2,
    "flow-steps": 10,
    temperature: 0,
    sigma: 0.25,
    "stop-threshold": 0.5,
    "log-every": 0,
    minimum: 0,
    maximum: 0,
  };
  for (const [id, value] of Object.entries(values)) $(id).value = value;
  saveDraft();
  toast("已恢复官方默认值");
});
bind("all-tags", () => {
  let dialog = $("tags-dialog");
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = "tags-dialog";
    dialog.innerHTML = `<div class="dialog-heading"><h2>全部声音标签</h2><button class="icon-button" id="tags-close">×</button></div><div class="voice-grid">${Object.entries(
      tags,
    )
      .map(
        ([tag, label]) =>
          `<button class="voice-option" data-tag="${tag}"><strong>${label}</strong><small>${tag}</small></button>`,
      )
      .join("")}</div>`;
    document.body.append(dialog);
    $("tags-close").onclick = () => dialog.close();
    dialog.addEventListener("click", (event) => {
      if (event.target.closest("[data-tag]")) dialog.close();
    });
  }
  dialog.showModal();
});
bind("show-history", () => setView("history"));
bind("cancel-job", async () => {
  stopStreaming();
  if (state.activeJob)
    await api(`/api/jobs/${state.activeJob}/cancel`, { method: "POST" });
  await refreshJobs();
});
bind("open-outputs", () => api("/api/folders/jobs", { method: "POST" }));
bind("open-data", () => api("/api/folders/jobs", { method: "POST" }));
bind("unload-models", async () => {
  await api("/api/models/unload", { method: "POST" });
  toast("模型显存已释放，下次生成会重新加载");
});
bind("settings-open", async () => {
  await refreshStatus();
  const settings = await api("/api/settings");
  $("settings-info").innerHTML =
    `<p class="field-note">整合包已配置好默认路径。复用已有模型时，可在这里填写对应文件或目录。</p>
     <label>主模型文件 / BF16目录<input id="settings-model" value="${esc(settings.model_path)}"></label>
     <div class="path-picker-actions"><button class="text-button" data-pick-kind="model_file" data-pick-target="settings-model">选择单文件模型…</button><button class="text-button" data-pick-kind="bf16_dir" data-pick-target="settings-model">选择BF16目录…</button></div>
     <label>辅助文件目录<input id="settings-assets" value="${esc(settings.assets_path)}"></label>
     <div class="path-picker-actions"><button class="text-button" data-pick-kind="assets_dir" data-pick-target="settings-assets">选择辅助文件目录…</button></div>
     <label>Confucius项目或组件目录<input id="settings-asr" value="${esc(settings.asr_root)}"></label>
     <div class="path-picker-actions"><button class="text-button" data-pick-kind="asr_dir" data-pick-target="settings-asr">选择Confucius目录…</button></div>
     <details><summary>识别选项：语言、热词与背景信息</summary>
       <label>识别语言<select id="asr-language">${["Auto","Chinese","English","Cantonese","Japanese","Korean","German","French","Spanish","Russian","Portuguese","Italian"].map(language=>`<option value="${language}" ${state.asrOptions.language===language?"selected":""}>${language==="Auto"?"自动检测":language}</option>`).join("")}</select></label>
       <label>热词<input id="asr-hotwords" placeholder="人名、产品名等，用逗号分隔" value="${esc(state.asrOptions.hotwords)}"></label>
       <label>识别背景<textarea id="asr-context" rows="2" placeholder="帮助识别专有名词的简短背景">${esc(state.asrOptions.context)}</textarea></label>
       <p class="field-note">用于参考录音、角色录音和成品字幕的下一次识别，不会改写已校对的文字。</p>
     </details>
     <label>计算方式<select id="settings-kernels"><option value="portable">兼容计算</option><option value="auto">原生CUDA加速（自动兼容）</option></select></label>
     <label>注意力计算<select id="settings-attention"><option value="sdpa">SDPA（当前实测推荐）</option><option value="auto">自动兼容</option><option value="flash_attention_2">FlashAttention 2（匹配轮子时可用）</option></select></label>
     <label class="check-label"><input type="checkbox" id="settings-graphs">CUDA Graph 加速（首次需预热）</label>
     <button class="button primary" id="settings-save">保存设置</button>
     <div class="settings-line">用户数据：${esc(state.status?.data_root)}</div>
     <div class="settings-line">Confucius：${state.status?.asr.available ? "原生组件已找到" : "需要匹配的原生组件"} · Python ${esc(state.status?.python)}</div>
     <div class="download-row"><button class="button quiet" id="download-models">下载 / 继续下载模型</button><button class="text-button" id="stop-model-download">停止本次下载</button></div>`;
  $("settings-kernels").value = settings.native_kernels;
  for (const button of $("settings-info").querySelectorAll("[data-pick-kind]")) button.onclick = run(async()=>{
    button.disabled=true;
    try {
      const result=await api("/api/paths/select",{method:"POST",body:{kind:button.dataset.pickKind,initial:$(button.dataset.pickTarget).value}});
      if(result.path)$(button.dataset.pickTarget).value=result.path;
    } finally {button.disabled=false;}
  });
  $("settings-attention").value=settings.attention_backend;$("settings-graphs").checked=settings.cuda_graphs;
  $("settings-save").onclick = run(async () => {
    await api("/api/settings", {method:"POST",body:{model_path:$("settings-model").value,assets_path:$("settings-assets").value,asr_root:$("settings-asr").value,native_kernels:$("settings-kernels").value,attention_backend:$("settings-attention").value,cuda_graphs:$("settings-graphs").checked}});
    state.asrOptions={language:$("asr-language").value,hotwords:$("asr-hotwords").value,context:$("asr-context").value};saveDraft();
    await refreshStatus(); toast("设置已保存，下次生成使用新的配置");
  });
  $("download-models").onclick = run(async () => {const result = await api("/api/models/download",{method:"POST"});toast(result.message);});
  $("stop-model-download").onclick = run(async () => {const result = await api("/api/models/download/cancel",{method:"POST"});toast(result.message);});
  $("settings-dialog").showModal();
});
bind("model-status", () => $("settings-open").click());
bind("project-save", saveProject);
bind("project-import", () => $("project-file").click());
bind(
  "project-file",
  async () => {
    const file = $("project-file").files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    await loadProject(
      await api("/api/projects/import", { method: "POST", body: form }),
    );
  },
  "change",
);
bind("create-subtitles", async () => {
  const job = state.jobs.find((item) => item.id === state.focusJob);
  if (!job?.result?.audio_file) throw new Error("请先完成一段语音作品");
  await submit({
    operation: "transcribe",
    audio_path: `${state.status.data_root}/jobs/${job.id}/${job.result.audio_file}`,
    subtitle_timings: true,
    ...state.asrOptions,
  });
});
$("reference-drop").addEventListener("dragover", (event) => {
  event.preventDefault();
  $("reference-drop").classList.add("dragging");
});
$("reference-drop").addEventListener("dragleave", () =>
  $("reference-drop").classList.remove("dragging"),
);
$("reference-drop").addEventListener(
  "drop",
  run(async (event) => {
    event.preventDefault();
    $("reference-drop").classList.remove("dragging");
    const file = event.dataTransfer.files[0];
    if (file) await uploadReference(file);
  }),
);
try {
  const favorites = JSON.parse(localStorage.getItem("ming-t8-favorite-voices-v1") || "[]");
  if (Array.isArray(favorites)) state.favoriteVoices = new Set(favorites.filter(id => typeof id === "string"));
} catch {}
restoreDraft();
updateTask();
showReference();
renderRoles();
await Promise.all([loadVoices(), refreshStatus(), refreshJobs()]);
setInterval(refreshJobs, 1100);
setInterval(refreshStatus, 5000);

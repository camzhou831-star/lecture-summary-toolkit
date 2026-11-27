// 总结工作台前端:新建 / 历史 / 阅读(总结、文字稿、日志)/ 播放器 + 章节。地址栏 #/t/<id> 记住当前任务
const $ = (s) => document.querySelector(s);
const ICON = {
  check: '<svg viewBox="0 0 24 24"><path d="M5 12l5 5L20 7"/></svg>',
  spin: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  dot: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="2" fill="currentColor"/></svg>',
};
const STAGES = ["fetch", "prepare", "summarize", "check", "names", "review"];
const stagesOf = (tpl, kind) => kind === "compare" ? ["prepare", "summarize", "check"]       // 横向对比:收集拆稿 → 写 → 核对
  : tpl === "shots" ? ["fetch", "prepare", "summarize", "check"]                                  // 画面拉片:下载视频 → 机测 → 逐镜头登记 → 核对
  : (!tpl || tpl === "course" || tpl === "breakdown" ? STAGES : STAGES.filter((k) => k !== "review")).filter((k) => !(kind === "slides" && k === "fetch"));   // 只有课件的任务没有「拿文字稿」   // 审核内容只有课程总结有
const kindName = (k) => t("kind_" + k);
const statusName = (s) => t("status_" + s);

let tasks = [];
let current = null;            // 当前任务
let rendered = {};             // 已渲染内容的任务 id:{summary, transcript}
let tab = "summary";

async function api(path, opt = {}) {
  const r = await fetch(path, opt);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return (r.headers.get("content-type") || "").includes("json") ? r.json() : r.text();
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const mmss = (sec) => `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;
const dur = (s) => s == null ? "" : s < 60 ? t("sec", { n: s }) : t("min_sec", { m: Math.floor(s / 60), s: Math.round(s % 60) });
function ago(ts) {
  const d = (Date.now() / 1000 - ts);
  if (d < 60) return t("just_now");
  if (d < 3600) return t("min_ago", { n: Math.floor(d / 60) });
  if (d < 86400) return t("hr_ago", { n: Math.floor(d / 3600) });
  const x = new Date(ts * 1000); return t("date", { m: x.getMonth() + 1, mon: MONTHS[x.getMonth()], d: x.getDate() });
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("on");
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("on"), 1600);
}

// ---------- 模板(第一期只有课程总结可用) ----------
const TEMPLATES = [
  { id: "course", key: "tpl_course", ready: true, icon: '<svg viewBox="0 0 24 24"><path d="M22 10 12 5 2 10l10 5 10-5z"/><path d="M6 12v5c3 2 9 2 12 0v-5"/></svg>',
  },
  { id: "breakdown", key: "tpl_bench", ready: true, icon: '<svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
  },
  { id: "shots", key: "tpl_shots", ready: true, icon: '<svg viewBox="0 0 24 24"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M7 5v14M17 5v14M2 10h5M2 14h5M17 10h5M17 14h5"/></svg>',
  },
  { id: "meeting", key: "tpl_meet", ready: true, icon: '<svg viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/></svg>',
  },
];
let template = "course";
let status = null, cfg = null, slidesFile = null;   // 首页检查结果、选好的课件 PDF(提前声明:drawTemplates → drawReady 一开始就会用到)
function tplCard(t, pick) {
  const tp = t;   // 模板对象(下面的 t() 是翻译函数)
  return ((t) => {
    const tag = tp.ready ? (pick && tp.id === template ? t("tag_selected") : t("tag_ready")) : t("tag_soon");
    return `<button type="button" class="tpl ${pick && tp.id === template ? "on" : ""}" data-tpl="${tp.id}" ${tp.ready ? "" : "disabled"}>
    <span class="tpl-tag">${tag}</span><span class="tpl-ic">${tp.icon}</span>
    <span class="tpl-n">${t(tp.key)}</span><span class="tpl-d">${t(tp.key + "_d")}</span>
    ${pick ? "" : `<ul>${t(tp.key + "_p").map((p) => `<li>${p}</li>`).join("")}</ul>`}</button>`;
  })(window.t);
}
let meetings = [], meetingVariant = "meeting.standard_meeting";
const tplId = () => template === "meeting" ? meetingVariant : template;   // 提交给后端的模板 id
function tplName(id) {
  if (!id || id === "course") return t("tpl_course");
  if (id === "shots") return t("tpl_shots");
  if (id === "breakdown") return t("tpl_bench");
  const m = meetings.find((x) => x.id === id);
  return t("tpl_meet") + (m ? " · " + (LANG === "zh" ? m.name_zh : m.name_en) : "");
}
function drawTemplates() {
  $("#tpl-pick").innerHTML = TEMPLATES.map((t) => tplCard(t, true)).join("");
  $("#tpl-list").innerHTML = TEMPLATES.map((t) => tplCard(t, false)).join("");
  document.querySelectorAll("#tpl-pick .tpl:not(:disabled)").forEach((b) => b.onclick = () => { template = b.dataset.tpl; drawTemplates(); drawSrcHint(); drawSlidesBtn(); });
  // 会议纪要:选中后在卡片下面选会议类型
  let row = $("#meet-row");
  if (!row) { row = document.createElement("div"); row.id = "meet-row"; row.className = "meet-row"; $("#tpl-pick").after(row); }
  row.hidden = template !== "meeting" || !meetings.length;
  row.innerHTML = `<label>${t("meet_type")}</label><select id="meet-type" class="select">${meetings.map((m) =>
    `<option value="${m.id}" ${m.id === meetingVariant ? "selected" : ""}>${esc(LANG === "zh" ? m.name_zh : m.name_en)} — ${esc(LANG === "zh" ? m.desc_zh : m.desc_en)}</option>`).join("")}</select>
    <span class="small muted">${(meetings.find((m) => m.id === meetingVariant) || {})[LANG === "zh" ? "sections_zh" : "sections_en"]?.join(" · ") || ""}</span>`;
  const sel = $("#meet-type"); if (sel) sel.onchange = () => { meetingVariant = sel.value; drawTemplates(); };
  drawHero(); drawReady();
}
api("/api/templates").then((x) => { meetings = x.meetings || []; drawTemplates(); }).catch(() => {});
drawTemplates();

// ---------- 模型状态 ----------
api("/api/config").then((c) => {
  cfg = c;
  drawModelCard(c);
});

const PNAME = { claude: "Claude Code", codex: "Codex", api: "API", harness: "DeepSeek Harness" };
function drawModelCard(c) {
  $("#model").innerHTML = c.ready
    ? `<span class="ok">${PNAME[c.active]}${c.active === "api" ? " · " + esc(c.model) : t("model_local")}${c.provider === "auto" ? t("model_auto") : ""}</span>`
    : `<span class="bad">${t("model_none")}</span>`;
}

// ---------- 路由:#/ 新建 · #/library 资料库 · #/templates 模板 · #/settings 设置 · #/t/<id> 任务 ----------
const PAGES = ["home", "library", "templates", "settings", "detail"];
const TITLES = { home: "nav_home", library: "nav_lib", templates: "nav_tpl", settings: "nav_set", detail: "title_detail" };
let shownPage = null;
function show(page) {
  PAGES.forEach((p) => $("#" + p).hidden = p !== page);
  document.querySelectorAll(".nav-item").forEach((a) => a.classList.toggle("on", a.dataset.page === page));
  $("#page-title").textContent = t(TITLES[page]);
  if (shownPage !== page) {   // 换页时:页面上浮淡入,卡片依次出现(TreeUI 的 200/300ms + easeOut)
    const el = $("#" + page);
    el.classList.remove("enter"); void el.offsetWidth; el.classList.add("enter");
    el.querySelectorAll(".tpl-grid, .cards, .steps").forEach((g) => { g.classList.remove("stagger"); void g.offsetWidth; g.classList.add("stagger"); });
    $(".main").scrollTop = 0;
  }
  shownPage = page;
}

// ---------- 顶栏:搜索(⌘K)、深浅色 ----------
$("#top-search").addEventListener("input", (e) => {
  lib.q = e.target.value.trim().toLowerCase(); $("#lib-search").value = e.target.value;
  if (location.hash !== "#/library") location.hash = "#/library"; else drawLibrary();
});
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#top-search").focus(); $("#top-search").select(); }
  if (e.key === "Escape" && document.activeElement === $("#top-search")) $("#top-search").blur();
});
function isDark() {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}
function drawThemeBtn() {
  $("#theme-btn").innerHTML = isDark()
    ? '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
    : '<svg viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
}
$("#theme-btn").onclick = () => {
  const next = isDark() ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("wb-theme", next); } catch (_) {}
  drawThemeBtn();
};
drawThemeBtn();

// ---------- 配色(设置页) ----------
const PALETTES = [
  { id: "sage", key: "pal_sage", sw: "linear-gradient(135deg, #c4dfcd, #f1ead8 55%, #d6deee)", dot: "#4f7f6f" },
  { id: "lavender", key: "pal_lav", sw: "linear-gradient(135deg, #d6cced, #f6dacd 55%, #e8d6e2)", dot: "#7a6aa8" },
  { id: "mist", key: "pal_mist", sw: "linear-gradient(135deg, #bedce8, #cee8d6 55%, #dce2f0)", dot: "#3e7c94" },
];
function drawPalettes() {
  const cur = document.documentElement.dataset.palette || "sage";
  $("#palettes").innerHTML = PALETTES.map((p) => `<button type="button" class="palette ${p.id === cur ? "on" : ""}" data-p="${p.id}">
    <span class="sw" style="background:${p.sw}; box-shadow: inset -14px 0 0 -8px ${p.dot}"></span>
    <b>${t(p.key)}</b><small>${t(p.key + "_d")}</small></button>`).join("");
  document.querySelectorAll(".palette").forEach((b) => b.onclick = () => {
    document.documentElement.dataset.palette = b.dataset.p;
    try { localStorage.setItem("wb-palette", b.dataset.p); } catch (_) {}
    drawPalettes(); toast(t("pal_changed", { n: t(PALETTES.find((x) => x.id === b.dataset.p).key) }));
  });
}
function route() {
  const h = location.hash;
  const m = h.match(/^#\/t\/(\d+)/);
  if (m) return openTask(+m[1]);
  current = null; drawList();
  if (h === "#/library") { show("library"); drawLibrary(); }
  else if (h === "#/templates") show("templates");
  else if (h === "#/settings") { show("settings"); drawSettings(); }
  else { show("home"); drawOnboard(); setTimeout(() => $("#source").focus(), 0); }
}
window.addEventListener("hashchange", route);

// ---------- 新建 ----------
$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const source = $("#source").value.trim();
  if (!source && !(slidesFile && template === "course")) return $("#source").focus();   // 只附了课件也能开始:只根据课件写复习笔记
  formMsg(t("submitting"));
  try {
    const slides = await sendSlides();
    const t = await api("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, lang: $("#lang").value, out_lang: $("#out_lang").value, template: tplId(), slides }) });
    $("#source").value = ""; formMsg(""); setSlides(null);
    await refresh(); location.hash = `#/t/${t.id}`;
  } catch (err) { formMsg(trServer(err.message), true); }
});
$("#source").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("#form").requestSubmit(); });
$("#file").addEventListener("change", () => { if ($("#file").files[0]) upload($("#file").files[0]); });
function formMsg(s, bad) { const m = $("#formmsg"); m.textContent = s; m.classList.toggle("bad", !!bad); }

// 课件 PDF(只给课程总结):先选好,提交任务时先传课件、拿到文件名再建任务
function setSlides(f) {
  slidesFile = f; $("#slides").value = "";
  const chip = $("#slides-chip");
  chip.hidden = !f; if (f) chip.querySelector(".nm").textContent = f.name;
  drawReady(); drawSrcHint();
}
function drawSlidesBtn() { const on = template === "course"; $("#slides-btn").hidden = !on; if (!on) setSlides(null); }
$("#slides").addEventListener("change", () => { const f = $("#slides").files[0]; if (f) setSlides(f); });
$("#slides-chip .x").onclick = () => setSlides(null);
async function sendSlides() {
  if (!slidesFile || template !== "course") return "";
  const fd = new FormData(); fd.append("file", slidesFile);
  formMsg(t("uploading", { n: slidesFile.name }));
  return (await api("/api/slides", { method: "POST", body: fd })).slides;
}

async function upload(f) {
  if (/\.(pdf|pptx)$/i.test(f.name)) { if (template === "course") { setSlides(f); formMsg(""); } else formMsg(t("slides_course_only"), true); return; }
  try {
    const slides = await sendSlides();
    const fd = new FormData();
    fd.append("file", f); fd.append("lang", $("#lang").value); fd.append("out_lang", $("#out_lang").value); fd.append("template", tplId()); fd.append("slides", slides);
    formMsg(t("uploading", { n: f.name }));
    const task = await api("/api/upload", { method: "POST", body: fd });
    formMsg(""); $("#file").value = ""; setSlides(null);
    await refresh(); location.hash = `#/t/${task.id}`;
  } catch (err) { formMsg(trServer(err.message), true); }
}
// 拖文件进新建页
let dragDepth = 0;
const home = $("#home");
home.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; $("#drop").classList.add("on"); });
home.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("#drop").classList.remove("on"); } });
home.addEventListener("dragover", (e) => e.preventDefault());
home.addEventListener("drop", (e) => {
  e.preventDefault(); dragDepth = 0; $("#drop").classList.remove("on");
  const f = e.dataTransfer.files[0]; if (f) upload(f);
});

// ---------- 左栏最近任务 ----------
async function refresh() {
  tasks = await api("/api/tasks"); drawList();
  $("#nav-count").textContent = tasks.length || "";
  drawTabTitle();
  if (!$("#library").hidden) drawLibrary();
}
function drawList() {
  const list = tasks.slice(0, 8);
  $("#tasks").innerHTML = list.map((t) => `
    <li class="task ${current && t.id === current.id ? "on" : ""}" data-id="${t.id}" title="${esc(t.title || t.vid)}">
      <span class="s-dot ${t.status}"></span>
      <span class="t-title">${esc(t.title || t.vid)}</span>
      <span class="t-sub">${siteName(t)} · ${t.status === "done" ? ago(t.updated_at) : esc(t.status === "running" ? trServer(t.message) : statusName(t.status))}</span>
    </li>`).join("") || `<li class="task-empty">${window.t("no_tasks")}</li>`;
  document.querySelectorAll(".task[data-id]").forEach((li) => li.onclick = () => { location.hash = `#/t/${li.dataset.id}`; });
}

// ---------- 资料库 ----------
const lib = { q: "", kind: "", status: "" };
$("#lib-search").addEventListener("input", (e) => { lib.q = e.target.value.trim().toLowerCase(); drawLibrary(); });
for (const [id, key] of [["#lib-kind", "kind"], ["#lib-status", "status"]]) {
  document.querySelectorAll(`${id} button`).forEach((b) => b.onclick = () => {
    lib[key] = b.dataset.v;
    document.querySelectorAll(`${id} button`).forEach((x) => x.classList.toggle("on", x === b));
    drawLibrary();
  });
}
function drawLibrary() {
  const rows = tasks.filter((t) => (!lib.q || (t.title || t.vid || "").toLowerCase().includes(lib.q))
    && (!lib.kind || t.kind === lib.kind)
    && (!lib.status || t.status === lib.status || (lib.status === "running" && t.status === "queued")));
  $("#lib-rows").innerHTML = rows.map((t) => {
    const total = Object.values(t.timings || {}).reduce((a, b) => a + b, 0);
    const st = t.status === "done" && !t.check_ok ? ["warn", window.t("done_warn")] : [t.status, statusName(t.status)];
    return `<tr data-id="${t.id}">
      <td class="t-cell" title="${esc(t.title || t.vid)}">${esc(t.title || t.vid)}<div class="small muted">${esc(tplName(t.template))}</div></td>
      <td>${siteName(t)}</td>
      <td>${window.t(t.out_lang === "en" ? "l_en" : "l_zh")}</td>
      <td><span class="badge ${st[0]}">${st[1]}</span></td>
      <td class="num">${t.status === "done" ? dur(Math.round(total)) : "—"}</td>
      <td class="muted">${ago(t.created_at)}</td></tr>`;
  }).join("") || `<tr><td colspan="6" class="table-empty">${t(tasks.length ? "lib_none" : "lib_empty")}</td></tr>`;
  document.querySelectorAll("#lib-rows tr[data-id]").forEach((tr) => tr.onclick = () => { location.hash = `#/t/${tr.dataset.id}`; });
}

// ---------- 设置 ----------
function providerNote(p) {   // 后端给的"不可用原因"是中文,这里按情况重写
  if (p.ok) return "";
  if (p.id === "harness") return t(/没登录/.test(p.note || "") ? "p_harness_login" : /安装盘/.test(p.note || "") ? "p_harness_dmg" : "p_harness_missing");
  return p.id === "api" ? t("p_no_key") : t("p_not_found", { c: p.id });
}
function drawProviders(c) {
  const opts = [{ id: "auto", ok: c.ready, note: c.ready ? t("p_auto_now", { n: PNAME[c.active] }) : t("p_auto_none") }, ...c.providers];
  $("#providers").innerHTML = opts.map((p) => `<button type="button" class="provider ${c.provider === p.id ? "on" : ""}" data-p="${p.id}">
    <span class="radio"></span><b>${t("p_" + p.id)}</b>
    <span class="badge ${p.ok ? "done" : "failed"}">${t(p.ok ? "p_ok" : "p_no")}</span>
    <small>${p.id === "auto" ? t("p_auto_d") + " · " + esc(p.note) : t("p_" + p.id + "_d") + (p.ok ? "" : " · " + esc(providerNote(p)))}</small></button>`).join("");
  document.querySelectorAll(".provider").forEach((b) => b.onclick = async () => {
    const nc = await api("/api/config/provider", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: b.dataset.p }) });
    drawProviders(nc); drawModelCard(nc); toast(t("saved"));
  });
  const sel = $("#cookies-browser");
  sel.innerHTML = [["", t("cookies_off")], ...c.browsers.map((b) => [b, b[0].toUpperCase() + b.slice(1)])]
    .map(([v, n]) => `<option value="${v}" ${v === c.cookies_browser ? "selected" : ""}>${v ? t("cookies_use", { b: n }) : n}</option>`).join("");
  sel.onchange = async () => {
    await api("/api/config/cookies", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ browser: sel.value }) });
    toast(t(sel.value ? "cookies_saved" : "cookies_closed"));
  };
}

async function drawSettings() {
  drawPalettes();
  const [c, s] = await Promise.all([api("/api/config"), api("/api/status")]);
  const ok = '<svg viewBox="0 0 24 24"><path d="M5 12l5 5L20 7"/></svg>', no = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>';
  drawProviders(c);
  $("#cfg-path").textContent = s.config_file;
  $("#set-key").innerHTML = `<div class="keyline"><span>${c.key_ok ? t("key_have", { s: esc(c.key_source) }) : t("key_empty")}</span>
    ${c.key_ok ? `<button type="button" class="btn btn-ghost btn-sm" id="key-clear">${t("key_clear")}</button>` : `<a href="/guide/deepseek" target="_blank" rel="noopener">${t("ob_ds_guide")}</a> · <a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener">${t("ob_ds_link")} ↗</a>`}</div>${keyForm("set")}`;
  if (c.key_ok) $("#key-clear").onclick = async () => {
    try { cfg = await api("/api/config/key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: "" }) }); toast(t("key_cleared")); drawSettings(); }
    catch (err) { toast(trServer(err.message)); }
  };
  const NEED = { "yt-dlp": "tool_ytdlp", ffmpeg: "tool_ffmpeg", ffprobe: "tool_ffprobe", "whisper-cli": "tool_whisper", tesseract: "tool_tess" };
  $("#set-tools").innerHTML = s.tools.map((x) => `<li><span class="ck ${x.path ? "ok" : "no"}">${x.path ? ok : no}</span>
    <span>${esc(x.name.replace("whisper 模型", "whisper model"))}</span><span class="sub">${t(NEED[x.name] || "tool_model")}${x.path ? " · " + esc(x.path) : " · " + t("not_found")}</span></li>`).join("");
  const n = s.counts, total = Object.values(n).reduce((a, b) => a + b, 0);
  $("#set-data").innerHTML = `<dt>${t("data_tasks")}</dt><dd>${t("data_count", { t: total, d: n.done || 0, f: n.failed || 0 })}</dd>
    <dt>${t("data_dir")}</dt><dd><code>${esc(s.data_dir)}</code></dd><dt>${t("data_note_k")}</dt><dd class="muted">${t("data_note")}</dd>`;
}

// ---------- 详情 ----------
async function openTask(id) {
  let t;
  try { t = await api(`/api/tasks/${id}`); } catch (_) { location.hash = ""; return; }
  const switched = !current || current.id !== id;
  current = t;
  if (switched) {
    rendered = {}; setTab("summary");
    $("#player").innerHTML = `<div class="player-empty"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg><span>${window.t("player_empty")}</span></div>`;
    $("#chapters").innerHTML = "";
    $("#d-log").textContent = "";
  }
  show("detail");
  drawList(); drawDetail(t);
  if (switched && t.kind === "local" && t.meta && t.meta.media_path) loadLocal(t);
}

function drawDetail(t) {
  $("#d-title").textContent = t.title || t.vid;
  $("#d-kind").textContent = siteName(t);
  $("#d-time").innerHTML = esc(tplName(t.template) + " · " + window.t("sum_lang", { l: window.t(t.out_lang === "en" ? "l_en" : "l_zh"), ago: ago(t.created_at) }))
    + (t.meta && t.meta.derived_from ? ` · <a href="#/t/${+t.meta.derived_from}">${esc(window.t("derived_from", { n: t.meta.derived_from }))}</a>` : "");
  $("#d-open").hidden = t.kind === "local"; if (t.kind !== "local") $("#d-open").href = t.source;
  const done = t.status === "done";
  $("#d-copy").disabled = $("#d-download").disabled = !done;
  $("#d-retry").disabled = $("#d-del").disabled = t.status === "running";

  const tr = window.t;
  $("#cmp-wrap").hidden = !(t.template === "breakdown" && t.status === "done");
  const stages = stagesOf(t.template, t.kind);
  $("#steps").style.gridTemplateColumns = innerWidth > 980 ? `repeat(${stages.length}, 1fr)` : "";
  $("#steps").innerHTML = stages.map((k, i) => {
    const ok = t.timings[k] != null && !(t.status !== "done" && t.stage === k);
    const now = t.status === "running" && t.stage === k;
    const bad = t.status === "failed" && t.stage === k;
    const cls = bad ? "bad" : now ? "now" : ok ? "done" : "";
    const ic = bad ? ICON.x : now ? ICON.spin : ok ? ICON.check : `<b style="font-size:12px">${i + 1}</b>`;
    const tm = bad ? tr("step_failed") : now ? tr("step_now") : ok ? dur(t.timings[k]) : t.status === "queued" && i === 0 ? tr("step_queued") : tr("step_wait");
    const nm = t.template === "shots" && ["fetch", "prepare", "summarize"].includes(k) ? tr("st_" + k + "_v") : tr("st_" + k);
    return `<div class="step ${cls}"><span class="ic">${ic}</span><div><div class="nm">${nm}</div><div class="tm">${tm}</div></div></div>`;
  }).join("");

  const st = $("#d-status");
  st.className = "status-line " + (t.status === "failed" ? "bad" : done ? (t.check_ok ? "ok" : "warn") : "");
  st.textContent = trServer(t.message);
  drawTip(t);

  const pre = $("#d-log");
  const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  if (pre.textContent !== t.log) { pre.textContent = t.log || ""; if (atBottom) pre.scrollTop = pre.scrollHeight; }
  drawNames(t);
  drawReview(t);
  const ck = $("#d-check");
  ck.className = "callout " + (t.check_report ? (t.check_ok ? "ok" : "bad") : "");
  ck.textContent = t.check_report || "";
  $("#check-dot").className = "dot " + (t.check_report ? (t.check_ok ? "ok" : "bad") : "");

  if (done && !rendered.summary) loadSummary(t);
  else if (!done) {
    rendered.summary = false;
    $("#summary").innerHTML = t.status === "failed"
      ? `<div class="empty-pane">${tr("failed_pane")}</div>`
      : `<div class="skeleton">${"<i></i>".repeat(8).replace(/<i><\/i>/g, (m, i) => `<i style="width:${60 + ((i * 37) % 40)}%"></i>`)}</div>`;
    if (!$("#chapters").children.length) $("#chapters").innerHTML = `<li class="chapters-empty">${tr("chapters_wait")}</li>`;
  }
  if (tab === "transcript" && !rendered.transcript) loadTranscript(t);
}

// ---------- 标签页 ----------
document.querySelectorAll(".tab").forEach((b) => b.onclick = () => { setTab(b.dataset.tab); if (current && tab === "transcript" && !rendered.transcript) loadTranscript(current); });
function setTab(name) {
  tab = name;
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  $("#summary").hidden = name !== "summary"; $("#transcript").hidden = name !== "transcript"; $("#logpane").hidden = name !== "log";
}

// ---------- 总结 ----------
const TS = /(?<![\d:])(\d{1,3}):([0-5]\d)(?![\d:])/g;
async function loadSummary(t) {
  rendered.summary = true;
  const md = await api(`/api/tasks/${t.id}/summary`);
  rendered.md = md;
  // breaks:引用块里"讲者 / 链接 / 时长"一行一条,不并成一段
  const html = window.marked ? marked.parse(md, { breaks: true }) : `<pre>${esc(md)}</pre>`;
  const box = $("#summary");
  box.innerHTML = window.DOMPurify ? DOMPurify.sanitize(html) : html;
  box.querySelectorAll("a").forEach((a) => {
    const m = a.textContent.trim().match(/^\[?(\d{1,3}):([0-5]\d)\]?$/);
    if (m) { a.dataset.t = +m[1] * 60 + +m[2]; a.classList.add("ts"); }
    else { a.target = "_blank"; a.rel = "noopener"; }
  });
  linkify(box);
  enhance(box, md, t.template || "course");
  drawChapters(md, t.template);
}

// ---------- 总结排版增强(只改网页显示,导出的 Markdown 不变) ----------
// 参考脚本 / 视频结构分析工具的通行做法:分色时间轴 + 分段卡片 + 指标数字块,原句单独做引用
const ROLE_COLOR = {
  "钩子": "#d9a03f", "Hook": "#d9a03f", "承诺": "#9a7fd0", "Promise": "#9a7fd0", "背景": "#98a49e", "Context": "#98a49e",
  "转折": "#d47a8c", "Turn": "#d47a8c", "举例": "#4c9a88", "Example": "#4c9a88", "论证": "#5a86c2", "Argument": "#5a86c2",
  "清单": "#69a35e", "Takeaway list": "#69a35e", "结尾": "#7a8794", "Ending": "#7a8794", "广告": "#e07b4a", "Sponsor": "#e07b4a",
  "其他": "#c4cbc6", "Other": "#c4cbc6",
};
const roleColor = (r) => ROLE_COLOR[r] || ROLE_COLOR[Object.keys(ROLE_COLOR).find((k) => r.startsWith(k))] || "#b5bdb8";
function mdSection(md, re) {   // 某个 ## 小节的全部行(到下一个 ## 为止)
  const lines = md.split("\n"), i = lines.findIndex((l) => re.test(l));
  if (i < 0) return [];
  const out = [];
  for (const l of lines.slice(i + 1)) { if (l.startsWith("## ")) break; out.push(l); }
  return out;
}
const mdRows = (lines) => lines.filter((l) => /^\|/.test(l.trim()) && !/^\|\s*-{2,}/.test(l.trim()))
  .map((l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
const secOf = (s) => { const m = String(s).match(/(\d{1,3}):(\d{2})/); return m ? +m[1] * 60 + +m[2] : null; };
const tsLink = (sec) => `<a class="ts" href="#" data-t="${sec}">${mmss(sec)}</a>`;
function sectionNodes(box, re) {   // 某个 h2 后面、下一个 h2 之前的所有元素
  const h = [...box.querySelectorAll("h2")].find((x) => re.test(x.textContent.trim()));
  if (!h) return null;
  const nodes = [];
  for (let n = h.nextElementSibling; n && n.tagName !== "H2"; n = n.nextElementSibling) nodes.push(n);
  return { h, nodes };
}

function enhance(box, md, tpl) {
  // 1. 所有表格:包一层可横向滚动的框,短的数字 / 时间格不换行
  box.querySelectorAll("table").forEach((tb) => {
    if (!tb.parentElement.classList.contains("md-table")) { const w = document.createElement("div"); w.className = "md-table"; tb.replaceWith(w); w.appendChild(tb); }
    tb.querySelectorAll("td, th").forEach((c) => { const x = c.textContent.trim(); if (x.length <= 18 && /^[\s\d.,:%\[\]–~\-+秒分sxXhm/]*$/.test(x)) c.classList.add("num"); });
  });
  // 2. 列表项以加粗开头(如章节时间线 "**[00:12] 开场** — 摘要"):加粗部分单独成一行,去掉后面的破折号 / 冒号
  box.querySelectorAll("li").forEach((li) => {
    const f = li.firstElementChild;
    if (!f || f.tagName !== "STRONG" || li.firstChild !== f && !(li.firstChild.nodeType === 3 && !li.firstChild.nodeValue.trim())) return;
    const nx = f.nextSibling;
    if (nx && nx.nodeType === 3) nx.nodeValue = nx.nodeValue.replace(/^\s*[—–\-:：]\s*/, "");
    li.classList.add("lead-li");
  });
  // 3. 单独一行、以冒号结尾的短段落("收藏点:""借鉴边界:")当小标题
  box.querySelectorAll("p").forEach((p) => { const x = p.textContent.trim(); if (x.length <= 16 && /[：:]$/.test(x)) { p.classList.add("sub-h"); p.textContent = x.replace(/[：:]$/, ""); } });
  if (tpl === "breakdown") enhanceBreakdown(box, md);
}

function enhanceBreakdown(box, md) {
  // 分段表 → 分色时间轴 + 分段卡片
  const seg = sectionNodes(box, /^(3\.|3 )/), rows = mdRows(mdSection(md, /^## 3\./)).slice(1);
  if (seg && rows.length) {
    const items = rows.map((r) => {
      const [k, role, time, secs, share, words, wpm, points, ...note] = r;
      const [a, b] = (time.match(/\d{1,3}:\d{2}/g) || []).map(secOf);
      return { k, role, a, b, secs: parseFloat(secs) || 0, share, words, wpm, points, note: note.join("|") };
    });
    const roles = [...new Set(items.map((x) => x.role))];
    const unit = LANG === "zh" ? { s: "秒", w: "字/分", p: "个信息点" } : { s: "s", w: "wpm", p: "points" };
    const html = `<div class="seg-viz">
      <div class="seg-bar">${items.map((x) => `<button type="button" class="seg-piece" data-seek="${x.a ?? 0}" style="flex:${Math.max(x.secs, 0.5)};--c:${roleColor(x.role)}"
        title="${esc(`${x.k}. ${x.role} ${x.a != null ? mmss(x.a) : ""}–${x.b != null ? mmss(x.b) : ""} · ${x.share}`)}"></button>`).join("")}</div>
      <div class="seg-legend">${roles.map((r) => `<span><i style="--c:${roleColor(r)}"></i>${esc(r)}</span>`).join("")}</div>
      <ol class="seg-cards">${items.map((x) => `<li class="seg-card" style="--c:${roleColor(x.role)}">
        <div class="seg-top"><span class="seg-no">${esc(x.k)}</span><span class="role-chip">${esc(x.role)}</span>
          <span class="seg-time">${x.a != null ? tsLink(x.a) : ""}<span class="dash">–</span>${x.b != null ? tsLink(x.b) : ""}</span>
          <span class="seg-stats"><b>${esc(String(x.secs))}</b>${unit.s}<em>·</em><b>${esc(x.share)}</b><em>·</em><b>${esc(x.wpm)}</b> ${unit.w}<em>·</em><b>${esc(x.points)}</b> ${unit.p}</span></div>
        ${x.note ? `<p class="seg-note">${esc(x.note)}</p>` : ""}</li>`).join("")}</ol></div>`;
    const target = seg.nodes.find((n) => n.classList.contains("md-table") || n.tagName === "TABLE");
    if (target) { target.insertAdjacentHTML("beforebegin", html); target.remove(); }
  }
  // 全片指标 → 数字块
  const met = sectionNodes(box, /^(4\.|4 )/), mr = mdRows(mdSection(md, /^## 4\./));
  if (met && mr.length >= 2) {
    const [head, vals] = mr;
    const tiles = head.map((h, i) => {
      const v = (vals[i] || "").replace(/\[(\d{1,3}:\d{2})\]/, "$1");
      const sec = /^\d{1,3}:\d{2}$/.test(v) ? secOf(v) : null;
      return `<div class="kpi"><span class="kpi-k">${esc(h)}</span><span class="kpi-v">${sec != null ? tsLink(sec) : esc(v)}</span></div>`;
    }).join("");
    const target = met.nodes.find((n) => n.classList.contains("md-table") || n.tagName === "TABLE");
    if (target) { target.insertAdjacentHTML("beforebegin", `<div class="kpis">${tiles}</div>`); target.remove(); }
  }
  // 逐段要点 / 可学的写法 / 收藏点:每条拆成「标题 · 说明 · 原句引用」
  for (const re of [/^(5\.|5 )/, /^(6\.|6 )/, /^(7\.|7 )/]) {
    const sec = sectionNodes(box, re);
    if (!sec) continue;
    sec.nodes.forEach((n) => n.querySelectorAll?.(":scope > li").forEach(splitPoint));
  }
}

const QUOTE = /(?:关键原句|原句|如|例如|e\.g\.|Key quote|Quote)?\s*[:：]?\s*["“「]([^"”」]{2,260})["”」]\s*(<a class="ts"[^>]*>[^<]*<\/a>)/g;
function splitPoint(li) {
  let html = li.innerHTML.trim(), title = "", tag = "", range = "";
  // 段号开头:"段1(1–18)标题:" 或 "**段1 · 标题**(第 1–18 句):"
  let m = html.match(/^(?:<strong>)?\s*(段\s*\d+|Segment\s*\d+)\s*(?:[·.]\s*)?([^（(<：:]{0,40}?)\s*(?:<\/strong>)?\s*[（(]\s*(?:第|sentences?)?\s*([\d\s–\-~]+)\s*(?:句|sentences?)?\s*[)）]\s*([^：:<]{0,40}?)\s*[：:]\s*/i);
  if (m) { tag = m[1].replace(/\s+/g, ""); title = (m[2] || m[4] || "").trim(); range = m[3].trim(); html = html.slice(m[0].length); }
  else if ((m = html.match(/^<strong>([^<]{1,40})<\/strong>\s*[：:—–-]?\s*/))) { title = m[1].replace(/[：:]$/, ""); html = html.slice(m[0].length); }
  else if ((m = html.match(/^([^<：:。]{2,26})[：:]\s*/))) { title = m[1]; html = html.slice(m[0].length); }
  const quotes = [];
  html = html.replace(QUOTE, (all, q, ts) => { quotes.push(`<blockquote class="pq"><span>“${q}”</span>${ts}</blockquote>`); return ""; });
  // 新格式把原句放在列表项里的引用块中;原句取走后剩下的空引用块去掉
  html = html.replace(/<blockquote>\s*(?:<p>)?\s*(?:关键原句|原句|Key quote|Quote)?\s*[：:]?\s*(?:<\/p>)?\s*<\/blockquote>/gi, "");
  html = html.replace(/(?:关键原句|如|例如)?\s*[、,，。;；]*\s*$/, "").replace(/^[\s、,，。]+/, "").trim();
  if (!title && !quotes.length) return;
  li.classList.add("pt");
  li.innerHTML = (title || tag ? `<div class="pt-head">${tag ? `<span class="pt-tag">${esc(tag)}</span>` : ""}${title ? `<b>${title}</b>` : ""}${range ? `<span class="pt-range">${LANG === "zh" ? "第 " + esc(range) + " 句" : "sentences " + esc(range)}</span>` : ""}</div>` : "")
    + (html ? `<div class="pt-body">${html}</div>` : "") + quotes.join("");
}
function linkify(box) {   // 正文里其余的时间戳也变成可点的
  const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT), nodes = [];
  while (walker.nextNode()) {
    const n = walker.currentNode;
    if (n.parentElement.closest("a, code, pre")) continue;
    TS.lastIndex = 0; if (TS.test(n.nodeValue)) nodes.push(n);
  }
  nodes.forEach((n) => {
    const span = document.createElement("span");
    span.innerHTML = esc(n.nodeValue).replace(/\[(\d{1,3}:\d{2})\]/g, "$1").replace(TS, (s, m, ss) => `<a class="ts" href="#" data-t="${+m * 60 + +ss}">${s}</a>`);
    n.replaceWith(...span.childNodes);
  });
}
// 点时间戳:页面内播放;按住 ⌘/Ctrl 在原站打开
document.addEventListener("click", (e) => {
  const a = e.target.closest("a.ts, [data-seek]");
  if (!a || !current) return;
  e.preventDefault();
  const sec = +(a.dataset.t ?? a.dataset.seek);
  if (e.metaKey || e.ctrlKey) { const u = jumpUrl(current, sec); if (u) window.open(u, "_blank", "noopener"); return; }
  seek(current, sec);
});

function drawChapters(md, tpl = "course") {
  const lines = md.split("\n"); let inTl = false; const items = [];
  $(".chapter-card .panel-title span").textContent = t(tpl === "breakdown" ? "seg_chapters" : "chapters");
  if (tpl === "breakdown") {   // 对标拆稿:分段表的每一段当一个"章节"
    let inSeg = false;
    for (const l of lines) {
      if (l.startsWith("## ")) inSeg = /^## 3\./.test(l);
      const m = inSeg && l.match(/^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*\[(\d{1,3}):(\d{2})\][^|]*\|(?:[^|]*\|){5}\s*([^|]*?)\s*\|\s*$/);
      if (m) items.push({ t: +m[3] * 60 + +m[4], name: `${m[1]}. ${m[2]}`, desc: m[5] });
    }
  } else if (tpl.startsWith("meeting")) {
    $("#chapters").innerHTML = `<li class="chapters-empty">${t("no_chapters_tpl")}</li>`; return;
  }
  for (const l of tpl === "breakdown" ? [] : lines) {
    if (l.startsWith("## ")) inTl = /章节时间线|Timeline/.test(l);
    else if (inTl && l.startsWith("- ")) {
      const m = l.match(/\[(\d{1,3}):(\d{2})\]/);
      if (!m) continue;
      const plain = l.replace(/\]\(<[^>]*>\)|\]\([^)]*\)/g, "]").replace(/\*\*/g, "");
      const rest = plain.replace(/^-\s*\[\d{1,3}:\d{2}\]\s*/, "");
      const [name, ...desc] = rest.split(/\s+[—–-]{1,2}\s+/);
      items.push({ t: +m[1] * 60 + +m[2], name: name.trim(), desc: desc.join(" — ").trim() });
    }
  }
  $("#chapters").innerHTML = items.map((c) =>
    `<li class="chapter" data-seek="${c.t}"><span class="c-t">${mmss(c.t)}</span><span class="c-n">${esc(c.name)}</span>${c.desc ? `<span class="c-d">${esc(c.desc)}</span>` : ""}</li>`
  ).join("") || `<li class="chapters-empty">${t("chapters_none")}</li>`;
}
function markChapter(sec) {
  let best = null;
  document.querySelectorAll(".chapter").forEach((li) => { li.classList.remove("on"); if (+li.dataset.seek <= sec) best = li; });
  if (best) { best.classList.add("on"); best.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
}

// ---------- 文字稿 ----------
async function loadTranscript(t) {
  rendered.transcript = true;
  const box = $("#transcript");
  try {
    const srt = await api(`/api/tasks/${t.id}/transcript`);
    const rows = [];
    for (const b of srt.replace(/\r/g, "").split(/\n\s*\n/)) {
      const ls = b.trim().split("\n"); const i = ls.findIndex((l) => l.includes("-->"));
      if (i < 0) continue;
      const m = ls[i].match(/(\d+):(\d+):(\d+)/); const text = ls.slice(i + 1).join(" ").replace(/<[^>]+>/g, "").trim();
      if (m && text) rows.push([+m[1] * 3600 + +m[2] * 60 + +m[3], text]);
    }
    box.innerHTML = rows.map(([s, x]) => `<div class="tr-line"><a class="ts" href="#" data-t="${s}">${mmss(s)}</a><span>${esc(x)}</span></div>`).join("")
      || `<div class="empty-pane">${window.t("transcript_empty")}</div>`;
  } catch (err) { rendered.transcript = false; box.innerHTML = `<div class="empty-pane">${esc(trServer(err.message))}</div>`; }
}

// ---------- 播放器 ----------
function jumpUrl(t, sec) {
  if (t.kind === "youtube") return `${t.source}&t=${sec}s`;
  if (t.kind === "bilibili") return `${t.source}${t.source.includes("?") ? "&" : "?"}t=${sec}`;
  if (t.kind === "web") {
    const base = t.source.split("#")[0], low = base.toLowerCase();
    if (low.includes("twitch.tv/videos/")) return `${base}${base.includes("?") ? "&" : "?"}t=${Math.floor(sec / 3600)}h${Math.floor(sec % 3600 / 60)}m${sec % 60}s`;
    if (low.includes("vimeo.com/")) return `${base}#t=${sec}s`;
    return `${base}#t=${sec}`;
  }
  return null;
}
function loadLocal(t) {
  $("#player").innerHTML = `<video controls preload="metadata" src="/api/tasks/${t.id}/media"></video>`;
  $("#player video").addEventListener("timeupdate", (e) => markChapter(e.target.currentTime));
}
function seek(t, sec) {
  const box = $("#player");
  if (t.kind === "local") {
    if (!box.querySelector("video")) { if (!(t.meta && t.meta.media_path)) return toast(window.t("no_media")); loadLocal(t); }
    const v = box.querySelector("video"); v.currentTime = sec; v.play();
  } else if (t.kind === "web") {
    const u = jumpUrl(t, sec);
    box.innerHTML = `<div class="player-link"><span>${window.t("web_player")}</span><a href="${esc(u)}" target="_blank" rel="noopener">${window.t("web_open", { t: mmss(sec) })}</a>
      <span class="small">${window.t("web_note", { t: mmss(sec) })}</span></div>`;
  } else {
    let src;
    if (t.kind === "youtube") src = `https://www.youtube.com/embed/${t.vid}?start=${sec}&autoplay=1`;
    else { const [bv, p] = t.vid.split("_p"); src = `https://player.bilibili.com/player.html?bvid=${bv}&p=${p || 1}&t=${sec}&autoplay=1&high_quality=1`; }
    box.innerHTML = `<iframe src="${src}" allow="autoplay; encrypted-media; fullscreen" allowfullscreen></iframe>`;
  }
  markChapter(sec);
  box.classList.remove("flash"); void box.offsetWidth; box.classList.add("flash");   // 播放器闪一圈蓝光,提示"跳到这里了"
  if (window.matchMedia("(max-width: 1100px)").matches) box.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------- 操作 ----------
$("#d-copy").onclick = async () => {
  try { await navigator.clipboard.writeText(rendered.md || await api(`/api/tasks/${current.id}/summary`)); toast(t("copied")); }
  catch (_) { toast(t("copy_fail")); }
};
$("#d-download").onclick = () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([rendered.md || ""], { type: "text/markdown" }));
  a.download = `${(current.title || current.vid).replace(/[\\/:*?"<>|]+/g, "_")}.md`; a.click();
};
// 换个用途:用已有文字稿换模板 / 语言再出一份(新任务)
function drawDerivePop() {
  const cur = current.template || "course";
  const opts = [{ id: "course", name: t("tpl_course") }, { id: "breakdown", name: t("tpl_bench") },
    ...meetings.map((m) => ({ id: m.id, name: t("tpl_meet") + " · " + (LANG === "zh" ? m.name_zh : m.name_en) }))];
  const pick = opts.find((o) => o.id !== cur) || opts[0];
  $("#derive-pop").innerHTML = `<div class="pop-title">${t("derive_title")}</div><p class="pop-hint">${t("derive_hint")}</p>
    <div class="pop-list">${opts.map((o) => `<label class="pop-opt"><input type="radio" name="derive-tpl" value="${o.id}" ${o.id === pick.id ? "checked" : ""}>
      <span>${esc(o.name)}</span>${o.id === cur ? `<em>${t("derive_cur")}</em>` : ""}</label>`).join("")}</div>
    <div class="pop-foot"><label>${t("derive_lang")} <select id="derive-lang" class="select"><option value="zh" ${current.out_lang === "zh" ? "selected" : ""}>中文</option><option value="en" ${current.out_lang === "en" ? "selected" : ""}>English</option></select></label>
      <button type="button" id="derive-go" class="btn btn-primary btn-sm">${t("derive_go")}</button></div>`;
  $("#derive-go").onclick = async () => {
    const tpl = (document.querySelector("input[name=derive-tpl]:checked") || {}).value;
    try {
      const nt = await api(`/api/tasks/${current.id}/derive`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ template: tpl, out_lang: $("#derive-lang").value }) });
      $("#derive-pop").hidden = true; await refresh(); location.hash = `#/t/${nt.id}`;
    } catch (err) { toast(trServer(err.message)); }
  };
}
$("#d-derive").onclick = (e) => {
  e.stopPropagation();
  const pop = $("#derive-pop");
  if (!pop.hidden) { pop.hidden = true; return; }
  if (!current.timings || current.timings.fetch == null) return toast(t("derive_wait"));
  drawDerivePop(); pop.hidden = false;
};
document.addEventListener("click", (e) => { if (!e.target.closest(".derive-wrap")) { $("#derive-pop").hidden = true; $("#cmp-pop").hidden = true; } });

// 对比 / 汇总(拉片流程第 4、6 节):勾几条已完成的对标拆稿 → 导出汇总表 / 写横向对比与编辑决策
function drawComparePop() {
  const list = tasks.filter((x) => x.template === "breakdown" && x.kind !== "compare" && x.status === "done");
  $("#cmp-pop").innerHTML = `<div class="pop-title">${t("cmp_title")}</div><p class="pop-hint">${t("cmp_hint")}</p>
    <div class="pop-list">${list.map((x) => `<label class="pop-opt"><input type="checkbox" name="cmp-id" value="${x.id}" ${x.id === current.id ? "checked" : ""}>
      <span>${esc(x.title || x.vid)}</span></label>`).join("")}</div>
    <div class="pop-foot"><button type="button" id="cmp-csv" class="btn btn-ghost btn-sm">${t("cmp_csv")}</button>
      <button type="button" id="cmp-go" class="btn btn-primary btn-sm">${t("cmp_go")}</button></div>`;
  const ids = () => [...document.querySelectorAll("input[name=cmp-id]:checked")].map((i) => +i.value);
  $("#cmp-csv").onclick = () => { const v = ids(); if (!v.length) return toast(t("cmp_need1")); location.href = `/api/compare.csv?ids=${v.join(",")}`; };
  $("#cmp-go").onclick = async () => {
    const v = ids();
    if (v.length < 2 || v.length > 5) return toast(t("cmp_need"));
    try {
      const nt = await api("/api/compare", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: v, out_lang: current.out_lang || "zh" }) });
      $("#cmp-pop").hidden = true; await refresh(); location.hash = `#/t/${nt.id}`;
    } catch (err) { toast(trServer(err.message)); }
  };
}
$("#d-compare").onclick = (e) => { e.stopPropagation(); const pop = $("#cmp-pop"); if (!pop.hidden) { pop.hidden = true; return; } drawComparePop(); pop.hidden = false; };
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#derive-pop").hidden = true; });

$("#d-retry").onclick = async () => {
  await api(`/api/tasks/${current.id}/retry`, { method: "POST" }); rendered = {}; toast(t("requeued")); refresh(); openTask(current.id);
};
$("#d-del").onclick = async () => {
  if (!confirm(t("del_confirm"))) return;
  await api(`/api/tasks/${current.id}`, { method: "DELETE" });
  toast(t("deleted")); await refresh(); location.hash = "#/library";
};

// ---------- 轮询 ----------
async function tick() {
  try {
    await refresh();
    if (current) {
      const t = tasks.find((x) => x.id === current.id);
      if (t && (t.status !== current.status || t.status === "running" || t.status === "queued" || t.updated_at !== current.updated_at)) {
        const full = await api(`/api/tasks/${current.id}`);
        if (full.status !== current.status || full.updated_at !== current.updated_at) { if (full.status !== "done") rendered.summary = false; current = full; drawDetail(full); }
      }
    }
  } catch (_) {}
}
// ---------- 开始前检查(首页卡片) ----------
let obHidden = false;
try { obHidden = localStorage.getItem("wb-onboard-hidden") === "1"; } catch (_) {}
const OKI = '<svg viewBox="0 0 24 24"><path d="M5 12l5 5L20 7"/></svg>';
function cmdBox(c) { return `<div class="cmd"><code>${esc(c)}</code><button type="button" class="btn btn-ghost" data-copy="${esc(c)}">${LANG === "zh" ? "复制" : "Copy"}</button></div>`; }
// 时区 UTC+8(中国大陆、港澳台、新加坡等)→ 推荐 DeepSeek
function inUTC8() { return new Date().getTimezoneOffset() === -480; }
// 粘贴 API Key 的小表单(新手引导和设置页共用)
function keyForm(id) {
  return `<form class="keyform" data-key-form="${id}" autocomplete="off"><input type="password" class="input input-sm" name="k" placeholder="${t("key_ph")}" spellcheck="false">
    <button type="submit" class="btn btn-primary btn-sm">${t("key_save")}</button></form>`;
}
document.addEventListener("submit", async (e) => {
  const f = e.target.closest("[data-key-form]");
  if (!f) return;
  e.preventDefault();
  const k = f.k.value.trim();
  if (!k) return f.k.focus();
  const b = f.querySelector("button"); b.disabled = true;
  try {
    cfg = await api("/api/config/key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: k }) });
    toast(t("key_ok")); f.k.value = "";
    if (shownPage === "settings") drawSettings(); else drawOnboard(true);
  } catch (err) { toast(trServer(err.message)); } finally { b.disabled = false; }
});
// 「准备就绪」一行:按当前选的模板、写总结的 AI、有没有附课件、输入的是链接还是本地视频,说清这次会怎么做
function aiName(c) {
  if (c.active !== "api") return PNAME[c.active];
  return /deepseek\.com/.test(c.base_url || "") ? `DeepSeek${LANG === "zh" ? "" : " "}(${c.model})` : `API · ${c.model}`;
}
// 首页大标题、说明、输入框提示和开始按钮跟着所选模板换(课程总结 / 对标拆稿 / 会议纪要)
function drawHero() {
  const k = { breakdown: "_bench", meeting: "_meet", shots: "_shots" }[template] || "";
  $("#hero-h1").dataset.i18n = "home_h1" + k; $("#hero-p").dataset.i18n = "home_p" + k;
  $("#source").dataset.i18nPh = "source_ph" + k; $("#start-label").dataset.i18n = "start" + k;
  $("#hero-h1").textContent = t("home_h1" + k); $("#hero-p").textContent = t("home_p" + k);
  $("#source").placeholder = t("source_ph" + k); $("#start-label").textContent = t("start" + k);
}
function drawReady() {
  const box = $("#onboard");
  if (!status || !cfg || !cfg.ready || !box.classList.contains("allok")) return;   // 只改「都好了」那一行,检查清单不动
  const ok = (id) => (cfg.providers.find((p) => p.id === id) || {}).ok;
  const has = (n) => !!(status.tools.find((x) => x.name === n) || {}).path;
  const n = aiName(cfg), parts = [];
  if (template === "breakdown") parts.push(t("rd_bench", { n }));
  else if (template === "shots") parts.push(t("rd_shots", { n }) + (["claude", "harness"].includes(cfg.active) || (cfg.active === "api" && /deepseek\.com/.test(cfg.base_url || "")) || cfg.active === "codex" ? "" : t("rd_shots_noimg")));
  else if (template === "meeting") {
    const m = meetings.find((x) => x.id === meetingVariant);
    parts.push(t("rd_meet", { n, m: m ? (LANG === "zh" ? m.name_zh : m.name_en) : "" }));
  } else {
    parts.push(t("rd_course", { n }) + (["claude", "harness"].includes(cfg.active) ? t("rd_see") : ""));
    const other = { claude: "codex", codex: "claude" }[cfg.active];
    if (other && ok(other)) parts.push(t("rd_cross", { r: PNAME[other] }));
    else if (cfg.active === "api") parts.push(t("rd_api_rev", { m: cfg.review_model || cfg.model }) + t("rd_noimg"));
    else if (cfg.active === "harness") parts.push(t("rd_self", { r: PNAME.harness }) + t("rd_hs_rev"));
    else parts.push(t("rd_self", { r: PNAME[cfg.active] }));
    parts.push(slidesFile ? t("rd_slides", { f: esc(slidesFile.name) }) : t("rd_noslides"));
    const v = $("#source").value.trim();
    if (!v && slidesFile) parts.push(t("rd_slides_only"));
    else if (/^https?:\/\//i.test(v) || /https?:\/\/\S+/.test(v)) parts.push(t("rd_link"));
    else parts.push(has("tesseract") ? t("rd_frames") : t("rd_noframes"));
  }
  box.innerHTML = `<span class="ob-item"><span class="ck ok">${OKI}</span></span><span class="ob-ready rd">${t("rd_head")}${parts.join(t("rd_sep"))}${t("rd_end")}${status.model_ready ? "" : " " + t("ob_model")}</span>`;
}
async function drawOnboard(recheck) {
  const box = $("#onboard");
  if (recheck) box.innerHTML = `<div class="ob-sub">${t("ob_checking")}</div>`;
  try { [status, cfg] = await Promise.all([api("/api/status"), api("/api/config")]); } catch (_) { return; }
  drawModelCard(cfg);
  const has = (n) => !!(status.tools.find((x) => x.name === n) || {}).path;
  const mac = status.platform === "darwin", win = status.platform.startsWith("win");
  const dl = has("yt-dlp"), tr = has("ffmpeg") && has("whisper-cli"), ai = cfg.ready;
  box.hidden = false;
  if (dl && tr && ai) {   // 都好了:只留一行"准备就绪",内容跟着所选模板 / AI / 课件 / 输入变
    box.className = "onboard ready allok";
    drawReady();
    return;
  }
  if (obHidden && !recheck) {
    box.className = "onboard ready";
    box.innerHTML = `<span class="ob-ready" style="color:var(--warn-on-soft)">${t("ob_title")}: ${[dl, tr, ai].filter((x) => !x).length} ✗</span><button type="button" class="btn btn-ghost btn-sm" id="ob-show">${t("ob_show")}</button>`;
    $("#ob-show").onclick = () => { obHidden = false; try { localStorage.removeItem("wb-onboard-hidden"); } catch (_) {} drawOnboard(); };
    return;
  }
  box.className = "onboard";
  const item = (ok, title, desc, extra = "") => `<li class="ob-item"><span class="ck ${ok ? "ok" : "no"}">${ok ? OKI : "!"}</span><span class="ob-t">${title}</span>
    <span class="ob-d">${desc}</span>${ok ? "" : extra}</li>`;
  const brewCmd = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"';
  let rows = "";
  if (mac && !status.brew && !(dl && tr)) rows += item(false, t("ob_brew"), t("ob_brew_d"), cmdBox(brewCmd));
  const osNote = win ? `<div class="ob-note">${t("ob_win")}</div>` : !mac ? `<div class="ob-note">${t("ob_linux")}</div>` : "";
  rows += item(dl, t("ob_dl"), t("ob_dl_d"), mac ? cmdBox("brew install yt-dlp") : win ? cmdBox("winget install -e --id yt-dlp.yt-dlp") : osNote);
  rows += item(tr, t("ob_tr"), t("ob_tr_d") + (status.model_ready ? "" : `<div class="ob-note">${t("ob_model")}</div>`),
    mac ? cmdBox("brew install ffmpeg whisper-cpp") : win ? cmdBox("winget install -e --id Gyan.FFmpeg") + osNote : osNote);
  // 写总结的 AI:按时区排推荐顺序(UTC+8 → DeepSeek 在前;其他 → 先用已有的 ChatGPT / Claude 会员)
  const cn = inUTC8(), rec = `<span class="rec-tag">${t("ob_rec")}</span>`;
  const ds = `<div class="ob-note">${cn ? rec : ""}${t("ob_ds")} · <a href="/guide/deepseek" target="_blank" rel="noopener"><b>${t("ob_ds_guide")}</b></a> · <a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener">${t("ob_ds_link")} ↗</a></div>${keyForm("ob")}`;
  const hsp = (cfg.providers || []).find((p) => p.id === "harness") || {};
  const hs = (mac || win) ? `<div class="ob-note">${cn ? rec : ""}${t("ob_hs")} · <a href="https://www.deepseek.com/en/harness/" target="_blank" rel="noopener">${t("ob_hs_link")} ↗</a></div>`
    + (/没登录/.test(hsp.note || "") ? `<div class="ob-note">${t("ob_hs_login")}</div>` : /安装盘/.test(hsp.note || "") ? `<div class="ob-note">${t("p_harness_dmg")}</div>` : "") : "";
  const subs = `<div class="ob-note">${cn ? "" : rec}${t("ob_ai_claude")}</div>${cmdBox("npm i -g @anthropic-ai/claude-code && claude")}
     <div class="ob-note">${cn ? "" : rec}${t("ob_ai_codex")}</div>${cmdBox("npm i -g @openai/codex && codex")}
     ${status.npm ? "" : `<div class="ob-note">${t("ob_ai_node")}</div>${cmdBox(mac ? "brew install node" : win ? "winget install OpenJS.NodeJS.LTS" : "https://nodejs.org")}`}`;
  rows += item(ai, t("ob_ai"), ai ? t("ob_ai_ok", { n: PNAME[cfg.active] }) : t(cn ? "ob_tz_cn" : "ob_tz_intl"),
    cn ? `${hs}${hs ? `<div class="ob-note ob-sep">${t("ob_or_key")}</div>` : ""}${ds}<div class="ob-note ob-sep">${t("ob_alt")}</div>${subs}`
       : `${subs}<div class="ob-note ob-sep">${t("ob_alt_api")}</div>${hs}${ds}`);
  const oneclick = win ? `<div class="ob-or" style="grid-column:auto;margin-top:12px">${t("ob_oneclick_win")}</div>`
    : `<div class="ob-or" style="grid-column:auto;margin-top:12px">${t("ob_oneclick")}</div>${cmdBox(`bash "${status.workbench_dir}/setup.sh"`).replace('class="cmd"', 'class="cmd" style="grid-column:auto"')}`;
  box.innerHTML = `<div class="ob-head"><b>${t("ob_title")}</b></div><p class="ob-sub">${t("ob_sub")}</p><ul class="ob-list">${rows}</ul>${oneclick}
    <div class="ob-actions"><button type="button" class="btn btn-primary btn-sm" id="ob-recheck">${t("ob_recheck")}</button><button type="button" class="btn btn-ghost btn-sm" id="ob-hide">${t("ob_hide")}</button></div>`;
  $("#ob-recheck").onclick = () => drawOnboard(true);
  $("#ob-hide").onclick = () => { obHidden = true; try { localStorage.setItem("wb-onboard-hidden", "1"); } catch (_) {} drawOnboard(); };
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-copy]");
  if (!b) return;
  try { await navigator.clipboard.writeText(b.dataset.copy); toast(t("ob_copied")); } catch (_) { toast(t("copy_fail")); }
});
// 窗口切回来时(用户可能刚在终端装完)自动重查一次
window.addEventListener("focus", () => { if (shownPage === "home" && !$("#onboard").classList.contains("ready")) drawOnboard(); });

// ---------- 输入框下的用前提示 ----------
const LOGIN_SITES = /panopto|echo360|kaltura|yuja|coursera|udemy|edx\.org|instructure|canvas|moodle|blackboard|brightspace|d2l|lms\.|mediasite|zoom\.us\/rec|vimeo\.com/i;
function drawSrcHint() {
  const v = $("#source").value.trim(), el = $("#srchint");
  let msg = "", warn = false;
  if (!v && template === "course" && slidesFile) msg = t("hint_slides_only");
  else if (!v && template === "breakdown") msg = t("hint_bench");
  else if (!v && template === "meeting") msg = t("hint_meet");
  else if (/douyin\.com|iesdouyin/i.test(v)) { msg = t("hint_douyin"); warn = true; }
  else if (/^https?:\/\//i.test(v) || /https?:\/\/\S+/.test(v)) {
    if (LOGIN_SITES.test(v)) {
      const b = cfg && cfg.cookies_browser;
      msg = b ? t("hint_login_ok", { b: b[0].toUpperCase() + b.slice(1) }) : `${t("hint_login")} <a href="#/settings">→</a>`;
      warn = !b;
    } else if (status && !status.model_ready && !/youtube\.com|youtu\.be/i.test(v)) msg = t("hint_long");
  } else if (/^(\/|~\/|[A-Za-z]:\\)/.test(v)) msg = t("hint_local");
  el.hidden = !msg; el.className = "srchint" + (warn ? " warn" : ""); el.innerHTML = msg;
}
$("#source").addEventListener("input", () => { drawSrcHint(); drawReady(); });

// ---------- 详情页的进度提示 + 浏览器标签标题 ----------
// 专名核对结果:校正了哪些、哪些待核实(点开看清单)
function drawNames(task) {
  const el = $("#d-names"), n = task.status === "done" && task.meta && task.meta.names;
  el.hidden = !n;
  if (!n) return;
  const fixed = (n.fixed || []).length, unsure = n.unsure || 0;
  const parts = [fixed ? t("names_fixed", { n: fixed }) : "", unsure ? t("names_unsure", { n: unsure }) : ""].filter(Boolean);
  el.className = "names-box" + (unsure ? " warn" : "");
  el.querySelector("summary").textContent = parts.length ? parts.join(" · ") : t("names_ok");
  el.querySelector("pre").textContent = n.report || "";
}
function drawReview(task) {
  const el = $("#d-review"), r = task.status === "done" && task.meta && task.meta.review;
  el.hidden = !r;
  if (!r) return;
  el.className = "names-box" + (r.passed ? "" : " warn");
  el.querySelector("summary").textContent = r.passed ? t("review_pass", { n: r.rounds, who: r.reviewer || "", how: t(r.cross ? "review_cross" : "review_self") })
    : r.remaining ? t("review_left", { n: r.remaining }) : r.marked ? t("review_marked", { n: r.rounds, m: r.marked, f: r.fixed || 0 }) : t("review_none");
  el.querySelector("pre").textContent = r.report || "";
}
function drawTip(task) {
  const el = $("#d-tip");
  let msg = "";
  if (task.status === "running") {
    if (task.stage === "fetch") {
      const m = (task.log || "").match(/首次使用,下载 whisper 模型[\s\S]*?(\d+)%[^\n]*$/);
      msg = /首次使用,下载 whisper 模型/.test(task.log || "") && !/开始转写/.test(task.log || "")
        ? t("tip_model", { p: m ? ` (${m[1]}%)` : "" }) : t("tip_fetch");
    } else if (task.stage === "summarize") msg = cfg && cfg.active && cfg.active !== "api" ? t("tip_cli", { n: PNAME[cfg.active] }) : t("tip_api");
  }
  el.hidden = !msg; el.textContent = msg;
}
function drawTabTitle() {
  const run = tasks.find((x) => x.status === "running");
  if (run) document.title = `${t("tab_running", { s: trServer(run.message) || statusName("running") })} · ${t("app")}`;
  else if (drawTabTitle.wasRunning) document.title = `${t("tab_done")} · ${t("app")}`;
  else document.title = t("app");
  drawTabTitle.wasRunning = drawTabTitle.wasRunning || !!run;
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && !tasks.some((x) => x.status === "running")) { drawTabTitle.wasRunning = false; document.title = t("app"); } });

// ---------- 语言 ----------
function siteName(task) { return task.kind === "web" ? (task.meta && task.meta.site) || t("kind_web") : kindName(task.kind); }
function setLang(l) {
  LANG = l;
  try { localStorage.setItem("wb-lang", l); } catch (_) {}
  applyI18n(); drawTemplates(); drawList(); drawSrcHint(); drawTabTitle();
  if (shownPage === "home") drawOnboard();
  if (cfg) drawModelCard(cfg);
  if (shownPage) $("#page-title").textContent = t(TITLES[shownPage]);
  if (shownPage === "library") drawLibrary();
  if (shownPage === "settings") drawSettings();
  if (shownPage === "detail" && current) {
    drawDetail(current);
    if (!$("#chapters").querySelector(".chapter")) $("#chapters").innerHTML = "";
    if (!$("#player iframe, #player video")) $("#player").innerHTML = `<div class="player-empty"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg><span>${t("player_empty")}</span></div>`;
  }
}
$("#lang-btn").onclick = () => { setLang(LANG === "zh" ? "en" : "zh"); if (!outTouched) $("#out_lang").value = LANG; };
let outTouched = false;   // 没手动选过总结语言时,跟着界面语言走
$("#out_lang").addEventListener("change", () => { outTouched = true; });
applyI18n();
$("#out_lang").value = LANG;

refresh().then(route);
setInterval(tick, 2000);

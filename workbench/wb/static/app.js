// 总结工作台前端:新建 / 历史 / 阅读(总结、文字稿、日志)/ 播放器 + 章节。地址栏 #/t/<id> 记住当前任务
const $ = (s) => document.querySelector(s);
const ICON = {
  check: '<svg viewBox="0 0 24 24"><path d="M5 12l5 5L20 7"/></svg>',
  spin: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  dot: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="2" fill="currentColor"/></svg>',
};
const STAGES = [["fetch", "拿文字稿"], ["prepare", "整理讲义稿"], ["summarize", "写总结"], ["check", "核对时间戳"]];
const KIND = { youtube: "YouTube", bilibili: "B 站", local: "本地文件" };
const STATUS = { queued: "排队中", running: "进行中", done: "完成", failed: "失败" };

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
const dur = (s) => s == null ? "" : s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${Math.round(s % 60)} 秒`;
function ago(ts) {
  const d = (Date.now() / 1000 - ts);
  if (d < 60) return "刚刚";
  if (d < 3600) return `${Math.floor(d / 60)} 分钟前`;
  if (d < 86400) return `${Math.floor(d / 3600)} 小时前`;
  const t = new Date(ts * 1000); return `${t.getMonth() + 1}月${t.getDate()}日`;
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("on");
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("on"), 1600);
}

// ---------- 模板(第一期只有课程总结可用) ----------
const TEMPLATES = [
  { id: "course", name: "课程总结", ready: true, icon: '<svg viewBox="0 0 24 24"><path d="M22 10 12 5 2 10l10 5 10-5z"/><path d="M6 12v5c3 2 9 2 12 0v-5"/></svg>',
    desc: "录播课、公开课。七节固定结构 + 复习卡,时间戳自动核对。",
    parts: ["课程通知", "一句话概括", "核心要点(带时间段)", "章节时间线(可回跳)", "金句 / 考点信号", "复习卡 8–15 张"] },
  { id: "benchmark", name: "对标拆稿", ready: false, icon: '<svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
    desc: "短视频口播逐句拆:作用分段、秒数、字数、信息点。",
    parts: ["逐句拆稿表", "结构骨架", "可复用句式"] },
  { id: "meeting", name: "会议纪要", ready: false, icon: '<svg viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/></svg>',
    desc: "会议录音:议题、结论、待办和负责人。",
    parts: ["议题", "结论", "待办与负责人"] },
];
let template = "course";
function tplCard(t, pick) {
  const tag = t.ready ? (pick && t.id === template ? "已选" : "可用") : "即将上线";
  return `<button type="button" class="tpl ${pick && t.id === template ? "on" : ""}" data-tpl="${t.id}" ${t.ready ? "" : "disabled"}>
    <span class="tpl-tag">${tag}</span><span class="tpl-ic">${t.icon}</span>
    <span class="tpl-n">${t.name}</span><span class="tpl-d">${t.desc}</span>
    ${pick ? "" : `<ul>${t.parts.map((p) => `<li>${p}</li>`).join("")}</ul>`}</button>`;
}
function drawTemplates() {
  $("#tpl-pick").innerHTML = TEMPLATES.map((t) => tplCard(t, true)).join("");
  $("#tpl-list").innerHTML = TEMPLATES.map((t) => tplCard(t, false)).join("");
  document.querySelectorAll("#tpl-pick .tpl:not(:disabled)").forEach((b) => b.onclick = () => { template = b.dataset.tpl; drawTemplates(); });
}
drawTemplates();

// ---------- 模型状态 ----------
let cfg = null;
api("/api/config").then((c) => {
  cfg = c;
  $("#model").innerHTML = c.key_ok ? `<span class="ok">${esc(c.model)} · Key 已配置</span>` : `<span class="bad">还没配置 Key,见「设置」</span>`;
});

// ---------- 路由:#/ 新建 · #/library 资料库 · #/templates 模板 · #/settings 设置 · #/t/<id> 任务 ----------
const PAGES = ["home", "library", "templates", "settings", "detail"];
const TITLES = { home: "新建总结", library: "资料库", templates: "模板", settings: "设置", detail: "总结" };
let shownPage = null;
function show(page) {
  PAGES.forEach((p) => $("#" + p).hidden = p !== page);
  document.querySelectorAll(".nav-item").forEach((a) => a.classList.toggle("on", a.dataset.page === page));
  $("#page-title").textContent = TITLES[page];
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
  { id: "sage", name: "鼠尾草", desc: "灰绿 + 米白,最安静", sw: "linear-gradient(135deg, #c4dfcd, #f1ead8 55%, #d6deee)", dot: "#4f7f6f" },
  { id: "lavender", name: "薰衣草暮色", desc: "灰紫 + 浅杏,傍晚的感觉", sw: "linear-gradient(135deg, #d6cced, #f6dacd 55%, #e8d6e2)", dot: "#7a6aa8" },
  { id: "mist", name: "晨雾", desc: "雾蓝绿,清爽", sw: "linear-gradient(135deg, #bedce8, #cee8d6 55%, #dce2f0)", dot: "#3e7c94" },
];
function drawPalettes() {
  const cur = document.documentElement.dataset.palette || "sage";
  $("#palettes").innerHTML = PALETTES.map((p) => `<button type="button" class="palette ${p.id === cur ? "on" : ""}" data-p="${p.id}">
    <span class="sw" style="background:${p.sw}; box-shadow: inset -14px 0 0 -8px ${p.dot}"></span>
    <b>${p.name}</b><small>${p.desc}</small></button>`).join("");
  document.querySelectorAll(".palette").forEach((b) => b.onclick = () => {
    document.documentElement.dataset.palette = b.dataset.p;
    try { localStorage.setItem("wb-palette", b.dataset.p); } catch (_) {}
    drawPalettes(); toast(`已换成「${PALETTES.find((x) => x.id === b.dataset.p).name}」`);
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
  else { show("home"); setTimeout(() => $("#source").focus(), 0); }
}
window.addEventListener("hashchange", route);

// ---------- 新建 ----------
$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const source = $("#source").value.trim();
  if (!source) return $("#source").focus();
  formMsg("提交中…");
  try {
    const t = await api("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, lang: $("#lang").value, out_lang: $("#out_lang").value }) });
    $("#source").value = ""; formMsg("");
    await refresh(); location.hash = `#/t/${t.id}`;
  } catch (err) { formMsg(err.message, true); }
});
$("#source").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("#form").requestSubmit(); });
$("#file").addEventListener("change", () => { if ($("#file").files[0]) upload($("#file").files[0]); });
function formMsg(s, bad) { const m = $("#formmsg"); m.textContent = s; m.classList.toggle("bad", !!bad); }

async function upload(f) {
  const fd = new FormData();
  fd.append("file", f); fd.append("lang", $("#lang").value); fd.append("out_lang", $("#out_lang").value);
  formMsg(`上传 ${f.name}…`);
  try {
    const t = await api("/api/upload", { method: "POST", body: fd });
    formMsg(""); $("#file").value = "";
    await refresh(); location.hash = `#/t/${t.id}`;
  } catch (err) { formMsg(err.message, true); }
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
  if (!$("#library").hidden) drawLibrary();
}
function drawList() {
  const list = tasks.slice(0, 8);
  $("#tasks").innerHTML = list.map((t) => `
    <li class="task ${current && t.id === current.id ? "on" : ""}" data-id="${t.id}" title="${esc(t.title || t.vid)}">
      <span class="s-dot ${t.status}"></span>
      <span class="t-title">${esc(t.title || t.vid)}</span>
      <span class="t-sub">${KIND[t.kind] || t.kind} · ${t.status === "done" ? ago(t.updated_at) : esc(t.status === "running" ? t.message : STATUS[t.status])}</span>
    </li>`).join("") || `<li class="task-empty">还没有任务</li>`;
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
    const st = t.status === "done" && !t.check_ok ? ["warn", "完成(核对有问题)"] : [t.status, STATUS[t.status]];
    return `<tr data-id="${t.id}">
      <td class="t-cell" title="${esc(t.title || t.vid)}">${esc(t.title || t.vid)}</td>
      <td>${KIND[t.kind] || t.kind}</td>
      <td>${t.out_lang === "en" ? "English" : "中文"}</td>
      <td><span class="badge ${st[0]}">${st[1]}</span></td>
      <td class="num">${t.status === "done" ? dur(Math.round(total)) : "—"}</td>
      <td class="muted">${ago(t.created_at)}</td></tr>`;
  }).join("") || `<tr><td colspan="6" class="table-empty">${tasks.length ? "没有符合条件的任务" : "还没有任务,去「新建总结」贴一个链接"}</td></tr>`;
  document.querySelectorAll("#lib-rows tr[data-id]").forEach((tr) => tr.onclick = () => { location.hash = `#/t/${tr.dataset.id}`; });
}

// ---------- 设置 ----------
async function drawSettings() {
  drawPalettes();
  const [c, s] = await Promise.all([api("/api/config"), api("/api/status")]);
  const ok = '<svg viewBox="0 0 24 24"><path d="M5 12l5 5L20 7"/></svg>', no = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>';
  $("#set-model").innerHTML = `<dt>状态</dt><dd><span class="badge ${c.key_ok ? "done" : "failed"}">${c.key_ok ? "Key 已配置" : "没有 Key"}</span></dd>
    <dt>模型</dt><dd>${esc(c.model)}</dd><dt>接口</dt><dd>${esc(c.base_url)}</dd><dt>Key 来源</dt><dd>${esc(c.key_source)}</dd>
    <dt>配置文件</dt><dd><code>${esc(s.config_file)}</code></dd>`;
  $("#set-tools").innerHTML = s.tools.map((t) => `<li><span class="ck ${t.path ? "ok" : "no"}">${t.path ? ok : no}</span>
    <span>${esc(t.name)}</span><span class="sub">${esc(t.need)}${t.path ? " · " + esc(t.path) : " · 没找到"}</span></li>`).join("");
  const n = s.counts, total = Object.values(n).reduce((a, b) => a + b, 0);
  $("#set-data").innerHTML = `<dt>任务</dt><dd>共 ${total} 个 · 完成 ${n.done || 0} · 失败 ${n.failed || 0}</dd>
    <dt>数据目录</dt><dd><code>${esc(s.data_dir)}</code></dd><dt>说明</dt><dd class="muted">每个任务一个文件夹,里面有文字稿、讲义稿和总结 .md;不进 git。</dd>`;
}

// ---------- 详情 ----------
async function openTask(id) {
  let t;
  try { t = await api(`/api/tasks/${id}`); } catch (_) { location.hash = ""; return; }
  const switched = !current || current.id !== id;
  current = t;
  if (switched) {
    rendered = {}; setTab("summary");
    $("#player").innerHTML = `<div class="player-empty">${'<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>'}<span>点任意时间戳,在这里播放</span></div>`;
    $("#chapters").innerHTML = "";
    $("#d-log").textContent = "";
  }
  show("detail");
  drawList(); drawDetail(t);
  if (switched && t.kind === "local" && t.meta && t.meta.media_path) loadLocal(t);
}

function drawDetail(t) {
  $("#d-title").textContent = t.title || t.vid;
  $("#d-kind").textContent = KIND[t.kind] || t.kind;
  $("#d-time").textContent = `${t.out_lang === "en" ? "English" : "中文"}总结 · ${ago(t.created_at)}`;
  $("#d-open").hidden = t.kind === "local"; if (t.kind !== "local") $("#d-open").href = t.source;
  const done = t.status === "done";
  $("#d-copy").disabled = $("#d-download").disabled = !done;
  $("#d-retry").disabled = $("#d-del").disabled = t.status === "running";

  $("#steps").innerHTML = STAGES.map(([k, name], i) => {
    const ok = t.timings[k] != null && !(t.status !== "done" && t.stage === k);
    const now = t.status === "running" && t.stage === k;
    const bad = t.status === "failed" && t.stage === k;
    const cls = bad ? "bad" : now ? "now" : ok ? "done" : "";
    const ic = bad ? ICON.x : now ? ICON.spin : ok ? ICON.check : `<b style="font-size:12px">${i + 1}</b>`;
    const tm = bad ? "失败" : now ? "进行中…" : ok ? dur(t.timings[k]) : t.status === "queued" && i === 0 ? "排队中" : "等待";
    return `<div class="step ${cls}"><span class="ic">${ic}</span><div><div class="nm">${name}</div><div class="tm">${tm}</div></div></div>`;
  }).join("");

  const st = $("#d-status");
  st.className = "status-line " + (t.status === "failed" ? "bad" : done ? (t.check_ok ? "ok" : "warn") : "");
  st.textContent = t.message || "";

  const pre = $("#d-log");
  const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  if (pre.textContent !== t.log) { pre.textContent = t.log || ""; if (atBottom) pre.scrollTop = pre.scrollHeight; }
  const ck = $("#d-check");
  ck.className = "callout " + (t.check_report ? (t.check_ok ? "ok" : "bad") : "");
  ck.textContent = t.check_report || "";
  $("#check-dot").className = "dot " + (t.check_report ? (t.check_ok ? "ok" : "bad") : "");

  if (done && !rendered.summary) loadSummary(t);
  else if (!done) {
    rendered.summary = false;
    $("#summary").innerHTML = t.status === "failed"
      ? `<div class="empty-pane">没有生成总结。原因见上方提示和"日志";修好后点"重跑"。</div>`
      : `<div class="skeleton">${"<i></i>".repeat(8).replace(/<i><\/i>/g, (m, i) => `<i style="width:${60 + ((i * 37) % 40)}%"></i>`)}</div>`;
    if (!$("#chapters").children.length) $("#chapters").innerHTML = `<li class="chapters-empty">总结写好后显示章节</li>`;
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
  drawChapters(md);
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

function drawChapters(md) {
  const lines = md.split("\n"); let inTl = false; const items = [];
  for (const l of lines) {
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
  ).join("") || `<li class="chapters-empty">总结里没有章节时间线</li>`;
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
      || `<div class="empty-pane">文字稿是空的</div>`;
  } catch (err) { rendered.transcript = false; box.innerHTML = `<div class="empty-pane">${esc(err.message)}</div>`; }
}

// ---------- 播放器 ----------
function jumpUrl(t, sec) {
  if (t.kind === "youtube") return `${t.source}&t=${sec}s`;
  if (t.kind === "bilibili") return `${t.source}${t.source.includes("?") ? "&" : "?"}t=${sec}`;
  return null;
}
function loadLocal(t) {
  $("#player").innerHTML = `<video controls preload="metadata" src="/api/tasks/${t.id}/media"></video>`;
  $("#player video").addEventListener("timeupdate", (e) => markChapter(e.target.currentTime));
}
function seek(t, sec) {
  const box = $("#player");
  if (t.kind === "local") {
    if (!box.querySelector("video")) { if (!(t.meta && t.meta.media_path)) return toast("这个任务没有本地视频(只有字幕)"); loadLocal(t); }
    const v = box.querySelector("video"); v.currentTime = sec; v.play();
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
  try { await navigator.clipboard.writeText(rendered.md || await api(`/api/tasks/${current.id}/summary`)); toast("已复制 Markdown"); }
  catch (_) { toast("复制失败"); }
};
$("#d-download").onclick = () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([rendered.md || ""], { type: "text/markdown" }));
  a.download = `${(current.title || current.vid).replace(/[\\/:*?"<>|]+/g, "_")}.md`; a.click();
};
$("#d-retry").onclick = async () => {
  await api(`/api/tasks/${current.id}/retry`, { method: "POST" }); rendered = {}; toast("已重新排队"); refresh(); openTask(current.id);
};
$("#d-del").onclick = async () => {
  if (!confirm("删除这个任务和它的文字稿、总结?")) return;
  await api(`/api/tasks/${current.id}`, { method: "DELETE" });
  toast("已删除"); await refresh(); location.hash = "#/library";
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
refresh().then(route);
setInterval(tick, 2000);

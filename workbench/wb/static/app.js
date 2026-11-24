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

// ---------- 模型状态 ----------
api("/api/config").then((c) => {
  $("#model").innerHTML = c.key_ok ? `<span class="ok">${esc(c.model)}</span>` : `<span class="bad">还没配置模型 Key(见 README)</span>`;
  $("#hint-model").textContent = c.key_ok ? c.model : "未配置 Key";
});

// ---------- 路由 ----------
function route() {
  const m = location.hash.match(/^#\/t\/(\d+)/);
  if (m) openTask(+m[1]); else showHome();
}
window.addEventListener("hashchange", route);
$("#new-btn").onclick = () => { location.hash = ""; showHome(); };
function showHome() {
  current = null; $("#detail").hidden = true; $("#home").hidden = false;
  drawList(); setTimeout(() => $("#source").focus(), 0);
}

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

// ---------- 历史列表 ----------
async function refresh() { tasks = await api("/api/tasks"); drawList(); }
$("#search").addEventListener("input", drawList);
function drawList() {
  const q = $("#search").value.trim().toLowerCase();
  const list = tasks.filter((t) => !q || (t.title || t.vid || "").toLowerCase().includes(q));
  $("#tasks").innerHTML = list.map((t) => `
    <li class="task ${current && t.id === current.id ? "on" : ""}" data-id="${t.id}" title="${esc(t.title || t.vid)}">
      <span class="s-dot ${t.status}"></span>
      <span class="t-title">${esc(t.title || t.vid)}</span>
      <span class="t-sub">${KIND[t.kind] || t.kind} · ${t.status === "done" ? ago(t.updated_at) : esc(t.status === "running" ? t.message : STATUS[t.status])}</span>
    </li>`).join("") || `<li class="task-empty">${q ? "没有匹配的任务" : "还没有任务"}</li>`;
  document.querySelectorAll(".task[data-id]").forEach((li) => li.onclick = () => { location.hash = `#/t/${li.dataset.id}`; });
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
  $("#home").hidden = true; $("#detail").hidden = false;
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
  toast("已删除"); await refresh(); location.hash = "";
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

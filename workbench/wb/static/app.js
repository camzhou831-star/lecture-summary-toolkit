// 总结工作台前端:贴链接 / 任务进度 / 结果(Markdown 渲染,时间戳点了跳到原视频对应时间)
const $ = (s) => document.querySelector(s);
const STAGES = [["fetch", "拿文字稿"], ["prepare", "整理讲义稿"], ["summarize", "写总结"], ["check", "核对时间戳"]];
const KIND = { youtube: "YouTube", bilibili: "B站", local: "本地" };
const STATUS = { queued: "排队中", running: "进行中", done: "完成", failed: "失败" };
let current = null;          // 当前打开的任务 id
let shownSummaryFor = null;  // 已渲染总结的任务 id(避免轮询时反复重绘、打断播放)
let tasks = [];

async function api(path, opt = {}) {
  const r = await fetch(path, opt);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function fmtSec(s) { return s == null ? "" : s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${Math.round(s % 60)} 秒`; }

// ---------- 配置 ----------
api("/api/config").then((c) => {
  $("#model").innerHTML = c.key_ok
    ? `模型 ${esc(c.model)} · Key 来自${esc(c.key_source)}`
    : `<span class="bad">还没配置模型 Key(见 workbench/README.md)</span>`;
});

// ---------- 新建 ----------
$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const source = $("#source").value.trim();
  if (!source) return;
  $("#formmsg").textContent = "提交中…";
  try {
    const t = await api("/api/tasks", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, lang: $("#lang").value, out_lang: $("#out_lang").value }),
    });
    $("#source").value = ""; $("#formmsg").textContent = "";
    await refresh(); open(t.id);
  } catch (err) { $("#formmsg").innerHTML = `<span class="bad">${esc(err.message)}</span>`; }
});

$("#file").addEventListener("change", async () => {
  const f = $("#file").files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f); fd.append("lang", $("#lang").value); fd.append("out_lang", $("#out_lang").value);
  $("#formmsg").textContent = `上传 ${f.name}…`;
  try {
    const t = await api("/api/upload", { method: "POST", body: fd });
    $("#formmsg").textContent = ""; $("#file").value = "";
    await refresh(); open(t.id);
  } catch (err) { $("#formmsg").innerHTML = `<span class="bad">${esc(err.message)}</span>`; }
});

// ---------- 任务列表 ----------
async function refresh() {
  tasks = await api("/api/tasks");
  $("#tasks").innerHTML = tasks.map((t) => `
    <li data-id="${t.id}" class="${t.id === current ? "on" : ""}">
      <div class="t-title">${esc(t.title || t.vid)}</div>
      <div class="t-sub"><span class="badge ${t.status}">${STATUS[t.status]}</span>
        ${KIND[t.kind] || t.kind} · ${esc(t.status === "done" || t.status === "failed" ? t.message : t.message || "")}</div>
    </li>`).join("") || `<li class="muted">还没有任务</li>`;
  document.querySelectorAll("#tasks li[data-id]").forEach((li) => li.onclick = () => open(+li.dataset.id));
}

// ---------- 详情 ----------
async function open(id) {
  if (current !== id) { shownSummaryFor = null; $("#player").innerHTML = ""; }
  current = id;
  document.querySelectorAll("#tasks li").forEach((li) => li.classList.toggle("on", +li.dataset.id === id));
  const t = await api(`/api/tasks/${id}`);
  $("#empty").hidden = true; $("#detail").hidden = false;
  $("#d-title").textContent = t.title || t.vid;
  const link = $("#d-open");
  if (t.kind === "local") link.hidden = true; else { link.hidden = false; link.href = t.source; }
  $("#d-status").innerHTML = `<span class="badge ${t.status}">${STATUS[t.status]}</span> ${esc(t.message || "")}`;
  $("#stages").innerHTML = STAGES.map(([k, name]) => {
    const done = t.timings[k] != null;
    const now = t.status === "running" && t.stage === k;
    const bad = t.status === "failed" && t.stage === k;
    return `<span class="stage ${done ? "done" : ""} ${now ? "now" : ""} ${bad ? "bad" : ""}">${name}${done ? ` · ${fmtSec(t.timings[k])}` : ""}</span>`;
  }).join("");
  const pre = $("#d-log");
  const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 20;
  pre.textContent = t.log || "";
  if (atBottom) pre.scrollTop = pre.scrollHeight;
  $("#d-check").hidden = !t.check_report;
  $("#d-report").textContent = t.check_report || "";
  if (t.status === "done" && shownSummaryFor !== id) {
    const md = await api(`/api/tasks/${id}/summary`);
    renderSummary(md, t);
    shownSummaryFor = id;
  } else if (t.status !== "done") {
    $("#summary").innerHTML = "";
  }
  $("#d-copy").onclick = async () => {
    try { await navigator.clipboard.writeText(await api(`/api/tasks/${id}/summary`)); $("#d-copy").textContent = "已复制"; }
    catch (err) { $("#d-copy").textContent = "复制失败"; }
    setTimeout(() => ($("#d-copy").textContent = "复制 Markdown"), 1500);
  };
  $("#d-retry").onclick = async () => { await api(`/api/tasks/${id}/retry`, { method: "POST" }); shownSummaryFor = null; refresh(); open(id); };
  $("#d-del").onclick = async () => {
    if (!confirm("删除这个任务和它的文字稿、总结?")) return;
    await api(`/api/tasks/${id}`, { method: "DELETE" });
    current = null; $("#detail").hidden = true; $("#empty").hidden = false; refresh();
  };
}

// ---------- 总结渲染 + 时间戳回跳 ----------
const TS = /(?<![\d:])(\d{1,3}):([0-5]\d)(?![\d:])/g;

function renderSummary(md, t) {
  const html = window.marked ? marked.parse(md) : `<pre>${esc(md)}</pre>`;
  const box = $("#summary");
  box.innerHTML = window.DOMPurify ? DOMPurify.sanitize(html, { ADD_ATTR: ["target"] }) : html;
  // 已有链接(章节时间线):链接文字是时间戳的,改成页面内跳转;按住 ⌘/Ctrl 点仍在原站打开
  box.querySelectorAll("a").forEach((a) => {
    const m = a.textContent.trim().match(/^\[?(\d{1,3}):([0-5]\d)\]?$/);
    if (m) { a.dataset.t = +m[1] * 60 + +m[2]; a.classList.add("ts"); }
    else { a.target = "_blank"; a.rel = "noopener"; }
  });
  // 正文里其余的时间戳(核心要点、考点信号里的 [录播 12:34])也变成可点的
  const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const n = walker.currentNode;
    if (n.parentElement.closest("a, code, pre")) continue;
    TS.lastIndex = 0;
    if (TS.test(n.nodeValue)) nodes.push(n);
  }
  nodes.forEach((n) => {
    const span = document.createElement("span");
    span.innerHTML = esc(n.nodeValue).replace(TS, (s, m, ss) => `<a class="ts" href="#" data-t="${+m * 60 + +ss}">${s}</a>`);
    n.replaceWith(...span.childNodes);
  });
  box.querySelectorAll("a.ts").forEach((a) => a.addEventListener("click", (e) => {
    if (e.metaKey || e.ctrlKey) {
      const url = jumpUrl(t, +a.dataset.t);
      if (url) window.open(url, "_blank", "noopener");
      e.preventDefault(); return;
    }
    e.preventDefault(); seek(t, +a.dataset.t);
  }));
  if (t.kind === "local" && t.meta && t.meta.media_path) seek(t, 0, false);
}

function jumpUrl(t, sec) {
  if (t.kind === "youtube") return `${t.source}&t=${sec}s`;
  if (t.kind === "bilibili") return `${t.source}${t.source.includes("?") ? "&" : "?"}t=${sec}`;
  return null;
}

function seek(t, sec, play = true) {
  const box = $("#player");
  if (t.kind === "local") {
    let v = box.querySelector("video");
    if (!v) {
      if (!t.meta || !t.meta.media_path) return;
      box.innerHTML = `<video controls preload="metadata" src="/api/tasks/${t.id}/media"></video>`;
      v = box.querySelector("video");
    }
    v.currentTime = sec; if (play) v.play();
    return;
  }
  let src;
  if (t.kind === "youtube") src = `https://www.youtube.com/embed/${t.vid}?start=${sec}&autoplay=1`;
  else if (t.kind === "bilibili") {
    const [bv, p] = t.vid.split("_p");
    src = `https://player.bilibili.com/player.html?bvid=${bv}&p=${p || 1}&t=${sec}&autoplay=1&high_quality=1`;
  }
  if (!src) return;
  box.innerHTML = `<div class="frame"><iframe src="${src}" allow="autoplay; encrypted-media; fullscreen" allowfullscreen></iframe></div>
    <p class="muted small">已跳到 ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}。按住 ⌘/Ctrl 点时间戳在原站打开。</p>`;
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---------- 轮询 ----------
async function tick() {
  try {
    await refresh();
    if (current != null) {
      const t = tasks.find((x) => x.id === current);
      if (t && (t.status === "running" || t.status === "queued" || shownSummaryFor !== current)) await open(current);
    }
  } catch (_) {}
}
refresh().then(() => { if (tasks.length) open(tasks[0].id); });
setInterval(tick, 2000);

"use strict";
// 课程笔记工作台前端。所有来自文件/AI 的文字都用 textContent 放进页面;
// 只有服务器渲染好的笔记 HTML(已整体转义)用 innerHTML。

const S = { state: null, job: null, jobId: null, poll: null, summary: null, aiTab: "upload", view: null };
const $ = (sel) => document.querySelector(sel);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;   // CSSOM,不受 CSP 对内联样式属性的限制
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const k of kids.flat()) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}

async function api(method, path, body, raw) {
  const opt = { method, headers: {} };
  if (body !== undefined && !raw) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  if (raw) opt.body = body;
  let r;
  try { r = await fetch(path, opt); }
  catch (e) { throw { error: "连不上工作台", next: "工作台窗口可能被关闭了。重新双击「启动工作台」后刷新这个页面,处理过的结果不会丢。" }; }
  const ct = r.headers.get("Content-Type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw (typeof data === "object" ? data : { error: data });
  return data;
}

function toast(msg, ms) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms || 2600);
}
function showErr(e) {
  const msg = (e && e.error) || String(e);
  info([h("h2", null, "出了点问题"), h("p", null, msg), e && e.next ? h("p", { class: "muted" }, "下一步:" + e.next) : null]);
}
function info(nodes) {
  const b = $("#info-body"); b.replaceChildren(...nodes); $("#dlg-info").showModal();
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); }
  catch (_) {
    const ta = h("textarea", { style: "position:fixed;left:-9999px" }); ta.value = text; document.body.append(ta);
    ta.select(); document.execCommand("copy"); ta.remove();
  }
  toast(`已复制(${text.length.toLocaleString()} 个字符),去 AI 网页里粘贴`);
}
const fmtDur = (s) => { s = Math.round(s || 0); const m = Math.floor(s / 60); return m ? `${m} 分 ${s % 60} 秒` : `${s} 秒`; };
const fmtSize = (b) => b > 1e9 ? (b / 1e9).toFixed(1) + " GB" : b > 1e6 ? (b / 1e6).toFixed(0) + " MB" : Math.max(1, Math.round(b / 1e3)) + " KB";
const STATE = { draft: "未开始", queued: "排队中", running: "处理中", done: "已完成", failed: "失败", cancelled: "已取消", interrupted: "中断" };
const MODE = { video: "录播视频", subtitle: "字幕", slides: "仅课件" };

// ---------------- 全局状态 ----------------
async function loadState() {
  S.state = await api("GET", "/api/state");
  const ul = $("#job-list"); ul.replaceChildren();
  for (const j of S.state.jobs) {
    ul.append(h("li", { class: j.id === S.jobId ? "active" : "", onclick: () => openJob(j.id), title: j.title || j.id },
      h("span", { class: "t" }, j.title || "(未命名)"), h("span", { class: "badge " + j.state }, STATE[j.state] || j.state)));
  }
  if (!S.state.jobs.length) ul.append(h("li", { class: "muted small" }, "还没有任务"));
  $("#data-dir").textContent = "数据保存在:" + S.state.data_dir;
}

function courseOptions(sel, current) {
  sel.replaceChildren(h("option", { value: "" }, "不选(未分类)"));
  for (const [id, c] of Object.entries(S.state.courses || {})) sel.append(h("option", { value: id, selected: id === current }, (c.code ? c.code + " · " : "") + (c.name || id)));
  sel.append(h("option", { value: "__new" }, "+ 新建课程…"));
}

async function newCourse() {
  const dlg = $("#dlg-course"); $("#form-course").reset(); dlg.showModal();
  return new Promise((resolve) => {
    dlg.addEventListener("close", async function once() {
      dlg.removeEventListener("close", once);
      if (dlg.returnValue !== "ok") return resolve(null);
      const f = new FormData($("#form-course"));
      try {
        const r = await api("POST", "/api/courses", Object.fromEntries(f));
        await loadState(); resolve(r.id);
      } catch (e) { showErr(e); resolve(null); }
    });
  });
}

async function newJob() {
  await loadState();
  const modes = S.state.modes || {};
  document.querySelectorAll("#form-new .mode").forEach((lab) => {
    const inp = lab.querySelector("input"), m = modes[inp.value];
    lab.querySelectorAll(".dep").forEach((x) => x.remove());
    if (!m) return;
    if (!m.ok) lab.append(h("span", { class: "dep", style: "grid-column:2;color:var(--err)" }, "这台电脑暂时不能用:缺少 " + m.missing.join("、") + (m.hint ? "。" + m.hint : "")));
    else if (m.hint) lab.append(h("span", { class: "dep", style: "grid-column:2;color:var(--warn)" }, m.hint));
    else if (inp.value === "video" && !m.model) lab.append(h("span", { class: "dep", style: "grid-column:2" }, "第一次处理视频会下载约 1.6 GB 的语音模型"));
  });
  const sel = $("#new-course"); courseOptions(sel, "");
  sel.onchange = async () => { if (sel.value === "__new") { const id = await newCourse(); courseOptions(sel, id || ""); } };
  const dlg = $("#dlg-new"); dlg.showModal();
  dlg.onclose = async () => {
    if (dlg.returnValue !== "ok") return;
    const f = Object.fromEntries(new FormData($("#form-new")));
    if (f.course_id === "__new") f.course_id = "";
    try { const j = await api("POST", "/api/jobs", f); await loadState(); openJob(j.id); }
    catch (e) { showErr(e); }
  };
}

// ---------------- 任务页 ----------------
async function openJob(id) {
  S.jobId = id; S.summary = null; closeEvidence();
  history.replaceState(null, "", "#job=" + id);
  $("#welcome").hidden = true; $("#job").hidden = false;
  await refreshJob(true);
  await loadState();
}

async function refreshJob(full) {
  if (!S.jobId) return;
  let j;
  try { j = await api("GET", `/api/jobs/${S.jobId}`); }
  catch (e) { if (full) showErr(e); return; }
  const prevState = S.job && S.job.state;
  S.job = j;
  if (full || !S.view) render();
  else { renderInputs(); renderProcess(); if (prevState !== j.state) { render(); loadState(); } }
  clearTimeout(S.poll);
  if (j.state === "running" || j.state === "queued") S.poll = setTimeout(() => refreshJob(false), 1500);
}

function render() {
  const j = S.job;
  S.view = {};
  const root = $("#job");
  const title = h("input", { value: j.title || "", placeholder: "给这节课起个名字", onchange: (e) => saveMeta({ title: e.target.value }) });
  const date = h("input", { type: "date", value: j.date || "", onchange: (e) => saveMeta({ date: e.target.value }) });
  const csel = h("select", {}); courseOptions(csel, j.course_id || "");
  csel.onchange = async () => {
    if (csel.value === "__new") { const id = await newCourse(); if (id) await saveMeta({ course_id: id }); else courseOptions(csel, j.course_id || ""); }
    else await saveMeta({ course_id: csel.value });
  };
  const tsel = h("select", { onchange: (e) => saveMeta({ template: e.target.value }) },
    h("option", { value: "full", selected: j.template === "full" }, "完整版:详细解释、章节、例题、复习卡"),
    h("option", { value: "concise", selected: j.template === "concise" }, "简明版:核心概念、例题、重点、自测题"));

  S.view.inputs = h("div", { class: "inputs" });
  S.view.process = h("div");
  root.replaceChildren(
    h("div", { class: "card" },
      h("h2", null, "① 材料 ", h("span", { class: "badge" }, MODE[j.mode])),
      h("div", { class: "row" }, h("label", null, "名称", title), h("label", null, "日期(可不填)", date)),
      h("div", { class: "row" }, h("label", null, "课程", csel), h("label", null, "笔记档位", tsel)),
      S.view.inputs,
      advanced(j)),
    h("div", { class: "card" }, h("h2", null, "② 本地处理"), S.view.process),
    aiCard(j),
    importCard(j),
    h("div", { class: "card", id: "preview-card" }, h("h2", null, "⑤ 预览、检查与导出"), h("div", { id: "preview" }, h("p", { class: "muted" }, "导入 AI 的回复后在这里显示。"))),
    h("div", { class: "card no-print" }, h("h2", null, "其它"),
      h("div", { class: "btns" },
        h("a", { href: `/api/jobs/${j.id}/diagnostics`, class: "small" }, "导出诊断信息(不含课程内容)"),
        h("button", { type: "button", class: "link danger", onclick: deleteJob }, "删除这个任务")),
      h("p", { class: "muted small" }, "删除只会删掉工作台里这个任务的处理结果和笔记;你的原视频、字幕、课件文件不会被删除。")));
  renderInputs(); renderProcess();
  if ((j.ai.versions || []).length) loadSummary();
}

function advanced(j) {
  const o = j.options;
  const busy = j.state === "running" || j.state === "queued";
  const opt = (k, v) => saveMeta({ options: { [k]: v } });
  return h("details", { class: "no-print" }, h("summary", null, "高级设置(一般不用改)"),
    h("div", { class: "row" },
      j.mode !== "slides" ? h("label", null, "授课语言",
        h("select", { disabled: busy || j.mode !== "video", onchange: (e) => saveMeta({ lang: e.target.value }) },
          ...[["en", "英文"], ["zh", "中文"], ["auto", "自动识别"]].map(([v, t]) => h("option", { value: v, selected: j.lang === v }, t)))) : null,
      h("label", null, "笔记语言",
        h("select", { onchange: (e) => saveMeta({ note_lang: e.target.value }) },
          h("option", { value: "zh", selected: j.note_lang === "zh" }, "中文"), h("option", { value: "en", selected: j.note_lang === "en" }, "English")))),
    j.mode !== "slides" ? h("div", { class: "row" },
      h("label", null, h("input", { type: "checkbox", checked: o.frames, disabled: busy, onchange: (e) => opt("frames", e.target.checked) }), " 抓取录播画面并识别文字(有视频时)"),
      h("label", null, "抓帧间隔", h("input", { value: o.frame_mode, disabled: busy, onchange: (e) => opt("frame_mode", e.target.value) })),
      j.mode === "video" ? h("label", null, "语音模型", h("select", { disabled: busy, onchange: (e) => opt("whisper_model", e.target.value) },
        ...["large-v3-turbo", "small", "base", "tiny"].map((m) => h("option", { value: m, selected: o.whisper_model === m }, m + (m === "large-v3-turbo" ? "(推荐,约 1.6 GB)" : ""))))) : null,
      j.mode === "video" ? h("label", null, h("input", { type: "checkbox", checked: o.vad, disabled: busy, onchange: (e) => opt("vad", e.target.checked) }), " 静音检测(减少课间的错误文字)") : null) : null,
    h("label", null, "分段复制时每块大约多少字符", h("input", { type: "number", min: 8000, step: 1000, value: o.chunk_chars, onchange: (e) => opt("chunk_chars", parseInt(e.target.value, 10)) })),
    h("p", { class: "muted small" }, "改了这些设置后需要重新点「开始处理」,受影响的步骤会自动重做,其它步骤保留。"));
}

function fileRow(label, f, role, index) {
  const busy = S.job.state === "running" || S.job.state === "queued";
  return h("div", { class: "file" },
    h("span", { class: "n", title: f.name }, `${label}:${f.name}`, h("span", { class: "muted small" }, `  ${fmtSize(f.size)}`),
      f.exists === false ? h("b", { style: "color:var(--err)" }, "  找不到文件") : null),
    h("span", null,
      role !== "slides" ? h("button", { type: "button", class: "link", disabled: busy, onclick: () => pick(role) }, "重新选择") : null,
      h("button", { type: "button", class: "link danger", disabled: busy, onclick: () => removeInput(role, index) }, "移除")));
}

function renderInputs() {
  const j = S.job, el = S.view.inputs, inp = j.inputs;
  const busy = j.state === "running" || j.state === "queued";
  const items = [];
  if (j.mode === "video") {
    items.push(inp.video ? fileRow("视频", inp.video, "video") : h("button", { type: "button", class: "primary", disabled: busy, onclick: () => pick("video") }, "选择录播视频"));
    items.push(inp.cam ? fileRow("第二路录像", inp.cam, "cam") : h("button", { type: "button", class: "link", disabled: busy, onclick: () => pick("cam") }, "+ 第二路录像(实物投影/手写,可选)"));
  }
  if (j.mode === "subtitle") {
    items.push(inp.subtitle ? fileRow("字幕", inp.subtitle, "subtitle") : h("button", { type: "button", class: "primary", disabled: busy, onclick: () => pick("subtitle") }, "选择字幕文件"));
    items.push(inp.video ? fileRow("视频(可选)", inp.video, "video") : h("button", { type: "button", class: "link", disabled: busy, onclick: () => pick("video") }, "+ 录播视频(可选:用于抓画面、点来源跳转播放)"));
  }
  (inp.slides || []).forEach((s, i) => items.push(fileRow("课件", s, "slides", i)));
  items.push(h("button", { type: "button", class: j.mode === "slides" && !(inp.slides || []).length ? "primary" : "link", disabled: busy, onclick: () => pick("slides") },
    j.mode === "slides" ? "+ 添加课件 PDF" : "+ 课件 PDF(可选,可多选)"));
  const drop = h("div", { class: "drop" }, "也可以把文件拖到这里(字幕、PDF 直接拖;视频建议用上面的按钮选择,拖进来会复制一份占用磁盘)");
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); uploadFiles(Array.from(e.dataTransfer.files)); });
  const fileIn = h("input", { type: "file", multiple: true, id: "file-upload", accept: ".srt,.vtt,.pdf,.md,.mp4,.mkv,.mov,.webm,.m4v,.m4a,.mp3,.wav", disabled: busy,
    onchange: (e) => { const fs = Array.from(e.target.files); e.target.value = ""; uploadFiles(fs); } });   // FileList 是实时的,清空前先复制
  drop.append(h("div", { class: "small" }, "或者 ", h("label", { class: "link-like" }, "从电脑上传文件", fileIn)));
  const missing = [];
  if (j.mode !== "slides" && !(inp.slides || []).length) missing.push("没有课件:笔记不会有课件页码来源");
  if (j.mode === "subtitle" && !inp.video) missing.push("没有视频:不能抓画面,点来源时不能跳转播放");
  el.replaceChildren(...items, drop, ...missing.map((m) => h("div", { class: "notice" }, m)));
}

async function pick(role) {
  try {
    toast("正在打开文件选择窗口(可能在浏览器后面)…", 4000);
    const r = await api("POST", `/api/jobs/${S.jobId}/pick`, { role });
    if (r.cancelled) return;
    afterInput(r);
  } catch (e) { showErr(e); }
}
async function uploadFiles(files) {
  for (const f of files) {
    const ext = f.name.toLowerCase().split(".").pop();
    let role = { srt: "subtitle", vtt: "subtitle", pdf: "slides", md: "summary", markdown: "summary" }[ext];
    if (!role && ["mp4", "mkv", "mov", "webm", "m4v", "m4a", "mp3", "wav"].includes(ext)) role = S.job.inputs.video && /-2\.\w+$/.test(f.name) ? "cam" : "video";
    if (!role) { showErr({ error: `「${f.name}」不是支持的文件类型`, next: "支持视频、.srt/.vtt 字幕、PDF 课件、.md 笔记" }); continue; }
    if (role === "summary") { $("#paste").value = await f.text(); toast("已放进导入框,点「检查并保存」"); continue; }
    toast(`正在导入 ${f.name}(${fmtSize(f.size)})…`, 60000);
    try { afterInput(await api("POST", `/api/jobs/${S.jobId}/upload?role=${role}&name=${encodeURIComponent(f.name)}`, f, true)); }
    catch (e) { showErr(e); }
  }
}
async function afterInput(r) {
  if (r.message) toast(r.message, 6000);
  else if (r.suggest_code && !S.job.course_id) {
    toast(`文件名里识别到课程代码 ${r.suggest_code},可以在「课程」里新建这门课`, 5000);
  } else toast("已添加");
  S.job = r.job; render(); loadState();
}
async function removeInput(role, index) {
  try { S.job = await api("POST", `/api/jobs/${S.jobId}/remove`, { role, index }); render(); } catch (e) { showErr(e); }
}
async function saveMeta(body) {
  try {
    S.job = await api("POST", `/api/jobs/${S.jobId}/meta`, body);
    if (body.course_id !== undefined || body.template !== undefined) render();
    if (body.title !== undefined) loadState();
  } catch (e) { showErr(e); render(); }
}

const ICON = { pending: "○", running: "◐", done: "●", failed: "✕", cancelled: "–", interrupted: "!", skipped: "–" };
function renderProcess() {
  const j = S.job, el = S.view.process;
  const busy = j.state === "running" || j.state === "queued";
  const failed = j.pipeline.find((s) => s.status === "failed" || s.status === "interrupted");
  const list = h("ul", { class: "stages" }, ...j.pipeline.map((s) => {
    const p = s.progress;
    let right = "";
    if (s.status === "done") right = s.elapsed != null ? fmtDur(s.elapsed) : "完成";
    else if (s.status === "running") right = "进行中";
    else if (s.status === "failed") right = "失败";
    else if (s.status === "interrupted") right = "中断";
    else if (s.status === "cancelled") right = "已取消";
    const color = { done: "var(--ok)", failed: "var(--err)", interrupted: "var(--err)", running: "var(--accent)" }[s.status] || "var(--muted)";
    return h("li", null, h("span", { class: "ic", style: `color:${color}` }, ICON[s.status] || "○"),
      h("div", null, s.name, p && p.label ? h("div", { class: "p" }, p.label + (p.total ? `(${p.done}/${p.total})` : "")) : null),
      h("span", { class: "small muted" }, right, s.status === "done" && !busy ? h("button", { type: "button", class: "link small", title: "输入没变时也强制重做这一步", onclick: () => redo(s.key) }, "重做") : null));
  }));
  const kids = [];
  if (j.state === "draft" || j.state === "cancelled") kids.push(h("p", { class: "muted small" }, "点「开始处理」后,关闭浏览器也会继续处理;关闭「工作台」窗口会中断当前这一步(下次可以继续,已完成的步骤不会重做)。"));
  kids.push(list);
  if (failed && failed.error) {
    const e = failed.error;
    kids.push(h("div", { class: "errbox" },
      h("b", null, `「${failed.name}」没有完成:`), " ", e.what,
      e.saved ? h("div", { class: "small" }, e.saved) : null,
      e.next ? h("div", null, "下一步:" + e.next) : null,
      h("div", { class: "btns" },
        h("button", { type: "button", class: "primary", onclick: start }, j.state === "interrupted" ? "继续" : "重试"),
        /找不到|重新选择/.test(e.what + e.next) ? h("button", { type: "button", onclick: () => pick(j.mode === "subtitle" ? "subtitle" : j.mode === "slides" ? "slides" : "video") }, "重新选择文件") : null,
        h("button", { type: "button", class: "link", onclick: () => showLog(failed.key) }, "技术细节"))));
  }
  for (const n of j.notices || []) kids.push(h("div", { class: "notice" }, n));
  const subIss = (j.info || {}).subtitle_issues || [];
  for (const i of subIss) kids.push(h("div", { class: "notice" }, "字幕检查:" + i.msg));
  if (j.info && j.state === "done") {
    const i = j.info;
    kids.push(h("dl", { class: "kv" },
      i.duration ? [h("dt", null, "录播时长"), h("dd", null, fmtDur(i.duration))] : null,
      i.n_segments != null && j.mode !== "slides" ? [h("dt", null, "转写"), h("dd", null, `${i.n_segments} 段(按分钟)`)] : null,
      i.n_frames ? [h("dt", null, "画面"), h("dd", null, `${i.n_frames} 张` + (i.n_cam ? `,手写页 ${i.n_cam} 张` : ""))] : null,
      i.n_pages ? [h("dt", null, "课件"), h("dd", null, `${i.n_pages} 页`)] : null));
    const cands = (i.glossary_candidates || []).filter((t) => !((j.course || {}).glossary || []).includes(t));
    if (cands.length && j.course_id) {
      kids.push(h("details", null, h("summary", null, `课件里找到 ${cands.length} 个可能的专有名词(确认后加入这门课的术语表)`),
        h("p", { class: "muted small" }, "术语表会写进 AI 提示词,也会在下次转写时提示语音识别。只加你确认拼写正确的词。"),
        h("div", { class: "btns" }, ...cands.map((t) => h("button", { type: "button", class: "small", onclick: async (ev) => {
          try { S.job = await api("POST", `/api/jobs/${j.id}/glossary`, { add: [t] }); ev.target.disabled = true; toast(`已加入术语表:${t}`); } catch (e) { showErr(e); }
        } }, "+ " + t)))));
    }
  }
  const btns = h("div", { class: "btns" });
  if (!busy && j.state !== "failed" && j.state !== "interrupted") btns.append(h("button", { type: "button", class: "primary", onclick: start }, j.state === "done" ? "重新检查并更新" : "开始处理"));
  if (busy) btns.append(h("button", { type: "button", onclick: cancel }, "取消"));
  if (busy) btns.append(h("span", { class: "muted small" }, j.state === "queued" ? "排队中:前面还有任务在处理" : "处理中…可以关闭浏览器,工作台会继续处理"));
  kids.push(btns);
  el.replaceChildren(...kids);
}

async function start() { try { S.job = await api("POST", `/api/jobs/${S.jobId}/start`, {}); render(); refreshJob(false); loadState(); } catch (e) { showErr(e); } }
async function cancel() { try { await api("POST", `/api/jobs/${S.jobId}/cancel`, {}); toast("正在取消…"); refreshJob(false); } catch (e) { showErr(e); } }
async function redo(stage) { try { S.job = await api("POST", `/api/jobs/${S.jobId}/redo`, { stage }); toast("已标记,点「开始处理」时会重做这一步及之后的步骤"); render(); } catch (e) { showErr(e); } }
async function showLog(stage) {
  try { const r = await api("GET", `/api/jobs/${S.jobId}/log?stage=${stage}`); info([h("h2", null, "技术细节"), h("pre", { style: "white-space:pre-wrap;max-height:60vh;overflow:auto;font-size:12px" }, r.text || "(没有日志)")]); }
  catch (e) { showErr(e); }
}
async function deleteJob() {
  const b = $("#info-body");
  info([h("h2", null, "删除这个任务?"), h("p", null, "会删掉工作台里的处理结果、AI 材料和导入的笔记。原视频、字幕、课件文件不会被删除。"),
    h("button", { type: "button", class: "danger", onclick: async () => {
      try { await api("POST", `/api/jobs/${S.jobId}/delete`, {}); $("#dlg-info").close(); S.jobId = null; $("#job").hidden = true; $("#welcome").hidden = false; loadState(); }
      catch (e) { showErr(e); }
    } }, "确认删除")]);
}

// ---------------- ③ 交给 AI ----------------
function aiCard(j) {
  const card = h("div", { class: "card" }, h("h2", null, "③ 交给网页版 AI"));
  if (!j.has_material || !j.material) { card.append(h("p", { class: "muted" }, "本地处理完成后,这里会生成 AI 材料。")); return card; }
  const m = j.material, n = (m.chunks || []).length;
  const tabs = h("div", { class: "tabs" });
  const body = h("div");
  const mk = (key, label) => h("button", { type: "button", class: S.aiTab === key ? "on" : "", onclick: () => { S.aiTab = key; render(); } }, label);
  tabs.append(mk("upload", "上传文件(推荐)"), mk("chunks", `分段复制(备用,${n} 段)`));
  if (S.aiTab === "upload") {
    body.append(
      h("ol", { class: "note" },
        h("li", null, "下载 AI 材料文件:", h("a", { href: `/api/jobs/${j.id}/material?kind=full&download=1` }, `AI材料-${j.id}.md`), h("span", { class: "muted small" }, `(约 ${m.chars.toLocaleString()} 个字符)`)),
        h("li", null, "打开你常用的 AI 网页版(ChatGPT、Claude 等),新建对话,把这个文件上传(拖进对话框或点回形针)。"),
        h("li", null, "回到这里点下面的按钮复制提示词,粘贴到同一条消息里发送。", h("div", { class: "btns" },
          h("button", { type: "button", class: "primary", onclick: async () => copy((await api("GET", `/api/jobs/${j.id}/prompt?kind=upload`)).text) }, "复制提示词"))),
        h("li", null, "AI 回复完以后,把它的完整回复复制下来,贴到下面「④ 导入 AI 的回复」。如果回复停在一半,在 AI 那里说「继续」,把后面的内容也接上。")),
      h("details", null, h("summary", null, "网页版不能上传文件?"),
        h("p", { class: "small" }, "可以把提示词和资料全文一起复制,直接粘贴发送。资料很长时 AI 可能读不全,这时请改用「分段复制」。"),
        h("button", { type: "button", onclick: async () => copy((await api("GET", `/api/jobs/${j.id}/prompt?kind=paste`)).text) }, "复制提示词 + 全部资料")));
  } else {
    body.append(h("p", { class: "small" }, `资料切成了 ${n} 段:以分钟/课件页为单位,切口尽量选在课间静音、课件跳页或换页处(这是启发式规则,可能切在一段讲解中间,所以每段开头附了上一段的结尾)。每段都包含它需要的课件文字,可以单独发送、单独重做。在同一个 AI 对话里依次发送每一段,把每段的回复贴进对应的格子;全部贴好后复制「整合提示词」发送,最后把整合后的回复贴到 ④。`));
    const partsBox = h("div");
    body.append(partsBox);
    loadParts(partsBox, j, m);
  }
  card.append(tabs, body);
  return card;
}

async function loadParts(box, j, m) {
  let data;
  try { data = await api("GET", `/api/jobs/${j.id}/parts`); } catch (e) { showErr(e); return; }
  const overall = h("ul", { class: "issues" });
  const renderOverall = (iss) => overall.replaceChildren(...(iss.length ? iss : [{ level: "info", msg: "所有分段都已贴好,可以复制整合提示词了" }]).map(issueLi));
  const rows = (m.chunks || []).map((c) => {
    const ta = h("textarea", { placeholder: `把第 ${c.no} 段的 AI 回复贴在这里` }); ta.value = data.parts[String(c.no)] || "";
    const iss = h("ul", { class: "issues" }, ...(data.issues[String(c.no)] || []).map(issueLi));
    const save = async () => {
      try { const r = await api("POST", `/api/jobs/${j.id}/parts/${c.no}`, { text: ta.value }); iss.replaceChildren(...r.issues.map(issueLi)); renderOverall(r.overall); toast(`第 ${c.no} 段已保存`); }
      catch (e) { showErr(e); }
    };
    return h("div", { class: "chunk" },
      h("div", null, h("b", null, `第 ${c.no}/${m.chunks.length} 段`), h("span", { class: "muted small" }, `  ${c.range} · 约 ${c.chars.toLocaleString()} 字符`)),
      h("div", { class: "btns" },
        h("button", { type: "button", class: "primary", onclick: async () => copy((await api("GET", `/api/jobs/${j.id}/prompt?kind=chunk&no=${c.no}`)).text) }, `复制第 ${c.no} 段(含提示词)`),
        h("a", { href: `/api/jobs/${j.id}/material?kind=chunk&no=${c.no}&download=1`, class: "small" }, "下载这一段")),
      ta, h("div", { class: "btns" }, h("button", { type: "button", onclick: save }, "保存这一段的回复")), iss);
  });
  renderOverall(data.overall);
  box.replaceChildren(...rows, h("h3", null, "整合"), overall,
    h("button", { type: "button", class: "primary", onclick: async () => {
      try { copy((await api("GET", `/api/jobs/${j.id}/prompt?kind=merge`)).text); } catch (e) { showErr(e); }
    } }, "复制整合提示词"));
}

// ---------------- ④ 导入 ----------------
function importCard(j) {
  const ta = h("textarea", { id: "paste", placeholder: "把 AI 的完整回复粘贴在这里(从第一行到最后一行)" });
  return h("div", { class: "card" }, h("h2", null, "④ 导入 AI 的回复"),
    !j.has_material ? h("p", { class: "muted small" }, "(也可以先不处理,直接导入一份已有的笔记来检查)") : null,
    ta,
    h("div", { class: "btns" },
      h("button", { type: "button", class: "primary", onclick: async () => {
        try { S.summary = await api("POST", `/api/jobs/${j.id}/summary`, { text: ta.value, source: ta.dataset.source || "paste" }); ta.value = ""; delete ta.dataset.source; renderSummary(); toast("已保存为新版本"); refreshJob(false); }
        catch (e) { showErr(e); }
      } }, "检查并保存"),
      h("button", { type: "button", onclick: async () => {
        try { const r = await api("POST", `/api/jobs/${j.id}/pick`, { role: "summary" }); if (r.text !== undefined) { ta.value = r.text; ta.dataset.source = "file"; toast("已读入,点「检查并保存」"); } }
        catch (e) { showErr(e); }
      } }, "从 .md 文件导入")),
    h("p", { class: "muted small" }, "每次导入都会保存成一个新版本,旧版本不会被覆盖。"));
}

function issueLi(i) {
  const tag = { error: "问题", warn: "提醒", info: "说明" }[i.level];
  return h("li", { class: i.level }, `${tag}${i.line ? `(第 ${i.line} 行)` : ""}:${i.msg}`, i.fix ? h("span", { class: "fix" }, i.fix) : null);
}

async function loadSummary(v) {
  try { S.summary = await api("GET", `/api/jobs/${S.jobId}/summary${v ? "?v=" + v : ""}`); renderSummary(); } catch (e) { showErr(e); }
}

function renderSummary() {
  const pv = $("#preview"); const s = S.summary;
  if (!pv || !s || !s.version) return;
  const vsel = h("select", { onchange: (e) => loadSummary(parseInt(e.target.value, 10)) },
    ...s.versions.slice().reverse().map((x) => h("option", { value: x.v, selected: x.v === s.version.v }, `第 ${x.v} 版 · ${x.created.replace("T", " ")}` + ({ paste: " · 粘贴", file: " · 文件", "model-session": " · 模型测试回复" }[x.source] || "") + (x.errors ? ` · ${x.errors} 个问题` : ""))));
  const errs = s.issues.filter((i) => i.level === "error").length, warns = s.issues.filter((i) => i.level === "warn").length;
  const note = h("div", { class: "note" }); note.innerHTML = s.html;   // 服务器端已整体转义
  note.addEventListener("click", (e) => { const b = e.target.closest(".cite[data-id]"); if (b) openEvidence(b.dataset.id); });
  const v = s.version.v, jid = S.jobId;
  pv.replaceChildren(
    h("div", { class: "row no-print" }, h("label", null, "版本", vsel)),
    h("p", { class: "muted small no-print" }, `这一版按「${s.template_name}」的结构检查(导入时的档位)。`,
      s.stale_material ? h("b", null, "本地材料在这一版导入之后重新生成过;这一版仍按导入时的来源编号检查和回查。") : null),
    h("details", { open: errs > 0 || warns > 0, class: "no-print" }, h("summary", null, `检查结果:${errs} 个问题,${warns} 个提醒`), h("ul", { class: "issues" }, ...s.issues.map(issueLi))),
    h("div", { class: "btns no-print" },
      h("a", { href: `/api/jobs/${jid}/export?fmt=md&v=${v}` }, "导出 Markdown"),
      h("a", { href: `/api/jobs/${jid}/export?fmt=obsidian&v=${v}` }, "导出 Obsidian 格式"),
      h("a", { href: `/api/jobs/${jid}/export?fmt=html&v=${v}` }, "导出网页(HTML)"),
      h("button", { type: "button", class: "link", onclick: () => window.print() }, "打印 / 存为 PDF")),
    h("p", { class: "muted small no-print" }, "点正文里的蓝色来源标签,可以在右侧看到原文、课件页或截图;有视频时可以直接跳到那一刻播放。"),
    note);
}

// ---------------- 来源面板 ----------------
async function openEvidence(id) {
  const panel = $("#evidence"), body = $("#ev-body");
  panel.hidden = false; $("#ev-title").textContent = "来源 " + id; body.replaceChildren(h("p", { class: "muted" }, "加载中…"));
  let e;
  const ver = S.summary && S.summary.version ? `?v=${S.summary.version.v}` : "";
  try { e = await api("GET", `/api/jobs/${S.jobId}/source/${encodeURIComponent(id)}${ver}`); }
  catch (err) { body.replaceChildren(h("p", null, err.error || "加载失败"), err.next ? h("p", { class: "muted small" }, err.next) : null); return; }
  const kids = [h("p", null, h("b", null, e.label), e.range ? h("span", { class: "muted small" }, "  " + e.range) : null)];
  if (e.video && e.t != null) {
    const at = Math.max(0, Math.floor(e.t) - 2);
    const vid = h("video", { controls: true, preload: "metadata", src: `${e.video}#t=${at}` });
    vid.addEventListener("loadedmetadata", () => { if (vid.currentTime < at - 1) vid.currentTime = at; }, { once: true });
    kids.push(vid, h("p", { class: "muted small" }, "已定位到这段话之前 2 秒。"));
  }
  if (e.image) {
    const img = h("img", { src: e.image, alt: e.label, loading: "lazy" });
    img.addEventListener("error", () => img.replaceWith(h("p", { class: "muted small" }, "(图片无法显示,只能看文字)")));
    kids.push(img);
  }
  if (e.slide) kids.push(h("p", null, "这张画面对应课件 ", h("button", { type: "button", class: "cite", onclick: () => openEvidence(e.slide) }, e.slide_label || e.slide)));
  if (e.text) kids.push(h("pre", null, e.text));
  if (e.kind === "S") kids.push(h("p", { class: "muted small" }, "转写可能有错字,重要内容请结合视频或课件核对。"));
  for (const c of e.context || []) kids.push(h("details", null, h("summary", null, `前后文 ${c.id} · ${c.label}`), h("pre", null, c.text)));
  body.replaceChildren(...kids);
}
function closeEvidence() { $("#evidence").hidden = true; $("#ev-body").replaceChildren(); }

// ---------------- 说明 ----------------
function privacy() {
  info([h("h2", null, "你的数据去了哪里"),
    h("ul", null,
      h("li", null, "视频转文字、抓画面、识别画面文字、读课件:全部在你的电脑上完成,不上传。"),
      h("li", null, "第一次处理视频时会从 Hugging Face 下载语音识别模型(约 1.6 GB),只下载,不上传任何东西。"),
      h("li", null, "你把「AI 材料」发给 ChatGPT / Claude 等网页版时,材料里的文字(转写、课件文字、画面识别出的文字)会发到对应公司的服务器。截图不会自动发送。"),
      h("li", null, "如果以后用 Claude Code / Codex 等命令行工具自动总结,同样会把文字发到云端模型。"),
      h("li", null, "工作台只在本机 127.0.0.1 上运行,局域网里的其他设备访问不到。")),
    h("p", { class: "muted small" }, "录播和课件的版权属于学校和老师,请按学校规定只供个人学习使用。")]);
}
function help() {
  info([h("h2", null, "使用说明"),
    h("ol", null,
      h("li", null, "点「新建任务」,选你手上的材料:录播视频、字幕文件,或只有课件。"),
      h("li", null, "选文件(视频只记录位置,不会被移动或复制),可以再加课件 PDF。"),
      h("li", null, "点「开始处理」。处理中可以关闭浏览器;关闭工作台窗口会中断当前这一步,下次可以继续。"),
      h("li", null, "下载 AI 材料,上传到 AI 网页版,复制提示词一起发送。"),
      h("li", null, "把 AI 的完整回复贴回「④」,点「检查并保存」。"),
      h("li", null, "在「⑤」里看检查结果,点来源标签核对原文,导出 Markdown / HTML。")),
    h("p", { class: "muted small" }, "检查只能确认格式、来源编号和时间是否有效,不能保证内容完全正确;标了「待核对」的地方请自己看原文。")]);
}

document.addEventListener("DOMContentLoaded", async () => {
  $("#btn-new").onclick = newJob; $("#btn-new-2").onclick = newJob;
  $("#btn-privacy").onclick = privacy; $("#btn-help").onclick = help;
  $("#ev-close").onclick = closeEvidence; $("#info-close").onclick = () => $("#dlg-info").close();
  try { await loadState(); } catch (e) { showErr(e); return; }
  const hp = new URLSearchParams(location.hash.slice(1));   // #job=<任务号>&src=<来源编号>:可收藏的直达链接
  const target = hp.get("job") && S.state.jobs.find((j) => j.id === hp.get("job"));
  const running = S.state.jobs.find((j) => j.state === "running" || j.state === "queued" || j.state === "interrupted");
  if (target) { await openJob(target.id); if (hp.get("src")) setTimeout(() => openEvidence(hp.get("src")), 300); }
  else if (running) openJob(running.id);
});

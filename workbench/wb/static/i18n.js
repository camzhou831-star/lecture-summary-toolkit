// 中英双语。界面文字都从这里取:t("key", {变量})。页面里写死的元素用 data-i18n / data-i18n-ph / data-i18n-title / data-i18n-html 标记。
// 后端返回的进度和报错是中文,trServer() 按开头匹配翻成英文;对不上的原样显示(运行日志、核对报告是技术输出,不翻)。
const I18N = {
  zh: {
    app: "总结工作台", local: "本地", search: "搜索总结标题…", theme: "切换深浅色", settings: "设置", langBtn: "EN", langTitle: "Switch to English",
    nav_home: "新建总结", nav_home_d: "贴链接或选文件", nav_lib: "资料库", nav_lib_d: "所有总结任务", nav_tpl: "模板", nav_tpl_d: "总结的结构和写法",
    nav_set: "设置", nav_set_d: "AI、登录、程序", recent: "最近", all: "全部", side_ai: "写总结的 AI",
    home_h1: "贴一个链接,出一份课程总结",
    home_p: "YouTube、Twitch、Vimeo、学校录播(Panopto / Kaltura……)等网页链接,或本地视频 / 音频 / 字幕。带时间线,时间戳可点回原视频。",
    source_ph: "粘贴视频链接(YouTube、Twitch、Vimeo、学校录播页……),或本地文件路径",
    lang_title: "视频语言", lang_auto: "视频语言:自动", lang_zh: "视频语言:中文", lang_en: "视频语言:英文",
    out_title: "总结语言", out_zh: "总结:中文", out_en: "总结:English",
    pick_file: "选文件", pick_file_t: "选本地文件", start: "开始总结", pick_tpl: "选模板",
    foot_note: "要登录才能看的(学校录播、Coursera 等)先到「设置 → 网站登录」选浏览器;实在拿不到就下载后选文件或拖进来。抖音暂不支持。",
    drop: "松开即上传",
    lib_crumb: "总结工作台 / 资料库", lib_p: "所有总结任务。点一行打开。", lib_search: "搜索标题…",
    f_all: "全部", f_bili: "B 站", f_web: "其他网站", f_local: "本地", s_all: "全部状态", s_done: "完成", s_running: "进行中", s_failed: "失败",
    th_title: "标题", th_src: "来源", th_lang: "语言", th_status: "状态", th_time: "用时", th_when: "时间",
    tpl_crumb: "总结工作台 / 模板", tpl_p: "模板决定总结的结构和写法。选好模板后在「新建总结」里贴链接。",
    set_crumb: "总结工作台 / 设置", set_p: "写总结的 AI、网站登录、配色、本机程序和数据位置。改设置不用重启。",
    set_ai: "写总结用哪个 AI",
    set_ai_note: "有 Claude Pro / Max 或 ChatGPT Plus / Pro 的话,装好对应的命令行工具并登录一次就能用,<b>不用 API Key</b>,用量算在你的订阅里。没有订阅才需要 API Key:写进 <code id=\"cfg-path\"></code> 的 <code>api_key</code>。",
    set_login: "网站登录",
    set_login_note: "学校的 Panopto / Echo360 / Kaltura、Coursera、Udemy 这类要登录的视频:选一个你已经登录过的浏览器,下载时借用它的登录状态。只在本机用,不上传;不需要就保持「不用」。",
    set_palette: "配色", set_palette_note: "低饱和的绿、紫、蓝绿看着更放松。深浅色跟随系统,也可以点顶栏的月亮手动切。",
    set_tools: "本机程序", set_data: "数据",
    d_open: "原视频", d_open_t: "在原站打开", d_copy: "复制", d_copy_t: "复制 Markdown", d_dl: "下载", d_dl_t: "下载 .md", d_retry: "重跑", d_del_t: "删除",
    tab_sum: "总结", tab_tr: "文字稿", tab_log: "日志", player_empty: "点任意时间戳,在这里播放", chapters: "章节", chapters_hint: "点一下跳到这一段",
    st_fetch: "拿文字稿", st_prepare: "整理讲义稿", st_summarize: "写总结", st_check: "核对时间戳",
    kind_youtube: "YouTube", kind_bilibili: "B 站", kind_local: "本地文件", kind_web: "网页",
    status_queued: "排队中", status_running: "进行中", status_done: "完成", status_failed: "失败", done_warn: "完成(核对有问题)",
    step_failed: "失败", step_now: "进行中…", step_queued: "排队中", step_wait: "等待",
    sec: "{n} 秒", min_sec: "{m} 分 {s} 秒", just_now: "刚刚", min_ago: "{n} 分钟前", hr_ago: "{n} 小时前", date: "{m}月{d}日",
    sum_lang: "{l}总结 · {ago}", l_zh: "中文", l_en: "English",
    tag_selected: "已选", tag_ready: "可用", tag_soon: "即将上线",
    tpl_course: "课程总结", tpl_course_d: "录播课、公开课。七节固定结构 + 复习卡,时间戳自动核对。",
    tpl_course_p: ["课程通知", "一句话概括", "核心要点(带时间段)", "章节时间线(可回跳)", "金句 / 考点信号", "复习卡 8–15 张"],
    tpl_bench: "对标拆稿", tpl_bench_d: "短视频口播逐句拆:作用分段、秒数、字数、信息点。", tpl_bench_p: ["逐句拆稿表", "结构骨架", "可复用句式"],
    tpl_meet: "会议纪要", tpl_meet_d: "会议录音:议题、结论、待办和负责人。", tpl_meet_p: ["议题", "结论", "待办与负责人"],
    pal_sage: "鼠尾草", pal_sage_d: "灰绿 + 米白,最安静", pal_lav: "薰衣草暮色", pal_lav_d: "灰紫 + 浅杏,傍晚的感觉", pal_mist: "晨雾", pal_mist_d: "雾蓝绿,清爽",
    pal_changed: "已换成「{n}」",
    model_local: " · 本机账号", model_auto: "(自动)", model_none: "还没有能用的 AI,见「设置」",
    p_auto: "自动选择", p_auto_d: "有 API Key 用 API;没有就用本机的 Claude Code,再没有用 Codex", p_auto_now: "现在会用 {n}", p_auto_none: "没有能用的",
    p_claude: "Claude Code(Claude Pro / Max 订阅)", p_codex: "Codex(ChatGPT Plus / Pro 账号)", p_api: "API Key(DeepSeek 或任意 OpenAI 兼容接口)",
    p_claude_d: "用你登录的 Claude Pro / Max 订阅。没装:npm i -g @anthropic-ai/claude-code,再运行一次 claude 登录",
    p_codex_d: "用你登录的 ChatGPT Plus / Pro 账号。没装:npm i -g @openai/codex(或 brew install codex),再运行一次 codex 登录",
    p_api_d: "DeepSeek 或任意 OpenAI 兼容接口,按量付费", p_ok: "可用", p_no: "不可用", p_not_found: "没找到 {c} 命令", p_no_key: "没填 API Key",
    saved: "已保存", cookies_off: "不用(默认)", cookies_use: "借用 {b} 的登录状态", cookies_saved: "已保存;第一次读取时系统可能会问你是否允许", cookies_closed: "已关闭",
    tool_ytdlp: "网页视频链接", tool_ffmpeg: "转写前抽音频", tool_ffprobe: "读视频时长", tool_whisper: "本地转写", tool_model: "本地转写(第一次用时自动下载)", not_found: "没找到",
    data_tasks: "任务", data_count: "共 {t} 个 · 完成 {d} · 失败 {f}", data_dir: "数据目录", data_note_k: "说明", data_note: "每个任务一个文件夹,里面有文字稿、讲义稿和总结 .md;不进 git。",
    no_tasks: "还没有任务", lib_none: "没有符合条件的任务", lib_empty: "还没有任务,去「新建总结」贴一个链接",
    submitting: "提交中…", uploading: "上传 {n}…",
    failed_pane: "没有生成总结。原因见上方提示和「日志」;修好后点「重跑」。", chapters_wait: "总结写好后显示章节", chapters_none: "总结里没有章节时间线",
    transcript_empty: "文字稿是空的", no_media: "这个任务没有本地视频(只有字幕)",
    web_player: "这个网站不能嵌在页面里播放", web_open: "在原网站打开 {t} ↗", web_note: "Twitch、Vimeo 会直接跳到这个时间;其它网站可能要手动拖到 {t}",
    copied: "已复制 Markdown", copy_fail: "复制失败", requeued: "已重新排队", del_confirm: "删除这个任务和它的文字稿、总结?", deleted: "已删除",
    title_detail: "总结",
  },
  en: {
    app: "Lecture Workbench", local: "Local", search: "Search summaries…", theme: "Toggle dark mode", settings: "Settings", langBtn: "中", langTitle: "切换到中文",
    nav_home: "New summary", nav_home_d: "Paste a link or pick a file", nav_lib: "Library", nav_lib_d: "All summaries", nav_tpl: "Templates", nav_tpl_d: "How summaries are structured",
    nav_set: "Settings", nav_set_d: "AI, logins, tools", recent: "Recent", all: "All", side_ai: "AI for summaries",
    home_h1: "Paste a link, get a lecture summary",
    home_p: "Links from YouTube, Twitch, Vimeo, university lecture capture (Panopto, Kaltura…) and more, or a local video, audio or subtitle file. With a timeline whose timestamps jump back into the video.",
    source_ph: "Paste a video link (YouTube, Twitch, Vimeo, a lecture-capture page…) or a local file path",
    lang_title: "Video language", lang_auto: "Video: auto-detect", lang_zh: "Video: Chinese", lang_en: "Video: English",
    out_title: "Summary language", out_zh: "Summary: 中文", out_en: "Summary: English",
    pick_file: "Choose file", pick_file_t: "Choose a local file", start: "Summarize", pick_tpl: "Template",
    foot_note: "For lectures behind a login (university recordings, Coursera…), pick your browser under Settings → Site login first. If that still fails, download the video and drop the file here. Douyin is not supported.",
    drop: "Drop to upload",
    lib_crumb: "Workbench / Library", lib_p: "Every summary you have made. Click a row to open it.", lib_search: "Search titles…",
    f_all: "All", f_bili: "Bilibili", f_web: "Other sites", f_local: "Local", s_all: "Any status", s_done: "Done", s_running: "Running", s_failed: "Failed",
    th_title: "Title", th_src: "Source", th_lang: "Language", th_status: "Status", th_time: "Took", th_when: "Added",
    tpl_crumb: "Workbench / Templates", tpl_p: "A template decides how a summary is structured and written. Pick one, then paste a link under New summary.",
    set_crumb: "Workbench / Settings", set_p: "Which AI writes summaries, site logins, colours, local tools and where data lives. No restart needed.",
    set_ai: "Which AI writes the summary",
    set_ai_note: "With Claude Pro / Max or ChatGPT Plus / Pro, install the matching command-line tool and sign in once: <b>no API key needed</b>, usage counts against your plan. Only without a plan do you need an API key: put it as <code>api_key</code> in <code id=\"cfg-path\"></code>.",
    set_login: "Site login",
    set_login_note: "For videos behind a login (Panopto / Echo360 / Kaltura at your university, Coursera, Udemy): choose a browser you are signed in with and downloads will borrow its login. Stays on this computer. Leave it on \"Off\" if you don't need it.",
    set_palette: "Colours", set_palette_note: "Low-saturation greens, purples and teals feel calmer. Light/dark follows your system; use the moon button in the top bar to switch.",
    set_tools: "Local tools", set_data: "Data",
    d_open: "Source", d_open_t: "Open on the original site", d_copy: "Copy", d_copy_t: "Copy Markdown", d_dl: "Download", d_dl_t: "Download .md", d_retry: "Re-run", d_del_t: "Delete",
    tab_sum: "Summary", tab_tr: "Transcript", tab_log: "Log", player_empty: "Click any timestamp to play from there", chapters: "Chapters", chapters_hint: "Click to jump",
    st_fetch: "Get transcript", st_prepare: "Prepare", st_summarize: "Write summary", st_check: "Check timestamps",
    kind_youtube: "YouTube", kind_bilibili: "Bilibili", kind_local: "Local file", kind_web: "Web",
    status_queued: "Queued", status_running: "Running", status_done: "Done", status_failed: "Failed", done_warn: "Done (check found issues)",
    step_failed: "Failed", step_now: "Working…", step_queued: "Queued", step_wait: "Waiting",
    sec: "{n}s", min_sec: "{m}m {s}s", just_now: "just now", min_ago: "{n} min ago", hr_ago: "{n} h ago", date: "{mon} {d}",
    sum_lang: "{l} summary · {ago}", l_zh: "Chinese", l_en: "English",
    tag_selected: "Selected", tag_ready: "Ready", tag_soon: "Coming soon",
    tpl_course: "Lecture summary", tpl_course_d: "Recorded lectures and public courses. Fixed seven-part structure plus review cards; timestamps checked automatically.",
    tpl_course_p: ["Course notices", "One-sentence summary", "Key points (with time ranges)", "Timeline (click to jump back)", "Quotes / exam signals", "8–15 review cards"],
    tpl_bench: "Script breakdown", tpl_bench_d: "Sentence-by-sentence breakdown of short videos: role, seconds, word count, information points.", tpl_bench_p: ["Sentence table", "Structure skeleton", "Reusable phrasing"],
    tpl_meet: "Meeting notes", tpl_meet_d: "Meeting recordings: topics, decisions, action items and owners.", tpl_meet_p: ["Topics", "Decisions", "Action items and owners"],
    pal_sage: "Sage", pal_sage_d: "Grey-green and cream, the calmest", pal_lav: "Lavender dusk", pal_lav_d: "Grey-violet and apricot, like early evening", pal_mist: "Morning mist", pal_mist_d: "Misty blue-green, fresh",
    pal_changed: "Switched to {n}",
    model_local: " · your account", model_auto: " (auto)", model_none: "No AI available yet — see Settings",
    p_auto: "Automatic", p_auto_d: "Uses your API key if set, otherwise Claude Code on this computer, otherwise Codex", p_auto_now: "currently {n}", p_auto_none: "nothing available",
    p_claude: "Claude Code (Claude Pro / Max plan)", p_codex: "Codex (ChatGPT Plus / Pro plan)", p_api: "API key (DeepSeek or any OpenAI-compatible API)",
    p_claude_d: "Uses the Claude Pro / Max plan you are signed in with. Not installed? npm i -g @anthropic-ai/claude-code, then run claude once to sign in",
    p_codex_d: "Uses the ChatGPT Plus / Pro plan you are signed in with. Not installed? npm i -g @openai/codex (or brew install codex), then run codex once to sign in",
    p_api_d: "DeepSeek or any OpenAI-compatible API, pay as you go", p_ok: "Ready", p_no: "Unavailable", p_not_found: "{c} command not found", p_no_key: "no API key set",
    saved: "Saved", cookies_off: "Off (default)", cookies_use: "Borrow {b}'s login", cookies_saved: "Saved. Your system may ask for permission the first time.", cookies_closed: "Turned off",
    tool_ytdlp: "web video links", tool_ffmpeg: "extract audio before transcribing", tool_ffprobe: "read video length", tool_whisper: "local transcription", tool_model: "local transcription (downloads on first use)", not_found: "not found",
    data_tasks: "Tasks", data_count: "{t} total · {d} done · {f} failed", data_dir: "Data folder", data_note_k: "Note", data_note: "One folder per task with the transcript and the summary .md. Not tracked by git.",
    no_tasks: "No tasks yet", lib_none: "Nothing matches these filters", lib_empty: "No tasks yet — paste a link under New summary",
    submitting: "Submitting…", uploading: "Uploading {n}…",
    failed_pane: "No summary was written. See the message above and the Log tab; fix the problem, then click Re-run.", chapters_wait: "Chapters appear once the summary is written", chapters_none: "This summary has no timeline",
    transcript_empty: "The transcript is empty", no_media: "This task has no local video (subtitles only)",
    web_player: "This site can't be embedded here", web_open: "Open at {t} on the original site ↗", web_note: "Twitch and Vimeo jump straight to this time; on other sites you may need to seek to {t} yourself",
    copied: "Markdown copied", copy_fail: "Copy failed", requeued: "Queued again", del_confirm: "Delete this task with its transcript and summary?", deleted: "Deleted",
    title_detail: "Summary",
  },
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

let LANG = (() => {
  const q = typeof location === "undefined" ? null : new URLSearchParams(location.search).get("lang");   // ?lang=en / ?lang=zh 优先(分享和截图用)
  if (q === "zh" || q === "en") return q;
  try { const s = localStorage.getItem("wb-lang"); if (s === "zh" || s === "en") return s; } catch (_) {}
  return ((typeof navigator !== "undefined" && navigator.language) || "en").toLowerCase().startsWith("zh") ? "zh" : "en";
})();

function t(key, vars) {
  let s = (I18N[LANG] && I18N[LANG][key]) ?? I18N.zh[key] ?? key;
  if (vars && typeof s === "string") s = s.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
  return s;
}

function applyI18n(root = document) {
  document.documentElement.lang = LANG === "zh" ? "zh-CN" : "en";
  document.title = t("app");
  root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
  root.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
  root.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
}

// 后端的中文进度 / 报错 → 英文(按开头匹配;对不上的原样返回)
const SERVER_EN = [
  [/^排队中$/, "Queued"], [/^重新排队$/, "Queued again"], [/^上次未完成,重新排队$/, "Interrupted last time, queued again"],
  [/^拿文字稿…$/, "Getting the transcript…"], [/^整理讲义稿…$/, "Preparing the transcript…"], [/^写总结…$/, "Writing the summary…"], [/^核对时间戳…$/, "Checking timestamps…"],
  [/^写总结… 已生成 (\d+) 字$/, "Writing the summary… $1 characters so far"],
  [/^核对没过,让模型按检查结果改一轮…$/, "The check found issues; asking the AI to fix them…"],
  [/^完成,格式与时间戳校验通过$/, "Done — format and timestamps checked"], [/^完成,但核对还有问题/, "Done, but the check still found issues (see Log)"],
  [/^没有填链接或文件路径/, "Paste a link or a file path first"],
  [/^抖音链接/, "Douyin links aren't supported yet. Download the video and choose the file instead."],
  [/^B 站链接里认不出 BV 号/, "Couldn't find a BV id in this Bilibili link"], [/^YouTube 链接里认不出视频 id/, "Couldn't find a video id in this YouTube link"],
  [/^找不到文件 (.*)/, "File not found: $1"], [/^不支持的文件类型 (\S+)/, "Unsupported file type $1 (use video, audio, .srt or .vtt)"],
  [/^短链接打不开/, "Couldn't open the short link"], [/^找不到 (\S+);安装: (.*)/, "$1 not found. Install it with: $2"],
  [/^转写失败/, "Transcription failed (see Log)"],
  [/^B 站 CDN 拒绝了下载/, "Bilibili's CDN refused the download (HTTP 567). Download the video yourself and choose the file."],
  [/^B 站音频没下载下来/, "Couldn't download the Bilibili audio (rate limit, login or paid video). Download it yourself and choose the file."],
  [/^YouTube 字幕和音频都没拿到/, "Couldn't get subtitles or audio from YouTube (rate limit or login). Download it yourself and choose the file."],
  [/^yt-dlp 不认识这个网页/, "yt-dlp doesn't recognise this page (maybe no video, or it's inside an embedded player). Open the video's own page and copy that link, or download it and choose the file."],
  [/^拿不到视频信息。这个网站可能要登录/, "Couldn't read the video. This site probably needs a login (Panopto, Echo360, Kaltura, Coursera, Udemy…). Pick your signed-in browser under Settings → Site login and re-run, or download the video and choose the file."],
  [/^拿不到视频信息/, "Couldn't read the video information (see Log)"],
  [/^音频没下载下来/, "The audio didn't download. The site may need a login: pick your browser under Settings → Site login, or download it yourself."],
  [/^没拿到文字稿/, "No transcript was produced"], [/^(compact|build_bundle)\.py 失败/, "Preparing the transcript failed (see Log)"],
  [/^没有能用的模型/, "No AI available: install and sign in to Claude Code or Codex, or add an API key (see Settings)"],
  [/^没有配置模型 Key/, "No API key set: set DEEPSEEK_API_KEY or add api_key to ~/.config/lecture-workbench/config.json"],
  [/^找不到命令 (\S+)/, "Command not found: $1"], [/^(\S+) 超过 (\d+) 分钟没写完/, "$1 didn't finish within $2 minutes"],
  [/^(claude|codex) 出错\(没登录的话先在终端运行一次 \S+ 登录\)/, "$1 failed — if you're not signed in, run $1 once in a terminal to sign in"],
  [/^(claude|codex) 出错/, "$1 failed (see Log)"], [/^Claude Code 出错/, "Claude Code reported an error (see Log)"],
  [/(Claude Code|Codex|模型)没有返回内容/, "The AI returned nothing"], [/^模型接口返回 (\d+)/, "The API returned HTTP $1"], [/^连不上模型接口/, "Can't reach the API"],
  [/^未预期的错误/, "Unexpected error (see Log)"],
  [/^不支持的视频语言/, "Unsupported video language"], [/^总结语言只能是/, "Summary language must be zh or en"], [/^没有这个任务/, "Task not found"],
  [/^总结还没生成/, "The summary isn't ready yet"], [/^文字稿还没拿到/, "The transcript isn't ready yet"], [/^没有本地媒体文件/, "No local media file"],
  [/^任务正在跑/, "This task is still running"], [/^不认识的模型来源/, "Unknown AI option"], [/^不认识的浏览器/, "Unknown browser"],
];
function trServer(msg) {
  if (!msg || LANG === "zh") return msg || "";
  for (const [re, en] of SERVER_EN) {
    const m = msg.match(re);
    if (m) return en.replace(/\$(\d)/g, (_, i) => m[+i] ?? "");   // 只返回英文句子,不带后面的中文细节(细节在日志里)
  }
  return msg;
}

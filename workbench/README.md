# 总结工作台(workbench)

录播课总结工具的本地网页版:**贴视频链接(或选本地文件)→ 自动拿带时间戳的文字稿 → 让 AI 写课程总结 → 自动核对时间戳**,结果在网页上看,时间戳点了跳到原视频对应时间。

只在本机运行(`127.0.0.1`),不做账号和安装包。面向使用者的介绍见仓库根目录的 [README.zh.md](../README.zh.md)。

## 启动

最省事:在 Finder 里双击仓库根目录的 `启动工作台.command`(它就是调 `setup.sh`;第一次要按住 Control 点 → 打开)。在终端里则是 `bash setup.sh`(缺的工具用 Homebrew 装好、`uv sync`、检查写总结的 AI,然后启动并打开浏览器;可以重复运行,`--no-start` 只装不启动)。首页的「开始前检查」卡片会列出还缺什么、给可复制的命令,全部就绪后收成一行。

手动的话:

需要:[uv](https://docs.astral.sh/uv/)、`yt-dlp`、`ffmpeg`、`whisper-cli`(macOS:`brew install uv yt-dlp ffmpeg whisper-cpp`)。whisper 模型第一次转写时自动下载(约 1.6 GB,和录播课工具共用 `~/.local/share/whisper-models/`)。

1. 选写总结的 AI(在「设置」里也能改;默认"自动":有 API Key 用 API,否则本机 Claude Code,再否则 Codex):

   - **Claude Code**:装好 `claude` 并登录 Claude Pro / Max,不用 Key。工作台在空的临时目录里跑 `claude -p`,禁用改文件和联网的工具
   - **Codex**:装好 `codex` 并登录 ChatGPT Plus / Pro,不用 Key。跑 `codex exec --sandbox read-only`
   - **API**:环境变量 `DEEPSEEK_API_KEY`,或写配置文件 `~/.config/lecture-workbench/config.json`:

     ```json
     {"api_key": "sk-...", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"}
     ```

     `base_url` / `model` 可省略(默认 DeepSeek `deepseek-chat`),换成任意 OpenAI 兼容接口也行。

   配置文件里还会存「设置」页的选择:`provider`(auto / claude / codex / api)、`cookies_browser`(要登录的网站借用哪个浏览器的登录状态,默认空)。文件权限 600。

2. 启动:

   ```bash
   cd workbench
   uv run python -m wb
   ```

   打开 <http://127.0.0.1:8770>。端口被占时用 `PORT=8771 uv run python -m wb`。

## 怎么用

- **贴链接**:YouTube、B 站(可以连分享文案一起贴,`b23.tv` 短链也行),以及 yt-dlp 支持的任意网页(Twitch、Vimeo、TED、SoundCloud、Kaltura、Panopto……);或本地文件的路径;或点"选文件"上传视频 / 音频 / `.srt` / `.vtt`。
- **要登录的网站**:「设置 → 网站登录」选一个登录过的浏览器,yt-dlp 用 `--cookies-from-browser` 借它的登录状态(只在本机)。
- **视频语言**:自动 = B 站按中文转写、YouTube 和其它网站找英文字幕;中文视频选"中文"。
- **任务**:一次跑一个,其余排队。每个任务显示四步进度和每步用时:拿文字稿 → 整理讲义稿 → 写总结 → 核对时间戳。失败了点"重跑",已拿到的文字稿会复用。
- **结果**:Markdown 渲染。点任意时间戳,页面上方嵌入原视频并跳到那一秒(本地文件用页面里的播放器);按住 ⌘/Ctrl 点在原站打开。"复制 Markdown" 拿到的总结里,章节时间线已带回跳原视频的链接,可以直接放进 Obsidian。

## 怎么处理的

| 步骤 | 做什么 | 代码 |
|---|---|---|
| 拿文字稿 | B 站:yt-dlp 匿名只下音频 → whisper 转写;YouTube 和其它网页:yt-dlp 先下字幕,没有就下音频 + whisper;本地:字幕直接用,音视频走 whisper | `wb/sources.py`(逻辑复制自拉片流程的 `script_fetch.py`,whisper 改调本仓库 `工具/transcribe.py`,按系统找 whisper-cli,带 VAD) |
| 整理讲义稿 | `工具/compact.py` 滤幻觉、按分钟合并;`工具/build_bundle.py` 出讲义稿;再把 `[时:分]` 换成 `[分:秒]`(该分钟第一句的开始时间),模型照抄即可 | `wb/pipeline.py` |
| 写总结 | 系统提示 = `templates/course.md`(网页模式说明)+ `skills/video-summary/policy.md` 原文;交给本机 Claude Code / Codex,或 OpenAI 兼容 API(流式) | `wb/pipeline.py`、`wb/llm.py` |
| 核对时间戳 | 章节时间线加回跳链接,跑 `工具/check_summary.py`;没过就把报告交回模型改一轮再核 | `wb/pipeline.py` |

每个任务的文件在 `workbench/data/tasks/<id>/`(目录结构同录播课工具的 `COURSE_ROOT`:`课程视频/` 放 srt 和讲义稿,`总结/` 放总结),任务表是 `workbench/data/workbench.db`。`data/` 已在 `.gitignore`,不会进仓库。

## 模板

| 模板 | 给 AI 的输入 | AI 写什么 | 程序做什么 | 核对 |
|---|---|---|---|---|
| 课程总结 `course` | 按分钟合并的讲义稿 `[MM:SS]` | 七节固定结构(`policy.md`) | 章节时间线加回跳链接 | `工具/check_summary.py` |
| 对标拆稿 `breakdown` | 逐句表(长段按句号、逗号切开,时间按字数分,约 ±1 秒) | 分段 JSON(10 个作用词、新信息点)+ 逐段要点、可学的写法、收藏点与借鉴边界 | 开头 / 结尾 15 秒原文、分段表、全片指标(`wb/breakdown.py`,口径照拉片流程的 `srt_stats.py`);标题块里的播放、点赞、评论和"大爆款 / 小爆款"门槛 | 分段要从第 1 句连到最后一句;必需小节;时间戳 |
| 会议纪要 `meeting.<类型>` | 讲义稿 `[MM:SS]` | 按会议模板逐节填写,引用处照抄时间戳 | — | 必需小节;时间戳 |

会议模板在 `templates/meeting/*.json`,5 种取自 [Meetily](https://github.com/Zackriya-Solutions/meetily)(MIT,见该目录的 README 和 `LICENSE-meetily`),拼提示词的规则照它的 Rust 代码改写进 `wb/templates.py`。核对没过时,三种模板都会把报告交回 AI 改一轮。

## 界面

纯 HTML + CSS + JS,不用构建。界面中英双语:文字都在 `wb/static/i18n.js`(加功能时两套一起加,测试会查漏)。配色、圆角、阴影和动效时长 / 缓动取自 [TreeUI](https://github.com/Viserion77/treeui)(MIT)的设计 token(`docs/ai/TOKENS.yaml`),布局照它的 dashboard 示例:顶栏 + 左侧功能导航 + 浅灰内容面板 + 白色卡片。浅色 / 深色跟随系统,顶栏按钮可以手动切;⌘K 聚焦搜索。

颜色没有用 TreeUI 默认的蓝白,换成三套低饱和的放松配色(复习本来就烦,界面不要再刺眼),在「设置 → 配色」里切换,选择记在浏览器里:**鼠尾草**(默认,灰绿 + 米白)、**薰衣草暮色**(灰紫 + 浅杏)、**晨雾**(雾蓝绿)。每套都有深色版;内容区铺一层很淡的色雾,主按钮和首页标题用渐变,首页背后有几团慢慢漂动的柔光(系统开了「减少动态效果」就不动)。

## 测试

```bash
cd workbench
uv run pytest -q
```

不联网、不需要 whisper 和 Key(模型调用用假的替换,也不会去调本机的 claude / codex):链接识别(含 Twitch、Vimeo 等网页)、YouTube 滚动字幕去重、模型来源的自动选择、浏览器登录状态开关、讲义稿时间戳换算、时间线链接、本地字幕 → 总结 → check_summary 的整条流水线(含核对没过时改一轮)、接口。

## 实测(2026-11-24,Mac)

| 来源 | 拿文字稿 | 整理 | 写总结 | 核对 | 结果 |
|---|---|---|---|---|---|
| YouTube:MIT 6.006 第 1 讲(45:38,自动字幕) | 4.7 秒 | 0.1 秒 | 22.3 秒(输入 1.2 万 token,输出 2.5 千) | 0.1 秒 | 一次通过 check_summary;抽查的原话在字幕里都找得到 |
| 本地音频:3Blue1Brown 神经网络(18:39) | 30.3 秒(whisper 转写) | 0.1 秒 | 17.0 秒(输入 8.5 千,输出 3 千) | 0.1 秒 | 一次通过 |
| B 站:李宏毅机器学习 2022 p01(32:26) | 96.4 秒(下音频 + whisper 转写) | 0.1 秒 | 20.0 秒(输入 1 万,输出 2.5 千) | 0.1 秒 | 一次通过;课程通知、15 讲安排都写进去了 |
| TED:Sal Khan 演讲(网页字幕)+ **Claude Code** | 14.3 秒 | 0.1 秒 | 76.7 秒 | 0.1 秒 | 一次通过,没用 API Key |
| 同一条 + **Codex** | 13.5 秒 | 0.1 秒 | 62.1 秒 | 44.1 秒(核对没过,改了一轮) | 改一轮后通过,没用 API Key |
| SoundCloud 讲座(40 分钟,无字幕)+ Claude Code | 306.6 秒(下音频 + whisper) | 0.1 秒 | 97.3 秒 | 0.0 秒 | 一次通过 |
| Vimeo | — | | | | 这条视频现在要登录才能看,提示正确;没测「借浏览器登录状态」 |

| 对标拆稿:B 站《别被同事发现…1分钟搞定高颜值动效网站》(44 秒,6078 赞) | 6.8 秒 | 0 秒 | 5.8 秒 | 0 秒 | 17 句、6 段,钩子 5.2 秒,321 字/分;一次通过 |
| 会议纪要(项目同步,中文):GitLab Language Server 周会(25 分钟) | 4.1 秒 | 0 秒 | 8.2 秒 | 0 秒 | 里程碑、风险、6 条决定、8 条待办,一次通过 |
| 会议纪要(标准会议,英文):GitLab Package 周会(15 分钟) | 3.9 秒 | 0 秒 | 6.6 秒 | 0 秒 | 一次通过 |

前三行和最后三行写总结用的是 DeepSeek `deepseek-chat`。Twitch 回放的链接解析和时间跳转有单元测试,没跑真实视频。

B 站注意:yt-dlp(2026.10.26)直接下载会被 B 站 CDN 回 HTTP 567([yt-dlp#17847](https://github.com/yt-dlp/yt-dlp/issues/17847),还没修)。工作台按 issue 里的临时解法给 B 站下载加了 `Range: bytes=0-` 请求头(`wb/sources.py` 的 `BILI_DL_ARGS`),等 yt-dlp 修好后可以删掉。

页面上点时间戳,嵌入的 YouTube 播放器跳到对应秒数(已在浏览器里验证)。

## 限制

- 对标拆稿面向几分钟内的短视频口播,整节课这种长视频会拆得很慢;收藏数 yt-dlp 一般拿不到,写"未取到"。
- 会议纪要不区分说话人(没有声纹识别),参会人只能从对话内容推断。
- 界面中英双语(`wb/static/i18n.js`,顶栏切换或 `?lang=en`);运行日志和核对报告是技术输出,保持中文。
- 抖音不支持(匿名下载会被限流)。要登录的网站靠「借浏览器登录状态」,这条路还没实测;拿不到就自己下载后选文件。
- 只在 macOS 上测过;Windows 理论上能跑(找 whisper-cli 用的是录播课工具的跨平台逻辑),没验证。
- 没有画面:网页视频不抓帧、不 OCR,总结里没有截图和课件页码。
- 平台限流或要登录时任务会失败并提示"自己下载再选文件"。
- whisper 片尾可能编句子、专有名词常错;总结里会标"转写疑似",结尾仍建议人工核一下。
- 下载他人视频只做个人学习研究,不要再分发。

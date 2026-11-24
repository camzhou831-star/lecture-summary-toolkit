# 总结工作台(workbench,第一期 MVP)

录播课总结工具的本地网页版:**贴 B 站 / YouTube 链接(或选本地文件)→ 自动拿带时间戳的文字稿 → 调模型写课程总结 → 自动核对时间戳**,结果在网页上看,时间戳点了跳到原视频对应时间。

只在本机运行(`127.0.0.1`),不做账号和安装包。构想和后续计划见 [`docs/工作台构想.md`](../docs/工作台构想.md)。

## 启动

需要:[uv](https://docs.astral.sh/uv/)、`yt-dlp`、`ffmpeg`、`whisper-cli`(macOS:`brew install uv yt-dlp ffmpeg whisper-cpp`)。whisper 模型第一次转写时自动下载(约 1.6 GB,和录播课工具共用 `~/.local/share/whisper-models/`)。

1. 配置模型 Key(只放在本机,不进仓库),二选一:

   ```bash
   export DEEPSEEK_API_KEY=sk-...
   ```

   或写配置文件 `~/.config/lecture-workbench/config.json`:

   ```json
   {"api_key": "sk-...", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"}
   ```

   `base_url` / `model` 可省略(默认 DeepSeek `deepseek-chat`);换成任意 OpenAI 兼容接口也行。

2. 启动:

   ```bash
   cd workbench
   uv run python -m wb
   ```

   打开 <http://127.0.0.1:8770>。端口被占时用 `PORT=8771 uv run python -m wb`。

## 怎么用

- **贴链接**:B 站链接(可以连分享文案一起贴,`b23.tv` 短链也行)、YouTube 链接;或本地文件的路径;或点"选文件"上传视频 / 音频 / `.srt` / `.vtt`。
- **视频语言**:自动 = B 站按中文转写、YouTube 下英文字幕;中文 YouTube 视频选"中文"。
- **任务**:一次跑一个,其余排队。每个任务显示四步进度和每步用时:拿文字稿 → 整理讲义稿 → 写总结 → 核对时间戳。失败了点"重跑",已拿到的文字稿会复用。
- **结果**:Markdown 渲染。点任意时间戳,页面上方嵌入原视频并跳到那一秒(本地文件用页面里的播放器);按住 ⌘/Ctrl 点在原站打开。"复制 Markdown" 拿到的总结里,章节时间线已带回跳原视频的链接,可以直接放进 Obsidian。

## 怎么处理的

| 步骤 | 做什么 | 代码 |
|---|---|---|
| 拿文字稿 | B 站:yt-dlp 匿名只下音频 → whisper 转写;YouTube:yt-dlp 下字幕(没有字幕时退回下音频 + whisper);本地:字幕直接用,音视频走 whisper | `wb/sources.py`(逻辑复制自拉片流程的 `script_fetch.py`,whisper 改调本仓库 `工具/transcribe.py`,按系统找 whisper-cli,带 VAD) |
| 整理讲义稿 | `工具/compact.py` 滤幻觉、按分钟合并;`工具/build_bundle.py` 出讲义稿;再把 `[时:分]` 换成 `[分:秒]`(该分钟第一句的开始时间),模型照抄即可 | `wb/pipeline.py` |
| 写总结 | 系统提示 = `templates/course.md`(API 模式说明)+ `skills/video-summary/policy.md` 原文;调 DeepSeek(流式) | `wb/pipeline.py`、`wb/llm.py` |
| 核对时间戳 | 章节时间线加回跳链接,跑 `工具/check_summary.py`;没过就把报告交回模型改一轮再核 | `wb/pipeline.py` |

每个任务的文件在 `workbench/data/tasks/<id>/`(目录结构同录播课工具的 `COURSE_ROOT`:`课程视频/` 放 srt 和讲义稿,`总结/` 放总结),任务表是 `workbench/data/workbench.db`。`data/` 已在 `.gitignore`,不会进仓库。

## 测试

```bash
cd workbench
uv run pytest -q
```

不联网、不需要 whisper 和 Key(模型调用用假的替换):链接识别、YouTube 滚动字幕去重、讲义稿时间戳换算、时间线链接、本地字幕 → 总结 → check_summary 的整条流水线(含核对没过时改一轮)、接口。

## 实测(2026-11-24,Mac M 系列,DeepSeek deepseek-chat)

| 来源 | 拿文字稿 | 整理 | 写总结 | 核对 | 结果 |
|---|---|---|---|---|---|
| YouTube:MIT 6.006 第 1 讲(45:38,自动字幕) | 4.7 秒 | 0.1 秒 | 22.3 秒(输入 1.2 万 token,输出 2.5 千) | 0.1 秒 | 一次通过 check_summary;抽查的原话在字幕里都找得到 |
| 本地音频:3Blue1Brown 神经网络(18:39) | 30.3 秒(whisper 转写) | 0.1 秒 | 17.0 秒(输入 8.5 千,输出 3 千) | 0.1 秒 | 一次通过 |
| B 站:李宏毅机器学习 p01、3Blue1Brown 中文版 | ❌ | | | | yt-dlp 2026.10.26 下载音频时 B 站 CDN 返回 HTTP 567,两条都一样;已提示"自己下载后选文件" |

页面上点时间戳,嵌入的 YouTube 播放器跳到对应秒数(已在浏览器里验证)。

## 限制(第一期)

- 只有"课程总结"模板、只有 API 模式;"对标拆稿"模板、AI 应用模式(只准备材料交给 Claude Code)放第二期。
- 抖音第二期再接(匿名下载会被限流);学校 LMS(Echo360)要登录,拿不到,请自己下载后选文件。
- 没有画面:网页视频不抓帧、不 OCR,总结里没有截图和课件页码。
- 平台限流或要登录时任务会失败并提示"自己下载再选文件"。
- whisper 片尾可能编句子、专有名词常错;总结里会标"转写疑似",结尾仍建议人工核一下。
- 下载他人视频只做个人学习研究,不要再分发。

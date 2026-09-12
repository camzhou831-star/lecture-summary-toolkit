# 课程总结工具 / Lecture Summary Toolkit

自动总结录播课/长视频:本地转写字幕 + 抓取幻灯片画面 + AI 生成带时间戳的章节总结与复习卡。转写与 OCR 全程本地运行、不上传内容;总结由 **Claude Code 或 Codex CLI** 任一 agent 按同一份技能文件生成。

*Local lecture-recording summarizer: whisper.cpp + Silero VAD transcription, slide OCR aligned to the transcript, and a shared skill file that drives either Claude Code or Codex CLI to write timestamped notes and flashcards. Chinese UI for now; English localisation is on the roadmap.*

## 安装

```bash
git clone git@github.com:camzhou831-star/lecture-summary-toolkit.git
cd lecture-summary-toolkit && bash install.sh
```

`install.sh` 装 ffmpeg / whisper-cpp / tesseract,并把 `skills/video-summary` 链接到 `~/.claude/skills/` 与 `~/.codex/skills/`。仓库根目录的 `CLAUDE.md`(Claude Code)与 `AGENTS.md`(Codex)都指向同一份技能,改流程只改 `skills/video-summary/SKILL.md` 再跑 `bash 工具/sync_agents.sh`。

## 用法

把课程视频放进 `课程视频/`(或留在 Downloads),在仓库目录打开 Claude Code 或 Codex,说:

> 总结 DEMO1001 - 26 Aug 20-s1-full.mp4

agent 会跑 `工具/prepare.sh` 预处理,读生成的讲义稿写总结,存到 `总结/<课程号>/`。工作目录默认是仓库根目录,可用环境变量 `COURSE_ROOT` 指到别处。也可以手动只跑预处理:

```bash
bash 工具/prepare.sh "DEMO1001 - 26 Aug 20-s1-full.mp4" en
```

## 目录说明

- `课程视频/` — 视频与全部产物放在一起:
  - `x.srt` / `x.txt` — whisper 转写(带/不带时间戳)
  - `x.compact.txt` — 按分钟合并成 `[时:分] 文本`、已滤掉幻觉行
  - `x.bundle.json` — 机器可读:转写段 + 幻灯片 OCR
  - `x.grounded.md` — **讲义稿**:逐分钟转写,中间插入该分钟出现的幻灯片 OCR 文本与课件页码;写总结只读这一份
- `画面/<视频名>/` — 幻灯片帧 `tXXXXXs.jpg`(文件名即秒数)+ `ocr.json`
- `总结/1002/`、`总结/1003/` — 各课程的总结、考点记录、知识点笔记
- `工具/`:
  - `prepare.sh <视频> [语言码]` — **一键预处理**,依次调用下面各步。已有 srt 时跳过转写、已有帧时跳过抓帧,其余步骤(compact、去重、增量 OCR、bundle)每次都跑,只要几秒;`FORCE=1` 全部重做。环境变量 `FRAME_MODE=20s`、`NO_VAD=1`、`GLOSSARY=<文件>` 透传
  - `transcribe.sh <视频> [语言码]` — ffmpeg 抽音频 + whisper-cpp 转写(8 线程);默认开 Silero VAD 静音检测、按文件名课程号自动加载 `glossary/<课程号>.txt` 术语表;whisper 失败时自动用基础参数重试一次。`NO_VAD=1` 关 VAD,`GLOSSARY=<文件>` 指定术语表
  - `compact.sh <字幕.srt>` — 压成按分钟的 compact 文本,过滤 "Thank you." 等静音段幻觉
  - `extract_frames.sh <视频> [12s|0.20] [输出目录]` — 抓幻灯片帧,默认每 12 秒采样后去重;重跑先清旧帧
  - `dedup_frames.py <画面目录> [--threshold 2] [--window 5] [--dry-run]` — 16×16 感知哈希去掉几乎相同的帧(阈值很严,只删完全重复,保留后一张)
  - `ocr_frames.py <画面目录> [--jobs 4] [--no-merge] [--force]` — tesseract OCR 写入 `ocr.json`(增量,识别失败的帧下次重试),并做三层合并:相邻同页码取字多的、前帧文字被后帧包含则删前帧、整节课里同一页/同一终端或浏览器画面只留一次。2 小时课 12 秒采样约 400 张原始帧 → 100 张左右
  - `build_bundle.py <视频或.srt> [--frames-dir 目录]` — 生成 `bundle.json` 与 `grounded.md`(每帧课件页最多 14 行 OCR、非课件画面 6 行,2 小时课约 1000 行);≥3 分钟无语音标 ⏸(会识别 VAD 把静音填进上一段的情况,以及 compact 里连续空白的分钟)
  - `check_summary.py <总结.md> [--srt] [--frames-dir]` — 校验总结:时间戳越界/秒数非法/落在静音段、截图引用不存在、缺小节、标题日期与文件名不符;有问题退出码 1
  - `sync_agents.sh` — 从技能文件生成 `AGENTS.md` 与 `CLAUDE.md`
  - `add_links.py <总结.md> [--dry-run]` — 把"章节时间线"里行首 `- ` 条目的第一个 `[MM:SS]` 变成回跳录播的链接(幂等;Obsidian 装 Media Extended 插件后可定位到秒)
- `skills/video-summary/SKILL.md` — 两个 agent 共用的工作流程;`AGENTS.md` / `CLAUDE.md` 由它生成
- `install.sh` — 一键安装依赖与技能链接

## 总结的固定结构

1. 标题 `# <课程号> 第N周(YYYY-MM-DD)— 主题`,下面引用块写讲师、课件页码、录播时长与课间、截图文件夹
2. `## ⚠️ 课程通知(起止时间)` — 考核、截止日、项目安排(2026-09-12 之前的 1003 总结没有这一节)
3. `## 一句话概括`
4. `## 核心要点` — 带时间段和课件页码,老师强调的考点加粗
5. `## 章节时间线` — `[MM:SS] 标题 — 摘要`(超过 1 小时写成 `[100:16]` 这种分钟数),时间必须来自 srt
6. `## 金句 / 考点信号`
7. `## 复习卡` — 8–15 张 `问题::答案` / `==填空==` 卡片(Obsidian Spaced Repetition 插件语法)

## 依赖

- ffmpeg、whisper-cpp(`brew install ffmpeg whisper-cpp`)
- whisper 模型放在 `~/.local/share/whisper-models/`,缺失时脚本自动下载(large-v3-turbo,约 1.6 GB)
- tesseract(`brew install tesseract`,OCR 用)
- python3 + Pillow(系统自带的 python3 已带 Pillow;没有则 `pip3 install pillow`)
- 总结在线视频需另装 `brew install yt-dlp`

## 内容与合规

- 产物(转写、截图、讲义稿、总结)是**个人学习用途**。录播与课件属于学校/讲师版权,请不要把它们或其转写上传到公开仓库、分享群。本仓库 `.gitignore` 已排除 `课程视频/`、`画面/`、`总结/`。
- 工具本身不含任何课程内容。

## 已知情况

- 录播开头几分钟和课间常是静音,whisper 会输出 "Thank you." 一类幻觉,compact.sh 已过滤常见的几种;新出现的加进脚本的 BLACKLIST 即可。
- 讲师全屏翻 PDF 时画面变化小,场景检测模式会漏页,所以默认改为定点采样模式。
- 8 月手工补抓的 `gap_t…jpg` 已统一改名为 `t…jpg`。
- Obsidian 里要用回跳链接和复习卡,需装 Media Extended 与 Spaced Repetition 两个插件(可选)。

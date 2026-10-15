---
name: video-summary
description: 自动总结长视频内容。输入本地视频/音频文件路径(或在线视频链接),用 ffmpeg+whisper-cpp 本地转写字幕,再生成带时间戳的分章节中文总结。当用户要求"总结视频"、"视频摘要"、"总结录播课"、"这个视频讲了什么"时使用。
---

# 长视频自动总结

**先定位两个目录**(每次触发本技能第一步):
- `TOOLKIT` = 本工具仓库根目录。在仓库里打开 agent 时就是当前目录;若本技能是 `install.sh` 链接安装的,用 `readlink -f` 找到本 SKILL.md 的真实路径,其上两级就是 `TOOLKIT`(`$(dirname "$(dirname "$(dirname "$(readlink -f <SKILL.md>)")")")`)。
- `COURSE_ROOT` = 课程数据目录(视频、画面、总结所在)。默认 = `TOOLKIT`;用户另有目录时 `export COURSE_ROOT=<目录>`。
下文 `工具/xxx` 一律指 `$TOOLKIT/工具/xxx`,其余相对路径相对于 `COURSE_ROOT`;`prepare.sh` 会自动创建 `课程视频/ 画面/ 总结/`。
- `工具/prepare.sh` — **一键预处理**(转写+抓帧+compact+去重+OCR+课件PDF匹配+bundle),平时只需要跑这一个;结束时打印课程信息与总结应存路径
- `工具/course_meta.py <文件名>` — 从文件名解析单元代码/日期/周次,给出总结路径;规则与年份、学期起始日在 `<COURSE_ROOT>/course.json`(可选,格式见脚本头注释)
- `工具/match_slides.py <画面目录> <课件pdf或目录>` — 用课件 PDF 文字给帧定页码(prepare.sh 在 course.json 配了 `slides_dir` 时自动跑)
- `工具/cam_frames.py <视频> <输出目录>` — 双路录像时从实物投影仪那一路挑手写页关键帧(prepare.sh 检测到 `<名>-2.mp4` 时自动跑,产物在 `画面/<名>/cam/`)
- `工具/transcribe.sh` / `compact.sh` / `extract_frames.sh` / `dedup_frames.py` / `ocr_frames.py` / `build_bundle.py` — prepare.sh 内部调用的各步骤,可单独跑
- `工具/check_summary.py` — 总结写完后的校验(时间戳越界/落在静音段、截图引用、必需小节、复习卡 8–15 张、标题日期)
- `工具/review_pack.py <总结>` — 审核前准备审核包(见 `review.md`)
- `工具/add_links.py` — 给章节时间线加可点击回跳录播的链接
- `工具/exam_bank.py <单元代码>` — 跨周考点库:把该单元所有总结的 🎯 考点信号、课程通知、考核说明、复习卡汇总成 `总结/<单元>/考点库.md`(+ `.json`),Quiz/期中前出模拟题的唯一素材
- `glossary/<课程号>.txt`(在课程目录里,不在工具仓库)— 转写术语表,按视频文件名前缀自动选用;新课程新建一份
- `课程视频/` — 视频与全部转写产物放一起:`.srt` `.txt` `.compact.txt` `.bundle.json` `.grounded.md`
- `画面/<视频名>/` — 幻灯片帧 `tXXXXXs.jpg`(文件名即秒数)+ `ocr.json`
- `总结/<课程号>/` — 总结按课程分子文件夹(取视频文件名开头的单元代码,如 `总结/DEMO1001/`);新课程新建子文件夹

## 流程

1. **确定输入**
   - 本地文件:用户给文件名或路径即可,`prepare.sh` 会在 `课程视频/`、`~/Downloads/` 里找,并把视频移入 `课程视频/`。
   - 在线链接(YouTube/B站等):先检查 `yt-dlp`(未装则 `brew install yt-dlp`),`yt-dlp -f "ba" -x --audio-format m4a -o "<COURSE_ROOT>/课程视频/%(title)s.%(ext)s" <URL>` 只下音频;先试 `--write-auto-subs --skip-download` 拿现成字幕。

2. **预处理**(后台运行;2 小时录播约 3–4 分钟)
   ```bash
   bash "$TOOLKIT/工具/prepare.sh" "<视频文件名或路径>" en
   ```
   - 语言码:英文授课传 `en`;中文视频传 `zh`;不确定传 `auto`。
   - 转写已开 VAD(静音检测)和课程术语表(课程目录下 `glossary/<单元代码>.txt`,按文件名前缀自动选;新单元先建一份),静音段基本不再产生 "Thank you." 类幻觉;若讲义稿里仍有整分钟只是同一短句反复出现,按静音处理并在总结里注明。
   - **双路录像**(UWA LMS 同一节课有 `<名>.mp4` 和 `<名>-2.mp4`):把两个文件都放进 `课程视频/`(或都留在 Downloads),只传主文件名即可。约定 `<名>.mp4` 是讲台电脑屏幕、`-2` 是实物投影仪/摄像头;prepare.sh 自动从更响的一路取声音、屏幕路照常抓幻灯片、实物投影路用 `cam_frames.py` 挑手写页(每页写完一张 + 每 3 分钟一张进度帧,2 小时课约 20–50 张,无 OCR)。哪一路是哪种画面要以讲义稿和图片为准,有的课两路会反过来。
   - 抓帧默认每 12 秒采样 + 去重 + OCR 三层合并(相邻同页、动画被包含、整节课同页/同画面只留一次),2 小时课约 100 帧;`FRAME_MODE=20s` 可再减少。已有 srt 跳过转写、已有帧跳过抓帧,其余步骤每次重跑(几秒);`FORCE=1` 全部重做;`NO_VAD=1` 关静音检测(极少需要)。
   - 产物里最重要的是 **`课程视频/<视频名>.grounded.md`**(讲义稿):逐分钟转写 `[HH:MM]`(时:分),中间插入该分钟出现的幻灯片 OCR 文本、课件页码(`p12/20`)与截图文件名,并标出无语音空档。

3. **写总结**:**先读 `$TOOLKIT/skills/video-summary/policy.md`(唯一写作规则),严格按它执行**:输入与安全、写作过程(页→节映射、图片页看图)、固定七节结构、grounding、技术核查、文风。保存路径用 `prepare.sh` 最后一行打印的路径。

4. **收尾(必做)**
   ```bash
   python3 "$TOOLKIT/工具/add_links.py" "<COURSE_ROOT>/总结/<单元代码>/<视频文件名>.md"
   python3 "$TOOLKIT/工具/check_summary.py" "<COURSE_ROOT>/总结/<单元代码>/<视频文件名>.md"
   python3 "$TOOLKIT/工具/exam_bank.py" "<单元代码或总结子目录名>"
   ```
   - `check_summary.py` 报的每一条 ❌ 都要处理(改时间戳、补小节、修引用)后再交付;⚠️ 是提醒。它不检查内容正确性,通过后在回复里如实说明"格式与时间戳校验通过"。
   - `exam_bank.py` 把本周的 🎯 考点、通知、复习卡并进该单元的 `考点库.md`(整份重生成,不要手改);它提示"没有任何 🎯 标记"时回头检查是否漏标了老师明说的考点。用户要出模拟题/复习时,读考点库而不是逐份翻总结。

5. **审核(可选)**:只在用户说"总结并审核""审核这份总结"时做,按 `$TOOLKIT/skills/video-summary/review.md` 执行(`工具/review_pack.py` 准备审核包 → 独立子代理或另一家模型只读审核 → 逐条核实后修正,最多一轮)。没要求时不跑。

## 注意

- 转写、OCR 全部本地运行;写总结和审核时,讲义稿会发给你正在使用的模型服务。
- 音频文件(mp3/m4a/wav)同样支持,只是没有抓帧和 OCR。
- 如果用户只要文字稿不要总结,直接给 `.txt` 或 `.compact.txt` 路径即可。
- 本技能对 Claude Code 与 Codex CLI 通用(两者的 SKILL.md 格式相同);`AGENTS.md` 与 `CLAUDE.md` 由 `工具/sync_agents.sh` 从本文件生成,改流程只改本文件;写作规则只改 `policy.md`,审核规则只改 `review.md`。

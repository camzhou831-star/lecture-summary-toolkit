# AGENTS.md — 录播课总结工具(Codex CLI 项目指令)

> 本文件由 `工具/sync_agents.sh` 从 `skills/video-summary/SKILL.md` 生成,不要手改。
> 当用户要求"总结视频 / 总结录播课 / 这个视频讲了什么"时,按下面流程执行;其它任务照常。


# 长视频自动总结

**和用户说话用用户的语言**:用户用英文提问就用英文回复(进度、提问、考试信息确认、报错解释都一样),不要因为本说明是中文就改用中文。脚本输出是中文的,转述给英文用户时翻译成英文。总结本身用什么语言见 `policy.md`「输出语言」。

**先定位两个目录**(每次触发本技能第一步):
- `TOOLKIT` = 本工具仓库根目录。在仓库里打开 agent 时就是当前目录;若本技能是 `install.sh` 链接安装的,用 `readlink -f` 找到本 SKILL.md 的真实路径,其上两级就是 `TOOLKIT`(`$(dirname "$(dirname "$(dirname "$(readlink -f <SKILL.md>)")")")`);Windows 上 `install.cmd` 建的是目录联接(junction),改用 `python -c "import os,sys;print(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1])))))" <SKILL.md>`。
- `COURSE_ROOT` = 课程数据目录(视频、画面、总结所在)。默认 = `TOOLKIT`;用户另有目录时 `export COURSE_ROOT=<目录>`。
下文 `工具/xxx` 一律指 `$TOOLKIT/工具/xxx`,其余相对路径相对于 `COURSE_ROOT`;`prepare.sh` 会自动创建 `课程视频/ 画面/ 总结/`。
- `lsk`(`工具/lsk.py`)— **总入口**:`doctor` 查环境、`run` 预处理(字幕或视频)、`finish` 收尾、`review` 审核包
- `工具/prepare.sh` — **一键预处理**(转写+抓帧+compact+去重+OCR+课件PDF匹配+bundle),平时只需要跑这一个;结束时打印课程信息与总结应存路径
- `工具/course_meta.py <文件名>` — 从文件名解析单元代码/日期/周次,给出总结路径;规则与年份、学期起始日在 `<COURSE_ROOT>/course.json`(可选,格式见脚本头注释)
- `工具/match_slides.py <画面目录> <课件pdf或目录>` — 用课件 PDF 文字给帧定页码(prepare.sh 在 course.json 配了 `slides_dir` 时自动跑)
- `工具/cam_frames.py <视频> <输出目录>` — 双路录像时从实物投影仪那一路挑手写页关键帧(prepare.sh 检测到 `<名>-2.mp4` 时自动跑,产物在 `画面/<名>/cam/`)
- `工具/transcribe.sh` / `compact.py` / `extract_frames.sh` / `dedup_frames.py` / `ocr_frames.py` / `build_bundle.py` — prepare.sh 内部调用的各步骤,可单独跑
- `工具/check_summary.py` — 总结写完后的校验(时间戳越界/落在静音段、截图引用、必需小节、复习卡 8–15 张、标题日期)
- `工具/review_pack.py <总结>` — 审核前准备审核包(见 `review.md`)
- `工具/headings.py` — 中英两套小节标题与文件名约定(检查脚本共用;英文标题必须与 `policy.md` 表格一字不差)
- `工具/add_links.py` — 给章节时间线加可点击回跳录播的链接
- `工具/exam_bank.py <单元代码>` — 跨周考点库:把该单元所有总结的 🎯 考点信号、课程通知、考核说明、复习卡汇总成 `总结/<单元>/考点库.md`(+ `.json`),Quiz/期中前出模拟题的唯一素材
- `glossary/<课程号>.txt`(在课程目录里,不在工具仓库)— 转写术语表,按视频文件名前缀自动选用;新课程新建一份
- `课程视频/` — 视频与全部转写产物放一起:`.srt` `.txt` `.compact.txt` `.bundle.json` `.grounded.md`
- `画面/<视频名>/` — 幻灯片帧 `tXXXXXs.jpg`(文件名即秒数)+ `ocr.json`
- `总结/<课程号>/` — 总结按课程分子文件夹(取视频文件名开头的单元代码,如 `总结/DEMO1001/`);新课程新建子文件夹

## 流程

1. **确定输入**
   - 本地文件:用户给文件名或路径即可,`prepare.sh` 会在 `课程视频/`、`~/Downloads/` 里找,并把视频移入 `课程视频/`。
   - 在线链接(YouTube/B站等):先检查 `yt-dlp`(未装则 macOS `brew install yt-dlp`,Windows `winget install -e --id yt-dlp.yt-dlp`,装完新开终端或用 `%LOCALAPPDATA%\Microsoft\WinGet\Links\yt-dlp.exe`),`yt-dlp -f "ba" -x --audio-format m4a -o "<COURSE_ROOT>/课程视频/%(title)s.%(ext)s" <URL>` 只下音频;先试 `--write-auto-subs --skip-download` 拿现成字幕。

2. **预处理**:统一用总入口 `lsk`(第一次先跑 `bash "$TOOLKIT/lsk" doctor` 看环境,缺什么按它给的命令装,装之前先征得用户同意)。
   - **Windows**:下面所有 `bash "$TOOLKIT/lsk" …` 换成 `"$TOOLKIT\lsk.cmd" …`(或 `python "$TOOLKIT\工具\lsk.py" …`),参数相同。视频模式在 Windows 上走 `工具/prepare.py`(Python 版,产物与 prepare.sh 相同):先按 `lsk doctor --video` 的提示用 winget 装 ffmpeg 和 tesseract,再跑 `lsk setup` 下载 whisper.cpp 与模型(或让用户双击 `install.cmd` 一次做完,并把技能装进 Claude Code / Codex);有 NVIDIA 显卡时 `lsk setup` 自动装 CUDA 版(约 675 MB),速度和 Mac 相近;没有 NVIDIA 显卡只能用 CPU,2 小时录播可能要几十分钟到一小时以上,提前告诉用户。`lsk doctor --video` 的 whisper-cli 一行会标出 (CUDA GPU) 或 (CPU)。
   - **字幕模式**(推荐给新手;只有 `.srt` / `.vtt` 字幕,不需要 ffmpeg、whisper):
     ```bash
     bash "$TOOLKIT/lsk" run "<字幕文件>" [--unit DEMO1001 --date 2026-08-26] [--slides <本讲课件.pdf>] [--lang zh|en]
     ```
     文件名看不出单元和日期时它会要求 `--unit/--date`,问用户。只传本讲对应的那份课件,不要传整学期的课件文件夹。
   - **视频模式**(实验性;需要 `lsk doctor --video` 全绿;2 小时录播约 3–4 分钟,后台运行):
     ```bash
     bash "$TOOLKIT/lsk" run "<视频文件名或路径>" --lang-code en
     ```
     等同于 `bash "$TOOLKIT/工具/prepare.sh" "<视频>" en`,细节如下。
   - 语言码:英文授课传 `en`;中文视频传 `zh`;不确定传 `auto`。
   - 转写已开 VAD(静音检测)和课程术语表(课程目录下 `glossary/<单元代码>.txt`,按文件名前缀自动选;新单元先建一份),静音段基本不再产生 "Thank you." 类幻觉;若讲义稿里仍有整分钟只是同一短句反复出现,按静音处理并在总结里注明。
   - **双路录像**(UWA LMS 同一节课有 `<名>.mp4` 和 `<名>-2.mp4`):把两个文件都放进 `课程视频/`(或都留在 Downloads),只传主文件名即可。约定 `<名>.mp4` 是讲台电脑屏幕、`-2` 是实物投影仪/摄像头;prepare.sh 自动从更响的一路取声音、屏幕路照常抓幻灯片、实物投影路用 `cam_frames.py` 挑手写页(每页写完一张 + 每 3 分钟一张进度帧,2 小时课约 20–50 张,无 OCR)。哪一路是哪种画面要以讲义稿和图片为准,有的课两路会反过来。
   - 抓帧默认每 12 秒采样 + 去重 + OCR 三层合并(相邻同页、动画被包含、整节课同页/同画面只留一次),2 小时课约 100 帧;`FRAME_MODE=20s` 可再减少。已有 srt 跳过转写、已有帧跳过抓帧,其余步骤每次重跑(几秒);`FORCE=1` 全部重做;`NO_VAD=1` 关静音检测(极少需要)。
   - 产物里最重要的是 **`课程视频/<视频名>.grounded.md`**(讲义稿):逐分钟转写 `[HH:MM]`(时:分),中间插入该分钟出现的幻灯片 OCR 文本、课件页码(`p12/20`)与截图文件名,并标出无语音空档。

3. **写总结**:**先读 `$TOOLKIT/skills/video-summary/policy.md`(唯一写作规则),严格按它执行**:输入与安全、写作过程(页→节映射、图片页看图)、输出语言(中文 `<名>.md` / 英文 `<名>.en.md`)、固定七节结构、grounding、考试信息、技术核查、文风。保存路径用 `prepare.sh` 最后一行打印的路径。

4. **收尾(必做)**
   ```bash
   bash "$TOOLKIT/lsk" finish "<COURSE_ROOT>/总结/<单元>/<名>.md"     # = add_links + check_summary + exam_bank
   ```
   - **考试信息交给用户确认**:总结里有考试信息(范围、题型、分值、扣分加分、截止日、考核安排)时,交付前按 `policy.md` 第 4 节逐条列给用户并注明来源,来源说法不一致的问用户以哪个为准。
   - `check_summary.py` 报的每一条 ❌ 都要处理(改时间戳、补小节、修引用)后再交付;⚠️ 是提醒。它不检查内容正确性,通过后在回复里如实说明"格式与时间戳校验通过"。
   - `exam_bank.py` 把本周的 🎯 考点、通知、复习卡并进该单元的 `考点库.md`(整份重生成,不要手改);它提示"没有任何 🎯 标记"时回头检查是否漏标了老师明说的考点。用户要出模拟题/复习时,读考点库而不是逐份翻总结。

5. **审核(可选)**:只在用户说"总结并审核""审核这份总结"时做,按 `$TOOLKIT/skills/video-summary/review.md` 执行(`工具/review_pack.py` 准备审核包 → 独立子代理或另一家模型只读审核 → 逐条核实后修正,最多一轮)。没要求时不跑。

## 注意

- 转写、OCR 全部本地运行;写总结和审核时,讲义稿会发给你正在使用的模型服务。
- 音频文件(mp3/m4a/wav)同样支持,只是没有抓帧和 OCR。
- 如果用户只要文字稿不要总结,直接给 `.txt` 或 `.compact.txt` 路径即可。
- 本技能对 Claude Code 与 Codex CLI 通用(两者的 SKILL.md 格式相同);`AGENTS.md` 与 `CLAUDE.md` 由 `工具/sync_agents.sh` 从本文件生成,改流程只改本文件;写作规则只改 `policy.md`,审核规则只改 `review.md`。

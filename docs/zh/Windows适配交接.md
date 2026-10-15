# Windows 适配交接(字幕模式 + 网页版)

> 写给接手 Windows 适配的同学。目标:**Windows 用户能用字幕模式完整版**(`lsk run` → AI 写总结 → `lsk finish`)。视频模式这次不做,Windows 上明确提示"请用字幕模式或网页版"。
> 网页版(`prompts/web-prompt.*.md`)只是文本,已经跨平台,不用改。

## 先读

- `README.zh.md`:用户怎么用。
- `skills/video-summary/SKILL.md`:智能体按什么流程调用脚本。
- `工具/lsk.py`:总入口。字幕模式只会用到这些 Python 脚本:`lsk.py`、`compact.py`、`build_bundle.py`、`course_meta.py`、`headings.py`、`check_summary.py`、`add_links.py`、`exam_bank.py`、`review_pack.py`。
- 测试:`python -m unittest discover -s tests`(macOS 上 58 个全过)。

## 已知要改的 4 类问题

1. **编码**(最容易出错)
   - Windows 默认编码不是 UTF-8。凡是读写文本的 `open()` 都要写 `encoding="utf-8"`;现在还有几处没写(多在视频模式脚本里,字幕模式脚本也要逐个确认)。
   - 脚本往终端打印中文和 emoji(✅ ❌ ⚠️ 🎯),在 GBK / cp1252 控制台会抛 `UnicodeEncodeError`。建议在每个入口脚本开头统一做 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`(或者写进一个公共小函数),`lsk.py` 调子进程时传 `PYTHONUTF8=1`。
2. **链接路径**:`add_links.py`(第 19 行附近)和 `exam_bank.py`(`linked()` 里)用 `os.path.relpath` 生成回跳录播的链接,Windows 上会出现反斜杠,Markdown / Obsidian 认不了。改成正斜杠(`pathlib.PurePath(rel).as_posix()`),并补一个测试。
3. **启动方式**
   - 根目录的 `lsk` 是 bash 脚本。加一个 `lsk.cmd`(内容类似 `@py -3 "%~dp0工具\lsk.py" %*`,注意中文路径和 `py` 不存在时退回 `python`)。
   - `lsk.py` 里用 `bash` 调 `prepare.sh` 的分支(视频模式):Windows 上直接给出提示并退出。
   - `SKILL.md` 第 2、4 步写的是 `bash "$TOOLKIT/lsk" …`,加一句 Windows 写法(`python "$TOOLKIT\工具\lsk.py" …`)。改完 SKILL.md 要跑 `bash 工具/sync_agents.sh`(Windows 上可在 Git Bash 里跑)重新生成 AGENTS.md 等,CI 会检查。
4. **`lsk doctor`**:Windows 上给 Python 的安装方法(python.org 或 `winget install Python.Python.3.12`)、pdftotext 的替代(`pip install pypdf` 就够),视频模式一行写"Windows 暂不支持,请用字幕模式或网页版"。

## 测试与验证

1. **先加 Windows CI,让问题自己暴露**:在 `.github/workflows/ci.yml` 加一个 `runs-on: windows-latest` 的 job,跑单元测试。很多现有测试用 `bash` 调脚本,Windows 上先用 `@unittest.skipIf(sys.platform == "win32", ...)` 标出来,只跑纯 Python 的部分,再逐步改成直接调 Python。
2. **端到端**:CI 里用一份合成字幕跑 `python 工具\lsk.py run x.srt --unit DEMO1001 --date 2026-08-26 --lang en`,写一份最小英文总结,再跑 `lsk.py finish`,断言检查通过、`Exam-Bank.en.md` 生成、链接里没有反斜杠。可以参照 `tests/test_tools.py` 的 `Lsk.test_run_finish_subtitle_mode`。
3. **真机**:找一台 Windows 电脑,从 Release zip 解压(用资源管理器解压,注意中文文件夹名是否正常),装一个 AI 应用(Codex / Claude Code / Gemini CLI 任一),按 README 走一遍。

## 规矩

- **不要提交任何课程内容**(真实字幕、课件、总结、术语表)。`bash tests/check_no_course_content.sh` 必须通过,CI 也会查。测试只用合成数据。
- 不改写作规则(`policy.md`、`review.md`);只改脚本、启动方式、文档。
- macOS 上现有 58 个测试必须继续全过;中文和英文总结的检查结果不能变。
- 每个修复一个提交,写清楚改了什么、怎么验证的。

## 完成标准

- Windows CI 绿(单元测试 + 字幕模式端到端)。
- 真机上从 Release zip 到拿到通过检查的总结,走通一次,记录卡点。
- README 两份的"先准备好"和支持说明改成"字幕模式与网页版支持 macOS 和 Windows,视频模式仅 macOS"。

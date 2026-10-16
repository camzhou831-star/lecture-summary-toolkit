# Windows 真机回归测试(视频模式 + 字幕模式 + 网页版)

> 写给帮忙在 Windows 电脑上测试的同学。代码已经改好(分支 `windows-subtitle`,PR #1),GitHub 上的 Windows CI(含视频模式完整流程)也通过了;这份清单是在**真实 Windows 电脑**上从头到尾走一遍,看普通用户会卡在哪。**视频模式是重点。**
> 你只需要测试、记录,不用改代码。遇到问题按最后一节的格式记下来发给我。

## 测试范围

- **重点**:视频模式(把下载好的录播视频放进来 → 转写 + 抓幻灯片 → AI 写总结)。
- **也要测**:字幕模式、网页版提示词。

## 准备

1. 一台 Windows 10 或 11 电脑。记下:系统版本、系统语言(中文 / 英文)、用户名里有没有中文。
2. 拿到测试包(我发给你的 zip,或者仓库里 `windows-subtitle` 分支的代码)。**用资源管理器右键"全部解压缩"**,不要用命令行。解压后打开看一眼:`工具`、`课程视频` 这类中文文件夹名是否正常显示。
3. 测试用的字幕:把仓库里的合成示例 `examples\demo\课程视频\DEMO1001 - 01 Jan 26-s1-demo.srt` 复制到桌面,改名为 `captions.srt`(故意让文件名看不出课程和日期)。下面的 `<合成字幕.srt>` 都指它。
4. 装一个 AI 应用:Claude Code / Codex / Gemini CLI 任选一个,用你自己的账号登录。

## 第一部分:命令行检查(每一步把输出截图或复制下来)

在解压出来的 `lecture-summary-toolkit` 文件夹里打开"命令提示符"(cmd)或 PowerShell:

| # | 操作 | 应该看到 |
|---|---|---|
| 1 | `lsk.cmd doctor` | 一行 `✅ python 3.x`;`字幕模式:可以用`;最后一行说视频模式 Windows 暂不支持。中文和 ✅ 不是乱码、没有报错 |
| 2 | 没装 Python 的电脑(如果有):`lsk.cmd doctor` | 提示怎么装 Python,而不是一堆看不懂的报错 |
| 3 | `lsk.cmd run <合成字幕.srt>` | 报错说看不出单元和日期,要求加 `--unit` 和 `--date`(提示里的 DEMO1001 只是例子) |
| 4 | `lsk.cmd run <合成字幕.srt> --unit DEMO1001 --date 2026-01-01 --lang zh` | `== 完成`;`课程视频\` 里多出 `.srt`、`.compact.txt`、`.bundle.json`、`.grounded.md` 四个文件;最后打印总结该存的路径 |
| 5 | 用记事本打开 `课程视频\DEMO1001 2026-01-01.grounded.md` | 中文和英文都正常,不是乱码 |
| 7 | 在 PowerShell 里再跑一次第 1 步 | 结果和 cmd 一样 |

## 第二部分:视频模式(重点)

测试视频:仓库里的合成示例 `examples\demo\课程视频\DEMO1001 - 01 Jan 26-s1-demo.mp4`(2 分钟)。跑通后**再用一节你自己的真实录播**(1–2 小时)测一次,记下总用时;真实录播只在你自己电脑上跑,产物不要发出来。

| # | 操作 | 应该看到 |
|---|---|---|
| V1 | `lsk.cmd doctor --video` | 列出 ffmpeg、whisper-cli、tesseract、Pillow、whisper 模型,缺的每项后面有安装命令(winget / pip / `lsk setup`) |
| V2 | 按提示装:`winget install Gyan.FFmpeg`、`winget install UB-Mannheim.TesseractOCR`、`py -m pip install pillow pypdf` | 都装成功;记下哪一步要管理员权限、有没有弹窗 |
| V3 | **不关当前窗口**,再跑 `lsk.cmd doctor --video` | ffmpeg 和 tesseract 变成 ✅(刚装完 PATH 还没刷新,工具应该自己找得到) |
| V4 | `lsk.cmd setup` | 从安装包解压 GPU 版 whisper.cpp(Vulkan),再下 CPU 兜底版(约 8 MB)和模型(约 1.6 GB,有进度百分比);最后试跑一次,打印 `✅ GPU 转写: <你的显卡名>`。如果打印的是"没用上显卡"或"启动失败",把整段输出发我,并写上显卡型号和驱动版本 |
| V5 | 把示例视频复制到 `课程视频\`,`lsk.cmd run "DEMO1001 - 01 Jan 26-s1-demo.mp4"` | 依次出现 [1/5]…[5/5],最后 `全部完成`;`画面\DEMO1001 - 01 Jan 26-s1-demo\` 里有几张 `t000xxs.jpg` |
| V6 | 记事本打开 `课程视频\DEMO1001 - 01 Jan 26-s1-demo.grounded.md` | 有英文转写(含 "prime path"),有 `📄 t=… p2/6 …` 这样的幻灯片行 |
| V7 | 真实录播:放进 `课程视频\`,`lsk.cmd run "<文件名>.mp4"` | 能跑完;记下总用时、显卡型号、CPU 型号、内存;转写那行显示 `GPU: 开` 后有没有出现"改用 CPU(--no-gpu)重试"(出现说明 GPU 版没跑起来,把它上面的报错原文发我);任务管理器里"GPU"的 CUDA 占用有没有上去 |
| V8 | 如果你的用户名或文件夹路径里有中文:在那个路径下再跑一次 V5 | 照样跑完(whisper.cpp 读中文路径是已知风险点) |
| V9 | 在资源管理器里**双击** `install.cmd`(V2–V4 的一键版;已经装好的项会跳过) | 窗口跑完停住等你按键,不会一闪而过;最后列出 `...\.claude\skills\video-summary -> ...` 三行 |
| V10 | 关掉所有窗口,在**别的文件夹**(比如桌面)打开 Claude Code 或 Codex,说"总结 <示例视频完整路径>" | AI 认出技能并找到工具文件夹(技能是目录联接 junction,AI 需要顺着它找到 `lsk.cmd`) |

## 第三部分:让 AI 走完整流程

1. 用 AI 应用打开 `lecture-summary-toolkit` 文件夹,说:
   > 用中文总结这节课:<合成字幕的完整路径>,单元 DEMO1001,日期 2026-01-01
2. 观察并记录:
   - AI 有没有用 `lsk.cmd`(或 `python ...\lsk.py`)而不是 `bash lsk`?它有没有因为找不到 bash 卡住?
   - 总结是否存到了 `总结\DEMO1001\` 下;AI 有没有跑 `lsk finish`,检查结果是 ✅ 还是 ❌。
   - 用记事本打开总结:中文正常;"章节时间线"里如果有链接,链接里是 `/` 不是 `\`。
   - `总结\DEMO1001\` 下生成了 `考点库.md`。
3. 再用英文版测一次(`--lang en` 或者对 AI 说"Summarize in English"),看 `.en.md` 和 `Exam-Bank.en.md`。

## 第四部分:网页版

1. 打开 ChatGPT / Claude 网页版,新开对话,上传合成字幕。
2. 打开 `prompts\web-prompt.zh.md`(用记事本),全选复制,粘贴发送。
3. 记录:文件在记事本里是不是乱码;AI 有没有按固定结构输出。

## 怎么报问题

每个问题一条,写清楚:

```
第几步:
做了什么(命令原文):
看到了什么(截图或完整报错,别只写"报错了"):
电脑:Windows 10/11,系统语言,用 cmd 还是 PowerShell,AI 应用和版本
```

测完全部通过也告诉我一声,并附上第 1、4、V4、V5 步的截图,以及 V7 的用时。

## 规矩

- 只用合成字幕测试,不要把真实课程字幕、课件、总结发到群里或传到仓库。
- 不用改代码;发现问题记下来就行。

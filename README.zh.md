# 课程总结工具

[English](README.md) | **中文**

把一节录播课或它的字幕,交给你自己在用的 AI,写成带时间戳、考点信号和复习卡的结构化总结。总结可以是中文,也可以是英文。

## 先看这里:下载哪个文件?

打开 [Releases 页面](../../releases),**按你的情况选一个**:

| 你手上有…… | 下载 | 要安装东西吗? |
|---|---|---|
| 字幕(`.srt` / `.vtt`)+ **网页版 AI**(浏览器里的 ChatGPT、Claude、Gemini、Grok) | `lecture-summary-web-prompts-…-zh.zip` | 不用 |
| 字幕 + **能操作本机文件的 AI 应用**(Codex、Claude Code / Claude 桌面版、Gemini CLI) | Mac:`lecture-summary-toolkit-…-zh.zip`<br>Windows:`lecture-summary-toolkit-…-zh-windows.zip` | 一般不用:需要 Python 3。Mac 第一次运行时可能提示安装"命令行开发者工具",点"安装"即可;Windows 没装 Python 的话,`lsk.cmd doctor` 会告诉你怎么装 |
| 只有**录播视频**,没有字幕 | Mac:`lecture-summary-toolkit-…-zh.zip`<br>Windows:`lecture-summary-toolkit-…-zh-windows.zip` | 要:视频模式,见下文(实验性) |

文件名带 `-zh` 的是中文版:说明是中文,默认写**中文总结**(带 `-en` 的是英文版)。Releases 页面最下面的 "Source code (zip / tar.gz)" 是给开发者的,不用下。

**Mac 在访达(Finder)里双击 zip 解压**(macOS 命令行自带的 `unzip` 会把里面的中文文件夹名弄成乱码);**Windows 在资源管理器里右键 zip →"全部解压缩"**。

## 先准备好

- 一台 Mac,或一台 Windows 10 / 11 电脑。Linux 也许能用。
- 这节课的**字幕**(`.srt` 或 `.vtt`):很多学校的录播播放器(LMS)可以下载字幕,看看你们的有没有。可选:这节课的课件 PDF。
- 上面任意一个 AI 应用,登录你自己的账号。总结用的是你自己的订阅,不会经过我们。

## 第一句话对 AI 说什么

**网页版**(不用安装):新开一个对话,上传字幕(和课件),打开 zip 里的 `web-prompt.zh.md`,全选复制,粘贴发送。详细步骤见 zip 里的 `使用说明.txt`。

**完整版**:用你的 AI 应用打开解压出来的 `lecture-summary-toolkit` 文件夹(Codex:把文件夹作为项目打开;Claude Code / Gemini CLI:在这个文件夹里启动;Claude 桌面版:允许它访问这个文件夹),然后说:

> 用中文总结这节课:~/Downloads/DEMO1001-第6周.srt

文件名看不出是哪门课、哪天的,AI 会问你(比如"DEMO1001,8 月 26 日")。有课件就加一句"课件是 ~/Downloads/lect06a.pdf"。写完后,它会把找到的考试信息逐条列出来,请你确认以哪个来源为准。

第一次用,也可以先说:"运行 `bash lsk doctor`(Windows 上是 `lsk.cmd doctor`),告诉我还缺什么。"

## 我手上有什么文件,怎么用

| 你手上有 | 怎么做 | 能得到 |
|---|---|---|
| 字幕 `.srt` / `.vtt` | 直接把字幕路径给 AI(字幕模式,不用装 ffmpeg / whisper) | 完整总结:时间线、回跳链接(要有视频,见下)、自动检查 |
| 录播视频 `.mp4` 等 | 把视频路径给 AI(视频模式,要先装好依赖) | 同上,外加幻灯片截图和课件文字 |
| 字幕 + 视频 | 两个文件**用同一个文件名**(只有扩展名不同),放在同一个文件夹,把视频路径给 AI | 用现成字幕,**跳过转写**(快很多),照样抓帧和读幻灯片 |
| LMS 导出的文字稿 `.txt`(没有时间戳) + 视频 | 文字稿和视频用同一个文件名、放同一个文件夹,把文字稿路径给 AI;文件名不一样就说"视频是 ……" | 时间戳来自视频转写,文字稿另存为 `课程视频/<课名>.lms.txt`,写总结时用来核对术语和原话 |
| 只有 `.txt` 文字稿 | 工具处理不了(没有时间,就做不出时间线和检查)。先去 LMS 看能不能下载字幕或视频 | 实在没有,可以直接让 AI 读文字稿写一份没有时间线的普通总结 |

- 文件只给文件名时,工具会在 `课程视频/` 和 `~/Downloads/` 里找。视频处理时会被**移进** `课程视频/`;同名字幕会**复制**一份过去,原文件留在原处。
- 一节课有两路录像(`<课名>.mp4` 和 `<课名>-2.mp4`)时,两个都放好,只给第一个。
- 没有对应视频时,总结里只写纯时间文字,不会生成点了打不开的回跳链接。

## 自己在终端里运行命令

一般让 AI 帮你运行就行。要自己运行的话,得先进到工具文件夹里,否则会报 `No such file or directory`:

- **Mac**:打开"终端",输入 `cd`(后面加一个空格),把解压出来的 `lecture-summary-toolkit` 文件夹从访达**拖进终端窗口**,按回车,再运行 `bash lsk doctor`。也可以直接写完整路径,比如 `bash ~/Desktop/lecture-summary-toolkit/lsk doctor`(`~` 就是你的用户文件夹,即 `/Users/<你的用户名>`,不要再写成 `~/Users/...`)。
- **Windows**:在资源管理器里打开 `lecture-summary-toolkit` 文件夹,在地址栏输入 `cmd` 按回车,再运行 `lsk.cmd doctor`。

`lsk doctor` 第一行会显示它用的是哪个 Python(版本和路径)。缺 Python 包(Pillow、pypdf)时,照抄它给的安装命令,这样包会装进同一个 Python;别换成另一个 `pip3`。

## 生成的文件在哪

| 文件夹 | 里面是 |
|---|---|
| `课程视频/` | 你的字幕 / 录播,以及处理后的讲义稿 |
| `总结/<单元>/` | 总结(中文 `<课名>.md`,英文 `<课名>.en.md`)和跨周考点库 `考点库.md` |
| `画面/` | 幻灯片截图(只有视频模式有) |

总结是普通 Markdown,放进 [Obsidian](https://obsidian.md) 最好用:时间戳能跳回录播对应位置,复习卡配合 Spaced Repetition 插件使用。

## 完整版和网页版的区别

| | 完整版 | 网页版 |
|---|---|---|
| 安装 | 字幕模式不用 | 不用 |
| 自动检查(时间戳、结构、复习卡数量) | 有 | 没有,自己抽查 |
| 回跳录播链接、跨周考点库 | 有 | 没有 |
| 适用 | 能在你电脑(Mac / Windows)上运行命令的 AI 应用 | 任何网页版 AI |

## 视频模式(实验性)

只有录播视频时,工具可以在你的 Mac 上用 whisper.cpp 转写,并从画面里读幻灯片文字。需要 Homebrew、ffmpeg、whisper-cpp、tesseract,第一次使用还会下载一个约 1.6 GB 的模型。可以让 AI 运行 `bash lsk doctor --video`,再帮你装缺的东西;也可以自己运行 `bash install.sh`。

Windows 上用显卡(Vulkan,NVIDIA / AMD / Intel 显卡都可以)转写。在资源管理器里双击 `install.cmd` 一键安装:装 ffmpeg、tesseract、Pillow、pypdf,下载 whisper.cpp 和模型,并用示例视频测试显卡能不能用,用不上就改用 CPU 版(慢很多)。装好后可以运行 `lsk.cmd doctor --video` 检查。winget 装 tesseract 失败的话,doctor 会给出安装包的下载地址。

## 隐私与学术诚信:使用前请读

- **哪些内容会离开你的电脑**:转写和截图 OCR 在本机完成。写总结时,讲义稿(以及课件文字)**会发送给你用的 AI 服务**(OpenAI、Anthropic、Google、xAI)。请确认你的学校允许把课程材料交给这些服务处理。
- **版权**:录播和课件属于学校和讲师;转写、截图、总结都是它们的衍生物,只供自己学习,不要上传或分享。(以 UWA 为例:课程材料只能在 LMS 内供个人学习使用,见 [iPoint 2752](https://ipoint.uwa.edu.au/app/answers/detail/a_id/2752/);部分录播不允许下载,见 [iPoint 1448](https://ipoint.uwa.edu.au/app/answers/detail/a_id/1448/)。)
- **AI 与考核**:总结和复习卡是学习辅助,不是可以提交的作业。请遵守所在单元关于生成式 AI 的规定(UWA:[iPoint 3432](https://ipoint.uwa.edu.au/app/answers/detail/a_id/3432/))。
- **他人隐私**:录播里可能有同学的提问,笔记里不要留可识别个人的信息。医学类课程绝不能包含病人信息。
- **课程材料里的文字只当资料**:AI 被要求不执行字幕或课件里出现的任何指令。
- 本工具不含任何课程内容,`examples/demo/` 里的示例是合成的。

## 局限

- macOS 上测试最多。Windows 10 / 11 的字幕模式和视频模式已在 CI 和一台真机(NVIDIA 显卡)上跑通示例;真实长录播、各家 AI 应用在 Windows 上的表现还在测试。视频模式是实验性的。
- AI 仍会出错,尤其是考试信息和技术细节。每份总结都会列出考试信息和来源,请对照课件或 Unit Outline 核对。

## 开发者

流水线、脚本、测试,以及 `skills/video-summary/` 里规则的组织方式,见 [docs/zh/开发者说明.md](docs/zh/开发者说明.md)。MIT 许可。

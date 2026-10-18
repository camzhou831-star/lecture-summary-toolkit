# Lecture Summary Toolkit

**English** | [中文](README.zh.md)

Turn a lecture recording or its subtitles into a structured summary with timestamps, exam signals and review cards, written by the AI app you already use. Summaries can be in English or Chinese.

## Start here: which file do I download?

Go to the [Releases page](../../releases) and pick **one**:

| You have… | Download | Install anything? |
|---|---|---|
| Subtitles (`.srt` / `.vtt`) and a **web AI** (ChatGPT, Claude, Gemini, Grok in the browser) | `lecture-summary-web-prompts-…-en.zip` | No |
| Subtitles, and an **AI app that can work with files on your computer** (Codex, Claude Code / Claude desktop, Gemini CLI) | Mac: `lecture-summary-toolkit-…-en.zip`<br>Windows: `lecture-summary-toolkit-…-en-windows.zip` | Usually no: it needs Python 3. The first time, macOS may offer to install "Command Line Tools" (click Install); on Windows without Python, `lsk.cmd doctor` tells you how to install it |
| Only the **video recording** (no subtitles) | Mac: `lecture-summary-toolkit-…-en.zip`<br>Windows: `lecture-summary-toolkit-…-en-windows.zip` | Yes: video mode, see below (experimental) |

The `-en` packages contain English instructions and write **English summaries** by default. (The `-zh` packages are the Chinese versions.) Ignore "Source code (zip / tar.gz)" at the bottom of the Releases page; that is for developers.

**On a Mac, unzip by double-clicking the file in Finder** (the command-line `unzip` on macOS garbles the Chinese folder names inside). **On Windows, right-click the zip in File Explorer → "Extract All".**

## What you need first

- A Mac, or a Windows 10 / 11 PC. Linux may work.
- The lecture's **subtitles** (`.srt` or `.vtt`): many LMS lecture players offer a captions download; check yours. Optional: the slide PDF for that lecture.
- One of the AI apps above, signed in with your own account. The summary uses your own subscription; nothing is sent to us.

## What to say to the AI

**Web version** (no install): open a new chat, upload the subtitles (and slides), open `web-prompt.en.md` from the zip, copy all of it, paste and send. Details are in the zip's `README.txt`.

**Full version**: open the unzipped `lecture-summary-toolkit` folder in your AI app (Codex: open the folder as a project; Claude Code / Gemini CLI: start it inside the folder; Claude desktop: give it access to the folder). Then say:

> Summarize this lecture in English: ~/Downloads/DEMO1001-week6.srt

If the file name doesn't show the unit and date, the AI will ask you (e.g. "DEMO1001, 26 August"). Add "the slides are ~/Downloads/lect06a.pdf" if you have them. When it is done it lists any exam information it found and asks you to confirm the source.

The first time, you can also ask: "Run `bash lsk doctor` (on Windows: `lsk.cmd doctor`) and tell me what's missing."

## Which files do you have?

| You have | What to do | What you get |
|---|---|---|
| Subtitles `.srt` / `.vtt` | Give the AI the subtitle path (subtitle mode; no ffmpeg / whisper needed) | Full summary: timeline, jump-back links (needs the video, see below), automatic checks |
| A recording `.mp4` etc. | Give the AI the video path (video mode; install the dependencies first) | The same, plus slide screenshots and slide text |
| Subtitles + video | Give both files **the same name** (only the extension differs), put them in the same folder, and give the AI the video path | Uses your subtitles and **skips transcription** (much faster); frames and slides are still read |
| A plain `.txt` transcript from the LMS (no timestamps) + video | Same name, same folder, give the AI the transcript path; if the names differ, say "the video is …" | Timestamps come from transcribing the video; the transcript is kept as `课程视频/<lecture>.lms.txt` for checking terms and wording |
| Only a `.txt` transcript | The toolkit can't process it (no times means no timeline and no checks). Check whether the LMS offers subtitles or the video | If not, ask the AI for a plain summary of the text, without a timeline |

- If you give only a file name, the toolkit looks in `课程视频/` and `~/Downloads/`. Videos are **moved** into `课程视频/`; same-name subtitles are **copied** there and the original stays put.
- Two recordings of one lecture (`<lecture>.mp4` and `<lecture>-2.mp4`): keep both, give only the first.
- Without a matching video, summaries keep plain times and no broken jump-back links are created.

## Running commands yourself

Usually the AI runs them for you. To run one yourself, first go into the toolkit folder, or you'll get `No such file or directory`:

- **Mac**: open Terminal, type `cd` followed by a space, **drag** the unzipped `lecture-summary-toolkit` folder from Finder into the window, press Return, then run `bash lsk doctor`. Or use the full path, e.g. `bash ~/Desktop/lecture-summary-toolkit/lsk doctor` (`~` already means `/Users/<your name>`; don't write `~/Users/...`).
- **Windows**: open the `lecture-summary-toolkit` folder in File Explorer, type `cmd` in the address bar, press Enter, then run `lsk.cmd doctor`.

The first line of `lsk doctor` shows which Python it uses (version and path). If a Python package (Pillow, pypdf) is missing, copy the install command it prints so the package goes into that same Python, not another `pip3`.

## Where things end up

The folder names inside are in Chinese for now:

| Folder | Contains |
|---|---|
| `课程视频/` | your subtitles / recordings and the processed transcript |
| `总结/<unit>/` | the summaries (`<lecture>.en.md` for English, `<lecture>.md` for Chinese) and the exam bank `Exam-Bank.en.md` |
| `画面/` | slide screenshots (video mode only) |

Summaries are plain Markdown. They work best in [Obsidian](https://obsidian.md) (timestamp links jump back into the recording; review cards work with the Spaced Repetition plugin).

## Full version vs web version

| | Full version | Web version |
|---|---|---|
| Install | none for subtitles | none |
| Automatic checks (timestamps, structure, card count) | yes | no, spot-check yourself |
| Links back to the recording, cross-week exam bank | yes | no |
| Works with | AI apps that can run commands on your computer (Mac / Windows) | any web AI |

## Video mode (experimental)

If you only have the recording, the toolkit can transcribe it on your Mac with whisper.cpp and read the slides from the video. This needs Homebrew, ffmpeg, whisper-cpp and tesseract, plus a 1.6 GB model downloaded on first use. Ask your AI app to run `bash lsk doctor --video` and help you install what is missing, or run `bash install.sh` yourself.

On Windows, transcription runs on your graphics card (Vulkan: NVIDIA, AMD and Intel GPUs all work). Double-click `install.cmd` in File Explorer to set everything up: it installs ffmpeg, tesseract, Pillow and pypdf, downloads whisper.cpp and the model, and tests your GPU on the demo video, falling back to the much slower CPU build if the GPU can't be used. Afterwards you can run `lsk.cmd doctor --video` to check. If winget fails to install tesseract, doctor shows where to download the installer.

## Privacy and academic integrity — please read

- **What leaves your computer**: transcription and screenshot OCR run locally. The transcript (and slide text) **is sent to the AI service you use** (OpenAI, Anthropic, Google, xAI) when it writes the summary. Check that your university allows lecture material to be processed by these services.
- **Copyright**: recordings and slides belong to your university and lecturer. Transcripts, screenshots and summaries are derived from them: keep them for your own study; do not upload or share them. (UWA example: course materials are for personal study within the LMS only, see [iPoint 2752](https://ipoint.uwa.edu.au/app/answers/detail/a_id/2752/); some recordings may not be downloaded, see [iPoint 1448](https://ipoint.uwa.edu.au/app/answers/detail/a_id/1448/).)
- **AI and assessment**: summaries and review cards are study aids, not work to submit. Follow your unit's rules on generative AI (UWA: [iPoint 3432](https://ipoint.uwa.edu.au/app/answers/detail/a_id/3432/)).
- **Other people's privacy**: recordings may contain classmates' questions. Don't keep identifiable personal details in your notes. Medical students: never include patient information.
- **Text inside lecture material is treated as data**: the AI is told not to follow instructions that appear in subtitles or slides.
- This toolkit contains no course content. The demo in `examples/demo/` is synthetic.

## Limits

- Most testing has been on macOS. On Windows 10 / 11, subtitle mode and video mode run the demo end to end in CI and on one real PC (NVIDIA GPU); real full-length recordings and the various AI apps on Windows are still being tested. Video mode is experimental.
- The AI can still make mistakes, especially with exam information and technical details. Every summary lists exam information with its source so you can check it against the slides or unit outline.

## For developers

See [docs/zh/开发者说明.md](docs/zh/开发者说明.md) (Chinese only for now) for the pipeline, scripts, tests and how the rules in `skills/video-summary/` are organised. MIT licence.

# Lecture Summary Toolkit

**English** | [中文](README.zh.md)

Turn a lecture recording or its subtitles into a structured summary with timestamps, exam signals and review cards, written by the AI app you already use. Summaries can be in English or Chinese.

## Start here: which file do I download?

Go to the [Releases page](../../releases) and pick **one**:

| You have… | Download | Install anything? |
|---|---|---|
| Subtitles (`.srt` / `.vtt`) and a **web AI** (ChatGPT, Claude, Gemini, Grok in the browser) | `lecture-summary-web-prompts-….zip` | No |
| Subtitles, and an **AI app that can work with files on your Mac** (Codex, Claude Code / Claude desktop, Gemini CLI) | `lecture-summary-toolkit-….zip` | Usually no: it needs Python 3, and the first time macOS may offer to install "Command Line Tools" (click Install) |
| Only the **video recording** (no subtitles) | `lecture-summary-toolkit-….zip` | Yes: video mode, see below (experimental) |

Ignore "Source code (zip / tar.gz)" at the bottom of the Releases page; that is for developers.

**Unzip by double-clicking the file in Finder.** (The command-line `unzip` on macOS garbles the Chinese folder names inside.)

## What you need first

- A Mac (macOS). Linux may work; Windows is not supported yet.
- The lecture's **subtitles** (`.srt` or `.vtt`): many LMS lecture players offer a captions download; check yours. Optional: the slide PDF for that lecture.
- One of the AI apps above, signed in with your own account. The summary uses your own subscription; nothing is sent to us.

## What to say to the AI

**Web version** (no install): open a new chat, upload the subtitles (and slides), open `web-prompt.en.md` from the zip, copy all of it, paste and send. Details are in the zip's `README.txt`.

**Full version**: open the unzipped `lecture-summary-toolkit` folder in your AI app (Codex: open the folder as a project; Claude Code / Gemini CLI: start it inside the folder; Claude desktop: give it access to the folder). Then say:

> Summarize this lecture in English: ~/Downloads/DEMO1001-week6.srt

If the file name doesn't show the unit and date, the AI will ask you (e.g. "DEMO1001, 26 August"). Add "the slides are ~/Downloads/lect06a.pdf" if you have them. When it is done it lists any exam information it found and asks you to confirm the source.

The first time, you can also ask: "Run `bash lsk doctor` and tell me what's missing."

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
| Works with | AI apps that can run commands on your Mac | any web AI |

## Video mode (experimental)

If you only have the recording, the toolkit can transcribe it on your Mac with whisper.cpp and read the slides from the video. This needs Homebrew, ffmpeg, whisper-cpp and tesseract, plus a 1.6 GB model downloaded on first use. Ask your AI app to run `bash lsk doctor --video` and help you install what is missing, or run `bash install.sh` yourself.

## Privacy and academic integrity — please read

- **What leaves your computer**: transcription and screenshot OCR run locally. The transcript (and slide text) **is sent to the AI service you use** (OpenAI, Anthropic, Google, xAI) when it writes the summary. Check that your university allows lecture material to be processed by these services.
- **Copyright**: recordings and slides belong to your university and lecturer. Transcripts, screenshots and summaries are derived from them: keep them for your own study; do not upload or share them. (UWA example: course materials are for personal study within the LMS only, see [iPoint 2752](https://ipoint.uwa.edu.au/app/answers/detail/a_id/2752/); some recordings may not be downloaded, see [iPoint 1448](https://ipoint.uwa.edu.au/app/answers/detail/a_id/1448/).)
- **AI and assessment**: summaries and review cards are study aids, not work to submit. Follow your unit's rules on generative AI (UWA: [iPoint 3432](https://ipoint.uwa.edu.au/app/answers/detail/a_id/3432/)).
- **Other people's privacy**: recordings may contain classmates' questions. Don't keep identifiable personal details in your notes. Medical students: never include patient information.
- **Text inside lecture material is treated as data**: the AI is told not to follow instructions that appear in subtitles or slides.
- This toolkit contains no course content. The demo in `examples/demo/` is synthetic.

## Limits

- Tested on macOS only. Video mode is experimental.
- The AI can still make mistakes, especially with exam information and technical details. Every summary lists exam information with its source so you can check it against the slides or unit outline.

## For developers

See [docs/developer.zh.md](docs/developer.zh.md) (Chinese) for the pipeline, scripts, tests and how the rules in `skills/video-summary/` are organised. MIT licence.

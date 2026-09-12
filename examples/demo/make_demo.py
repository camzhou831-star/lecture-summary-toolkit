#!/usr/bin/env python3
"""重新生成示例讲座(全部原创内容):幻灯片 PNG + 带文字层的 PDF + macOS `say` 合成旁白 + 拼成 mp4。
用法: python3 examples/demo/make_demo.py [输出目录,默认 examples/demo]
依赖: Pillow、ffmpeg、macOS 的 say(其它系统可换成任意 TTS,把 6 段旁白各存成 audio/aNN.aiff 后从第 3 步继续)
"""
import json, os, subprocess, sys, textwrap
from PIL import Image, ImageDraw, ImageFont
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
UNIT, NAME = "DEMO1001", "DEMO1001 - 01 Jan 26-s1-demo"
SLIDES = [
 ("Testing Loops: A Tiny Lecture", ["Demo unit DEMO1001", "A two-minute synthetic lecture", "All content in this video is original and free to reuse"]),
 ("Why loops are hard to test", ["A loop body can run zero, one, or many times", "Each count can hide a different fault", "Line coverage says nothing about how many times"]),
 ("Loop coverage heuristic", ["Write one test where the body runs 0 times", "One where it runs exactly once", "One where it runs more than once", "This is informal but catches off-by-one errors"]),
 ("Prime paths, informally", ["A simple path visits no node twice", "A prime path is a simple path that cannot be extended", "Prime path coverage subsumes node and edge coverage"]),
 ("Worked example", ["while i < n: total += a[i]; i += 1", "n = 0  -> body never runs", "n = 1  -> body runs once", "n = 3  -> body runs three times"]),
 ("Summary", ["Test loop counts: 0, 1, many", "Prime paths formalise the idea", "Quiz next week covers this slide deck"]),
]
NARRATION = [
 "Welcome to this short demo lecture. Everything you hear and see here was generated for testing the summary toolkit, so there is no copyright problem in sharing it. Today's topic is testing loops.",
 "Loops are surprisingly hard to test. The body of a loop can run zero times, exactly once, or many times, and each of those counts can hide a different fault. Line coverage tells you the line ran, but not how many times.",
 "So here is the informal heuristic that most teams use. Write one test where the loop body never runs, one where it runs exactly once, and one where it runs more than once. This is informal, but it catches a lot of off by one errors.",
 "The textbook formalises this with prime paths. A simple path visits no node twice. A prime path is a simple path that cannot be extended without repeating a node. Prime path coverage subsumes node coverage and edge coverage.",
 "Let us look at a tiny example. While i is less than n, add a of i to the total and increment i. With n equal to zero the body never runs. With n equal to one it runs once. With n equal to three it runs three times. Those three tests give you loop coverage.",
 "To summarise: test loop counts of zero, one and many, and use prime paths when you need something rigorous. The quiz next week will cover this slide deck, so make sure you can state the definition of a prime path. Thanks, see you next time.",
]
def sh(*cmd): subprocess.run(cmd, check=True)
def main():
    work = os.path.join(OUT, ".build"); os.makedirs(os.path.join(work, "slides"), exist_ok=True); os.makedirs(os.path.join(work, "audio"), exist_ok=True)
    try: ft, fb, fs = [ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", n) for n in (54, 34, 22)]
    except Exception: ft = fb = fs = ImageFont.load_default()
    # 1. 幻灯片 PNG(右下角 "N of M" 模拟放映软件页码)
    for i, (title, bullets) in enumerate(SLIDES, 1):
        im = Image.new("RGB", (1280, 720), "white"); d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 1280, 90], fill=(30, 60, 120)); d.text((40, 18), title, fill="white", font=ft); y = 140
        for b in bullets:
            for j, line in enumerate(textwrap.wrap(b, 60)): d.text((70, y), ("• " if j == 0 else "  ") + line, fill=(20, 20, 20), font=fb); y += 52
            y += 14
        d.text((1100, 680), f"{i} of {len(SLIDES)}", fill=(90, 90, 90), font=fs); im.save(os.path.join(work, "slides", f"s{i:02d}.png"))
    # 2. 带文字层的 PDF(手写 PDF 语法,不依赖 reportlab)
    esc = lambda t: t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objs = []; add = lambda o: (objs.append(o), len(objs))[1]
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"); pages_idx = add(b"PLACEHOLDER"); ids = []
    for i, (title, bullets) in enumerate(SLIDES, 1):
        lines = [f"BT /F1 28 Tf 50 660 Td ({esc(title)}) Tj ET"]; y = 600
        for b in bullets:
            for l in textwrap.wrap(b, 70): lines.append(f"BT /F1 16 Tf 60 {y} Td ({esc('- ' + l)}) Tj ET"); y -= 26
            y -= 8
        lines.append(f"BT /F1 10 Tf 880 30 Td ({i} of {len(SLIDES)}) Tj ET"); content = "\n".join(lines).encode()
        c = add(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        ids.append(add(("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 960 720] /Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>" % (pages_idx, c, font)).encode()))
    objs[pages_idx - 1] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % p for p in ids), len(ids))).encode()
    cat = add(("<< /Type /Catalog /Pages %d 0 R >>" % pages_idx).encode()); out = b"%PDF-1.4\n"; offs = []
    for n, o in enumerate(objs, 1): offs.append(len(out)); out += b"%d 0 obj\n" % n + o + b"\nendobj\n"
    xref = len(out); out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, xref)
    os.makedirs(os.path.join(OUT, "课件", UNIT), exist_ok=True); open(os.path.join(OUT, "课件", UNIT, f"{UNIT}-testing-loops.pdf"), "wb").write(out)
    # 3. 旁白(macOS say),每段前后 1.5 s 静音;片头 8 s 黑屏静音模拟录播开头
    for i, t in enumerate(NARRATION, 1):
        a = os.path.join(work, "audio", f"a{i:02d}.aiff")
        if not os.path.exists(a): sh("say", "-v", "Samantha", "-r", "175", "-o", a, t)
        sh("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", a, "-af", "adelay=1500|1500,apad=pad_dur=1.5", "-ar", "16000", "-ac", "1", os.path.join(work, "audio", f"p{i:02d}.wav"))
    # 4. 逐页拼视频
    lst = os.path.join(work, "all.txt"); parts = []
    sh("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=10", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "8", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", os.path.join(work, "lead.mp4")); parts.append("lead.mp4")
    for i in range(1, len(SLIDES) + 1):
        wav = os.path.join(work, "audio", f"p{i:02d}.wav")
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav], capture_output=True, text=True).stdout.strip()
        sh("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "10", "-i", os.path.join(work, "slides", f"s{i:02d}.png"), "-i", wav, "-t", dur, "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-shortest", os.path.join(work, f"seg{i:02d}.mp4")); parts.append(f"seg{i:02d}.mp4")
    sh("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "10", "-i", os.path.join(work, "slides", f"s{len(SLIDES):02d}.png"), "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "5", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", os.path.join(work, "tail.mp4")); parts.append("tail.mp4")
    open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
    os.makedirs(os.path.join(OUT, "课程视频"), exist_ok=True)
    sh("ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", os.path.join(OUT, "课程视频", NAME + ".mp4"))
    json.dump({"slides": SLIDES, "narration": NARRATION}, open(os.path.join(OUT, "demo_script.json"), "w"), ensure_ascii=False, indent=1)
    print("== 生成完成:", os.path.join(OUT, "课程视频", NAME + ".mp4"))
if __name__ == "__main__":
    main()

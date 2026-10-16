#!/usr/bin/env python3
"""把转写(srt/compact)与幻灯片 OCR(ocr.json)按时间对齐,生成两份文件:
  课程视频/<视频名>.bundle.json  —— 机器可读:{video, duration, segments[], frames[]}
  课程视频/<视频名>.grounded.md  —— 给 Claude 读的"讲义稿":逐分钟转写,中间插入该分钟出现的幻灯片 OCR 文本
用法: build_bundle.py <视频路径或 课程视频/<视频名>.srt> [--frames-dir <画面目录>] [--duration 秒] [--video <视频路径>]
  --duration / --video: 视频不和 srt 放在一起时(网页工作台)用来确定时长;都不给时在 srt 同目录找同名视频,再不行用最后一段转写的结束时间
"""
import argparse, json, os, re, subprocess, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deps
ROOT = os.environ.get("COURSE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 默认为 工具/ 的上级目录
TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")

def hms(sec):
    sec = int(sec); return f"{sec//3600}:{sec%3600//60:02d}:{sec%60:02d}"

def parse_srt(path):
    segs = []
    for b in re.split(r"\n\s*\n", open(path, encoding="utf-8", errors="ignore").read().replace("\r\n", "\n").strip()):
        lines = [l.strip() for l in b.splitlines()]
        ti = next((i for i, l in enumerate(lines) if TIME_RE.search(l)), None)
        if ti is None: continue
        m = TIME_RE.search(lines[ti])
        s = int(m[1])*3600 + int(m[2])*60 + int(m[3]) + int(m[4])/1000
        e = int(m[5])*3600 + int(m[6])*60 + int(m[7]) + int(m[8])/1000
        text = re.sub(r"<[^>]+>", "", " ".join(lines[ti+1:])).strip()
        if text: segs.append({"start": round(s, 2), "end": round(e, 2), "text": text})
    segs.sort(key=lambda x: x["start"])
    for i, sg in enumerate(segs): sg["i"] = i
    return segs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input"); ap.add_argument("--frames-dir"); ap.add_argument("--duration", type=float); ap.add_argument("--video")
    a = ap.parse_args()
    base = os.path.splitext(a.input)[0]
    name = os.path.basename(base)
    srt = base + ".srt"; compact = base + ".compact.txt"
    if not os.path.exists(srt): sys.exit(f"错误: 找不到 {srt}")
    frames_dir = a.frames_dir or os.path.join(ROOT, "画面", name)
    ocr_path = os.path.join(frames_dir, "ocr.json")
    frames = []
    cam_path = os.path.join(frames_dir, "cam", "cam.json")   # 双路录像时实物投影(手写)帧,由 cam_frames.py 产出
    cam = []
    if os.path.exists(cam_path):
        try: cam = json.load(open(cam_path, encoding="utf-8"))
        except (json.JSONDecodeError, TypeError): print(f"⚠️ {cam_path} 损坏,本次不含手写帧;请重跑 cam_frames.py", file=sys.stderr)
    if os.path.exists(ocr_path):
        try: frames = [f for f in json.load(open(ocr_path, encoding="utf-8")) if not f.get("error")]
        except (json.JSONDecodeError, TypeError): print(f"⚠️ {ocr_path} 损坏,本次不含幻灯片;请重跑 ocr_frames.py --force", file=sys.stderr)
    segs = parse_srt(srt)
    if not segs: sys.exit(f"错误: {srt} 里没有任何带时间的转写段")
    duration = a.duration
    cands = [a.video] if a.video else [base + ext for ext in (".mp4", ".mkv", ".m4a", ".mp3", ".webm", ".mov")]
    for v in cands:
        if duration is not None: break
        if v and os.path.exists(v):
            try: r = subprocess.run([deps.exe("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", v], capture_output=True, text=True)
            except FileNotFoundError: break          # 没装 ffprobe(如 Windows 字幕模式):退回用转写结束时间
            try: duration = float(r.stdout.strip()); break
            except ValueError: pass
    if duration is None: duration = max(s["end"] for s in segs)
    rel_frames = os.path.relpath(frames_dir, ROOT).replace(os.sep, "/")   # 写进 json / 讲义稿的路径统一用正斜杠(Windows 也一样)
    bundle = {"video": name, "duration": duration, "generated": datetime.date.today().isoformat(),
              "srt": os.path.relpath(srt, ROOT).replace(os.sep, "/"), "frames_dir": rel_frames,
              "segments": segs,
              "cam_frames": [{"file": "cam/" + c["file"], "t": c["t"], "kind": c["kind"]} for c in cam],
              "frames": [{"file": f["file"], "t": f["t"], "page": f.get("page"), "pages": f.get("pages"), "deck": f.get("deck"), "also_at": f.get("also_at", []), "chars": f.get("chars", 0), "text": f.get("text", "")} for f in frames]}
    with open(base + ".bundle.json.tmp", "w", encoding="utf-8") as fh: json.dump(bundle, fh, ensure_ascii=False, indent=0)
    os.replace(base + ".bundle.json.tmp", base + ".bundle.json")

    # grounded.md
    minutes = {}
    if os.path.exists(compact):
        for l in open(compact, encoding="utf-8"):
            m = re.match(r"\[(\d+):(\d+)\] (.*)", l.rstrip("\n"))
            if m: minutes[int(m[1])*60 + int(m[2])] = m[3]
    else:
        for s in segs: minutes.setdefault(int(s["start"]) // 60, []); minutes[int(s["start"]) // 60] = (minutes[int(s["start"]) // 60] or "") + " " + s["text"]
    by_min = {}
    for f in frames: by_min.setdefault(f["t"] // 60, []).append(f)
    cam_by_min = {}
    for c in cam: cam_by_min.setdefault(c["t"] // 60, []).append(c)
    # 无语音的空档(>= 180 秒)也要标出来,提示可能是课间/忘开麦;标在空档开始的那一分钟
    # 注意 whisper 开 VAD 后会把静音前最后一段的结束时间拉到下一段开头(如 2 个词的段长 249 秒),
    # 所以"时长 >= 60 秒且每秒不到 0.5 个词"的段按 start + 3 秒 作为真实结束时间
    def eff_end(sg):
        dur = sg["end"] - sg["start"]
        return sg["start"] + 3 if dur >= 60 and len(sg["text"].split()) / dur < 0.5 else sg["end"]
    gaps = {}
    for s1, s2 in zip(segs, segs[1:]):
        e1 = eff_end(s1)
        if s2["start"] - e1 >= 180: gaps[int(e1) // 60] = (e1, s2["start"])
    # 另一种情况:srt 里有段落但全被 compact 当幻觉滤掉(课间闲聊噪声)——连续 >= 3 个分钟没有有效转写也标出来
    mk = sorted(minutes)
    for m1, m2 in zip(mk, mk[1:]):
        if m2 - m1 - 1 >= 3 and not any(m1 <= g < m2 for g in gaps):
            gaps[m1] = ((m1 + 1) * 60, m2 * 60)
    all_min = sorted(set(minutes) | set(by_min) | set(gaps) | set(cam_by_min))
    out = [f"# {name} · 讲义稿(转写 + 幻灯片 OCR 对齐)", "",
           f"> 时长 {hms(duration or 0)} · 转写段 {len(segs)} · 幻灯片帧 {len(frames)}" + (f" · 手写帧 {len(cam)}" if cam else "") + f" · 生成于 {bundle['generated']}",
           f"> 每行 `[HH:MM]` 是该分钟的转写(时:分)。`📄 t=秒 · p页/总页 · 文件名` 是该分钟出现的幻灯片及其 OCR 文本,图片在 `{rel_frames}/`。",
           "> OCR 文本很短(<60 字符)或看起来是代码/图表/终端的帧,建议直接打开图片看。课件页码来自 Okular 工具栏的 \"N of M\",没有的帧是终端/浏览器/桌面等非课件画面。"]
    if cam: out.append(f"> `✍️ t=秒 · 手写` 是实物投影仪拍到的老师手写页(图片在 `{rel_frames}/cam/`),没有 OCR,**必须打开图片看**:`整页` 是该页写完时的画面(内容最全),`书写中` 是每 3 分钟一张的进度帧(用来对上讲到纸上哪一处)。")
    out.append("")
    for mi in all_min:
        if mi in minutes: out.append(f"[{mi//60:02d}:{mi%60:02d}] {minutes[mi]}")
        if mi in gaps:
            g0, g1 = gaps[mi]
            out.append(f"⏸ {hms(g0)}–{hms(g1)} 无语音({int(g1-g0)//60} 分 {int(g1-g0)%60} 秒,可能是课间/静音/忘开麦)")
        for c in cam_by_min.get(mi, []):
            out.append(f"✍️ t={c['t']}s · 手写{'整页' if c['kind'] == 'page_end' else '·书写中'} · cam/{c['file']} ⚠️必须看图")
        for f in by_min.get(mi, []):
            deck = (f.get("match") or {}).get("deck") or f.get("deck")
            page = (f"p{f['page']}/{f['pages']}" + (f" {os.path.splitext(deck)[0]}" if deck else "")) if f.get("page") else "非课件画面"
            hint = " ⚠️文字少,建议看图" if f.get("chars", 0) < 60 else ""
            also = f" · 之后又回到此页: {', '.join(str(t)+'s' for t in f['also_at'])}" if f.get("also_at") else ""
            out.append(f"📄 t={f['t']}s · {page} · {f['file']}{hint}{also}")
            lines = (f.get("text") or "").splitlines()
            cap = 14 if f.get("page") else 6          # 课件页最多 14 行,终端/浏览器等最多 6 行,够认出内容即可
            for line in lines[:cap]:
                out.append(f"    {line}")
            if len(lines) > cap: out.append(f"    …(还有 {len(lines) - cap} 行,见 bundle.json 或图片)")
        out.append("")
    with open(base + ".grounded.md.tmp", "w", encoding="utf-8") as fh: fh.write("\n".join(out))
    os.replace(base + ".grounded.md.tmp", base + ".grounded.md")
    print(f"== bundle: {len(segs)} 段转写, {len(frames)} 帧" + (f", {len(cam)} 手写帧" if cam else "") + f", 时长 {hms(duration or 0)}")
    print(f"   {base}.bundle.json\n   {base}.grounded.md")

if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr): s.reconfigure(encoding="utf-8", errors="replace")   # Windows 终端/管道默认 GBK 或 cp1252,打印中文和 ✅⚠️🎯 会报 UnicodeEncodeError
    main()

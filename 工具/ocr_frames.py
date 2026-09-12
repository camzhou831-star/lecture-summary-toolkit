#!/usr/bin/env python3
"""对画面文件夹里的每一帧做 OCR(tesseract),写入 <目录>/ocr.json,并按文字内容再合并一次相邻的重复页。
用法: ocr_frames.py <画面目录> [--jobs 4] [--no-merge] [--force]
输出 ocr.json: [{"file","t","page","pages","text","chars"}, ...] 按时间排序
- page/pages 来自 Okular 工具栏的 "12 of 20"(没有则为 null)
- text 已去掉桌面/菜单栏噪声行
- 合并规则: A 相邻同页码只留文字最多的一帧;B 前一帧 90% 以上的词都在后一帧里 -> 前一帧是"未放完的动画/同一页",删掉;
  C 全局:同一页后面再出现且内容不更多 -> 删,非课件画面(终端/浏览器)与已保留的高度相似(Jaccard>=0.7) -> 删
"""
import argparse, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

NOISE = re.compile(r"(Applications|File View Edit|Show Sidebar|Zoom Out|Zoom In|Bookmarks Tools|Terminal Tabs Help|unpriv|^\W{0,3}$|Okular|Welcome - C|"
                   r"Mozilla Firefox|Google Search|@New|Gtimet|githu|xkcd|Browse Text Selection|Yellow Highlighter|Fit Width|Fit Page|Ctri\+|Ctrl\+|"
                   r"Search with Google|Show more|Sign ?in|Sponsor|Notifications|Pull ?requests|DEMO1002 Soft|demo1002 - Thu|Thunar|Places|Rubbish|File System|Encrypted|"
                   r"Copyright Act|UNIVERSITY OF|WESTERN|AUSTRALIA|COPYRIGHT NOTICE|copyright owner|personal use only|external websites|\d+ of \d+)")
def noisy_line(l):
    if NOISE.search(l): return True
    alpha = sum(ch.isalpha() or ch.isspace() for ch in l)
    return alpha / max(1, len(l)) < 0.6          # 一半以上是符号/数字的行,多为界面碎片
PAGE = re.compile(r"\b(\d{1,3}) of (\d{1,3})\b")

def frame_key(name):
    m = re.match(r"t(\d+)s(?:-(\d+))?\.jpg$", name)
    return (int(m.group(1)), int(m.group(2) or 1)) if m else None

def ocr(path):
    with open(path, "rb") as fh:   # 经 stdin 喂图,避免 leptonica 在某些路径下打不开文件
        r = subprocess.run(["tesseract", "stdin", "-", "-l", "eng", "--psm", "3"], stdin=fh, capture_output=True)
    if r.returncode != 0:
        print(f"   ⚠️ tesseract 失败: {os.path.basename(path)}: {r.stderr.decode('utf-8', 'replace').strip().splitlines()[-1] if r.stderr else ''}", file=sys.stderr)
        return {"page": None, "pages": None, "text": "", "chars": 0, "error": True}
    raw = r.stdout.decode("utf-8", errors="replace")
    page = PAGE.search(raw)
    lines = []
    for l in raw.splitlines():
        l = re.sub(r"\s+", " ", l).strip()
        if not l or noisy_line(l): continue
        if len(re.findall(r"[A-Za-z]{3,}", l)) < 2: continue      # 少于两个真单词的行
        lines.append(l)
    return {"page": int(page.group(1)) if page else None, "pages": int(page.group(2)) if page else None,
            "text": "\n".join(lines), "chars": sum(len(l) for l in lines)}

def words(t): return set(w for w in re.findall(r"[a-z]{3,}", t.lower()))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--no-merge", action="store_true"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    out = os.path.join(a.dir, "ocr.json")
    old = {}
    if os.path.exists(out) and not a.force:
        try:
            old = {e["file"]: e for e in json.load(open(out)) if not e.get("error")}
        except (json.JSONDecodeError, TypeError, KeyError):
            print(f"   ⚠️ {out} 损坏,忽略并全部重新识别", file=sys.stderr); old = {}
    files = sorted((f for f in os.listdir(a.dir) if frame_key(f)), key=frame_key)
    todo = [f for f in files if f not in old]
    with ThreadPoolExecutor(a.jobs) as ex:
        results = dict(zip(todo, ex.map(lambda f: ocr(os.path.join(a.dir, f)), todo)))
    entries = []
    for f in files:
        e = old.get(f) or {"file": f, "t": frame_key(f)[0], **results[f]}
        entries.append(e)
    # 按文字合并相邻重复页:
    #  规则 A: 连续几帧课件页码相同(同一套课件、同一页) -> 只保留文字最多的一帧
    #  规则 B: 前一帧 90% 以上的词都出现在后一帧 -> 前一帧是未放完的动画/被遮挡版本,删掉
    removed = []
    if not a.no_merge:
        i = 0
        while i < len(entries) - 1:
            e1, e2 = entries[i], entries[i + 1]
            same_page = e1["page"] is not None and e1["pages"] == e2["pages"] and e1["page"] == e2["page"]
            if same_page:
                drop = i if e1["chars"] <= e2["chars"] else i + 1
                removed.append(entries[drop]["file"]); del entries[drop]; continue
            wa, wb = words(e1["text"]), words(e2["text"])
            if len(wa) >= 5 and len(wa & wb) / len(wa) >= 0.9:
                removed.append(e1["file"]); del entries[i]; continue
            i += 1
        #  规则 C(全局):同一课件页在整节课里再次出现且内容不比已保留的多 -> 删;非课件画面(终端/浏览器)与已保留的词集合 Jaccard >= 0.7 -> 删
        kept = []
        for e in entries:
            w = words(e["text"]); drop = False
            for k in kept:
                kw = words(k["text"])
                if e["page"] and k["page"] == e["page"] and k["pages"] == e["pages"]:
                    if w and len(w & kw) / len(w) >= 0.9: drop = True; break
                    if kw and len(w & kw) / len(kw) >= 0.9 and k["chars"] < e["chars"]:
                        removed.append(k["file"]); kept.remove(k); break
                elif not e["page"] and not k["page"] and len(w) >= 8 and len(w & kw) / len(w | kw) >= 0.7:
                    drop = True; break
            if drop: removed.append(e["file"])
            else: kept.append(e)
        entries = kept
        for f in removed:
            p = os.path.join(a.dir, f)
            if os.path.exists(p): os.remove(p)
    json.dump(entries, open(out, "w"), ensure_ascii=False, indent=1)
    errs = sum(1 for e in entries if e.get("error"))
    print(f"== OCR: 新识别 {len(todo)} 帧,合并删除 {len(removed)} 帧,剩余 {len(entries)} 帧" + (f",{errs} 帧识别失败" if errs else "") + f" -> {out}")

if __name__ == "__main__":
    main()

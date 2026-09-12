#!/usr/bin/env python3
"""用课件 PDF 的文字给每一帧定页码(比 OCR 读工具栏 "N of M" 稳),写回 ocr.json 的 page/pages/deck/match 字段。
用法: match_slides.py <画面目录> <课件.pdf 或目录> [更多 pdf/目录...] [--min-score 0.35] [--dry-run]
原理: pdftotext 逐页抽字 → 每帧 OCR 词集合与每页词集合算 相似度 = |A∩B| / |A|(A 为帧的词,偏向"帧上的字都能在这页找到")
      得分最高且 >= min-score 的页作为匹配;同分时优先与上一帧同一套课件、页码相近的。
      已有工具栏页码的帧,若与匹配结果冲突,以 PDF 匹配为准并记录 match.toolbar 备查。
依赖: poppler 的 pdftotext(brew install poppler)
"""
import argparse, json, os, re, subprocess, sys
STOP = set("the and for that this with are was were from into your you our can will not but have has had they them their which what when where how why also than then there here these those such very just more most some any each other one two three four five six".split())

def words(t):
    return set(w for w in re.findall(r"[a-z][a-z0-9'+-]{2,}", t.lower())) - STOP

def pdf_pages(path):
    r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True)
    if r.returncode != 0: sys.exit(f"错误: pdftotext 失败: {path}: {r.stderr.decode('utf-8','replace')[-200:]}")
    pages = r.stdout.decode("utf-8", "replace").split("\f")
    if pages and not pages[-1].strip(): pages = pages[:-1]
    return [words(p) for p in pages]

def collect_pdfs(args):
    out = []
    for a in args:
        if os.path.isdir(a):
            out += sorted(os.path.join(a, f) for f in os.listdir(a) if f.lower().endswith(".pdf"))
        elif a.lower().endswith(".pdf"): out.append(a)
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("dir"); ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--min-score", type=float, default=0.35); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    pdfs = collect_pdfs(a.pdfs)
    if not pdfs: sys.exit("错误: 没有找到 PDF")
    decks = {os.path.basename(p): pdf_pages(p) for p in pdfs}
    ocr_path = os.path.join(a.dir, "ocr.json")
    entries = json.load(open(ocr_path))
    prev = None; matched = 0; conflicts = 0
    for e in entries:
        fw = words(e.get("text", ""))
        if len(fw) < 6: e["match"] = None; continue
        best = None
        for deck, pages in decks.items():
            for i, pw in enumerate(pages, 1):
                if not pw: continue
                score = len(fw & pw) / len(fw)
                bonus = 0.02 if prev and prev[0] == deck and abs(prev[1] - i) <= 2 else 0   # 连续性:同一套、相邻页优先
                if best is None or score + bonus > best[2]: best = (deck, i, score + bonus, score)
        if best and best[3] >= a.min_score:
            deck, page, _, score = best
            toolbar = e.get("page")
            if toolbar and toolbar != page: conflicts += 1
            e["match"] = {"deck": deck, "page": page, "pages": len(decks[deck]), "score": round(score, 2), "toolbar": toolbar}
            e["deck"] = deck; e["page"] = page; e["pages"] = len(decks[deck]); matched += 1; prev = (deck, page)
        else:
            e["match"] = {"deck": None, "page": None, "score": round(best[3], 2) if best else 0, "toolbar": e.get("page")}
    if not a.dry_run: json.dump(entries, open(ocr_path, "w"), ensure_ascii=False, indent=1)
    print(f"== 课件匹配: {matched}/{len(entries)} 帧定到页码({len(decks)} 套课件),{conflicts} 帧与工具栏页码不一致(以 PDF 为准)" + (" (dry-run)" if a.dry_run else ""))

if __name__ == "__main__":
    main()

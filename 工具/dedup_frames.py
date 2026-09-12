#!/usr/bin/env python3
"""去掉画面文件夹里几乎完全相同的帧(16x16 dHash,256 位 + 滑动窗口)。
用法: dedup_frames.py <画面目录> [--threshold 2] [--window 5] [--dry-run]
策略: 新帧与最近 window 张已保留帧比较,汉明距离 <= threshold 视为同一画面,只保留"最后一张"。
注意: 阈值必须很严——同一套课件的不同页在低精度哈希下非常像,同页/同内容的合并交给 ocr_frames.py 按文字判断。
"""
import argparse, os, re, sys
from PIL import Image

def dhash(path, size=16):
    img = Image.open(path).convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(img.getdata())
    bits = 0
    for r in range(size):
        for c in range(size):
            bits = (bits << 1) | (1 if px[r * (size + 1) + c] > px[r * (size + 1) + c + 1] else 0)
    return bits

def hamming(a, b):
    return bin(a ^ b).count("1")

def frame_key(name):
    m = re.match(r"t(\d+)s(?:-(\d+))?\.jpg$", name)
    return (int(m.group(1)), int(m.group(2) or 1)) if m else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("--threshold", type=int, default=2)
    ap.add_argument("--window", type=int, default=5); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    files = sorted((f for f in os.listdir(a.dir) if frame_key(f)), key=frame_key)
    kept = []   # [(name, hash)]
    removed = []
    for f in files:
        h = dhash(os.path.join(a.dir, f))
        dup_idx = None
        for i in range(len(kept) - 1, max(-1, len(kept) - 1 - a.window), -1):
            if hamming(kept[i][1], h) <= a.threshold:
                dup_idx = i; break
        if dup_idx is not None:
            removed.append(kept[dup_idx][0])   # 旧的删掉,保留新的
            del kept[dup_idx]
        kept.append((f, h))
    for f in removed:
        if not a.dry_run: os.remove(os.path.join(a.dir, f))
    print(f"== 去重: {len(files)} 帧 -> 保留 {len(kept)},删除 {len(removed)}" + (" (dry-run)" if a.dry_run else ""))
    if removed and len(removed) <= 30: print("   删除:", " ".join(removed))

if __name__ == "__main__":
    main()

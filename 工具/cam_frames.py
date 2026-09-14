#!/usr/bin/env python3
"""从"实物投影仪 / 文档摄像头"那一路录像里挑出手写页面的关键帧(老师在纸上写字,OCR 读不出来,只能看图,所以帧要少而准)。
用法: cam_frames.py <视频路径> <输出目录> [--interval 10] [--every 180] [--min-ink 0.010]
产出: <输出目录>/tXXXXXs.jpg(文件名即秒数)+ <输出目录>/cam.json
      [{"file","t","kind":"page_end"|"progress","ink","occl"}, ...]
原理(不做 OCR):
  1. 每 interval 秒抽一帧;先找白纸区域,在纸上算 ink(笔迹比例:比周围暗的细线,空白页约 0.005、写满约 0.02–0.03)、occl(手臂/袖子等遮挡比例)、dark(整帧黑屏比例)
  2. 黑屏帧(dark >= 0.85,摄像头没开)直接丢
  3. 同一页纸上 ink 只增不减;ink 比本段峰值掉一半以上、持续两帧且此时没有手遮挡 => 换页了。上一段里 ink 最多、遮挡最少的那帧就是"写完的整页"(page_end)
  4. 一段写很久时每 every 秒再留一张"书写中"(progress)帧,方便把讲解时间和纸上位置对上;和 page_end 相隔 < 45 秒的 progress 丢掉
  5. 重跑会先清掉输出目录里上一次的 t*.jpg
一节 2 小时课通常剩 20–50 帧。
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from PIL import Image, ImageChops, ImageFilter

def paper_bbox(g, th=200, frac=0.25):
    """白纸区域:亮像素(>th)在某列/某行占比超过 frac 的范围。找不到(整帧没有大片白)返回 None。"""
    bright = g.point(lambda v: 255 if v > th else 0)
    W, H = g.size
    cols = bright.resize((W, 1), Image.BOX).getdata(); rows = bright.resize((1, H), Image.BOX).getdata()
    xs = [x for x, v in enumerate(cols) if v > 255 * frac]; ys = [y for y, v in enumerate(rows) if v > 255 * frac]
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if xs and ys else None

def mask_gt(im, th): return im.point(lambda v: 255 if v > th else 0)

def features(path):
    """返回 (ink, occl, dark)。先在 640 宽缩略图上找到白纸区域,只在纸上统计:
    ink  = 笔迹比例:比周围(BoxBlur 4)暗 25 以上、且周围是亮纸面的像素 —— 铅笔/圆珠笔的细线也能抓到,桌边/袖子等大块暗区不算
    occl = 遮挡比例:肤色 + 纸上的大块暗区(袖子、笔盒)
    dark = 整帧近黑比例(黑屏检测,>=0.85 视为摄像头没开)"""
    im = Image.open(path).convert("RGB"); im.thumbnail((640, 640))
    g = im.convert("L")
    dark = mask_gt(g.point(lambda v: 255 - v), 195).histogram()[255] / (g.size[0] * g.size[1])   # v < 60
    bb = paper_bbox(g)
    if bb is None: return 0.0, 1.0, dark
    im = im.crop(bb); g = g.crop(bb); n = g.size[0] * g.size[1]
    blur = g.filter(ImageFilter.BoxBlur(4))
    stroke = mask_gt(ImageChops.subtract(blur, g), 25)
    on_paper = mask_gt(blur, 150)
    ink = ImageChops.multiply(stroke, on_paper).histogram()[255] / n
    blob = ImageChops.multiply(g.point(lambda v: 255 if v < 120 else 0), blur.point(lambda v: 255 if v <= 150 else 0)).histogram()[255] / n
    r, gg, b = im.split()
    skin = ImageChops.multiply(ImageChops.multiply(mask_gt(r, 95), mask_gt(gg, 40)),
                               ImageChops.multiply(mask_gt(ImageChops.subtract(r, b), 15), mask_gt(ImageChops.subtract(r, gg), 10))).histogram()[255] / n
    return ink, skin + blob, dark

def select(frames, every=180, min_ink=0.010, drop_ratio=0.5, near=45):
    """frames: [{"t", "ink", "occl", "dark"}] 按时间排序 → 选中的 [{"t","kind",...}]。纯函数,便于测试。"""
    frames = [f for f in frames if f["dark"] < 0.85]
    chosen = []
    seg = []     # 当前这一页的帧
    def best(s): return max(s, key=lambda f: (round(f["ink"], 3), -f["occl"]))
    i = 0
    while i < len(frames):
        f = frames[i]
        peak = max((x["ink"] for x in seg), default=0)
        nxt = frames[i + 1] if i + 1 < len(frames) else f
        if seg and peak >= min_ink and f["ink"] < peak * drop_ratio and nxt["ink"] < peak * drop_ratio and f["occl"] < 0.2 and nxt["occl"] < 0.2:
            chosen.append({**best(seg), "kind": "page_end"}); seg = []
        seg.append(f); i += 1
    if seg and max(x["ink"] for x in seg) >= min_ink: chosen.append({**best(seg), "kind": "page_end"})
    # 书写中的进度帧:每 every 秒,取该时刻附近(±2 帧)手最少的一帧
    ends = [c["t"] for c in chosen]
    prog = []
    if frames:
        t0 = frames[0]["t"]; mark = t0 + every
        for k, f in enumerate(frames):
            if f["t"] >= mark:
                win = frames[max(0, k - 2): k + 3]
                cand = min(win, key=lambda x: (round(x["occl"], 2), -x["ink"]))
                if cand["ink"] >= min_ink and all(abs(cand["t"] - e) >= near for e in ends): prog.append({**cand, "kind": "progress"})
                mark = f["t"] + every
    out = {c["t"]: c for c in chosen}
    for p in prog: out.setdefault(p["t"], p)
    return [out[t] for t in sorted(out)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("out")
    ap.add_argument("--interval", type=int, default=10); ap.add_argument("--every", type=int, default=180)
    ap.add_argument("--min-ink", type=float, default=0.010)
    a = ap.parse_args()
    if not os.path.isfile(a.video): sys.exit(f"错误: 找不到 {a.video}")
    os.makedirs(a.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="cam_", dir=a.out)
    try:
        print(f"== 实物投影抓帧: {a.video}(每 {a.interval}s 采样)")
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", a.video, "-vf", f"fps=1/{a.interval},scale=1280:-2",
                            "-fps_mode", "vfr", "-q:v", "4", os.path.join(tmp, "raw_%05d.jpg")])
        if r.returncode != 0: sys.exit("错误: ffmpeg 抽帧失败")
        raws = sorted(f for f in os.listdir(tmp) if f.startswith("raw_"))
        if not raws: sys.exit("错误: 没有抽到任何帧(视频无画面轨?)")
        frames = []
        for k, f in enumerate(raws):
            ink, occl, dark = features(os.path.join(tmp, f))
            frames.append({"t": k * a.interval, "ink": round(ink, 4), "occl": round(occl, 4), "dark": round(dark, 3), "_raw": f})
        blank = sum(1 for f in frames if f["dark"] >= 0.85)
        chosen = select(frames, every=a.every, min_ink=a.min_ink)
        old = [f for f in os.listdir(a.out) if re.match(r"t\d+s\.jpg$", f)]
        for f in old: os.remove(os.path.join(a.out, f))
        entries = []
        for c in chosen:
            name = f"t{c['t']:05d}s.jpg"
            shutil.move(os.path.join(tmp, c["_raw"]), os.path.join(a.out, name))
            entries.append({"file": name, "t": c["t"], "kind": c["kind"], "ink": c["ink"], "occl": c["occl"]})
        json.dump(entries, open(os.path.join(a.out, "cam.json"), "w"), ensure_ascii=False, indent=1)
        pages = sum(1 for e in entries if e["kind"] == "page_end")
        print(f"== 完成: 采样 {len(frames)} 帧(黑屏 {blank}),保留 {len(entries)} 帧(整页 {pages} + 书写中 {len(entries) - pages}) -> {a.out}")
        if blank == len(frames): print("   这一路全程黑屏(摄像头没开?),没有手写帧")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()

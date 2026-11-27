"""画面拉片(拉片流程第 7 节)的机测部分:接触表、切镜、换底、静止、逐镜头代表帧、前 5 秒逐 0.5 秒、进场动效逐帧量。

口径照拉片 skill 和 creator-pipeline/tools/shotlib/rhythm.py(10fps、96×54 采样,字幕区下 18% 不参与静止判断):
  - 切镜:相邻两帧整画面平均绝对差 > 28(0–255)且是局部峰值,0.3 秒内的合并;
  - 换底:四个角块平均色的中位数,每 0.5 秒比一次,变化 > 22 且持续 ≥1 秒算一次。**机测换底不可靠,只作参考**;
  - 静止:主体区(去掉下 18%)相邻帧差 < 1.2 连续超过 1 秒。
进场动效(第 7 节第 4 步「逐帧量」的半自动版):镜头开头 1 秒抽 30fps,每帧和这个镜头稳定后的帧做差、阈值化取包围盒,
算中心位移、宽度比例、亮度比例,由逐帧数值判断缓动(先快后慢 = out,两头慢 = inOut)和过冲。量不出来的标「估」。
一律要人看接触表核对,不许把估的写成量的。
"""
import json
import os
import subprocess

import numpy as np

from . import config

import sys
sys.path.insert(0, config.TOOLS)
import deps  # noqa: E402

TH = dict(cut=28.0, base=22.0, static=1.2, fps=10)
W, H = 96, 54


def ffmpeg():
    return deps.exe("ffmpeg")


def duration(video):
    r = subprocess.run([deps.exe("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def segments(dur):
    """拆哪几段:3 分钟以内整条;更长的拆 0–60 秒和片中一段 60 秒(照拉片 skill:一般取 0–60 和片中一段)"""
    if dur <= 180:
        return [(0.0, dur)]
    mid = round(dur * 0.4)
    return [(0.0, 60.0), (float(mid), 60.0)]


def _frames(video, start, dur, fps, w, h):
    cmd = [ffmpeg(), "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", video,
           "-vf", f"fps={fps},scale={w}:{h}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    if not raw:
        return np.zeros((0, h, w, 3), np.float32)
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.float32)


def rhythm(video, start, dur):
    """→ dict:cuts(秒,相对片头)、base_changes、bases(种类数)、static_ratio、shots[(起, 止)]"""
    F = TH["fps"]
    fr = _frames(video, start, dur, F, W, H)
    n = len(fr)
    if n < 2:
        return {"cuts": [], "base_changes": [], "bases": 0, "static_ratio": 0.0, "shots": [(start, start + dur)]}
    d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2, 3))
    cuts = [i + 1 for i in range(len(d)) if d[i] > TH["cut"] and (i == 0 or d[i] >= d[i - 1]) and (i + 1 >= len(d) or d[i] >= d[i + 1])]
    merged = []
    for c in cuts:
        if not merged or c - merged[-1] > 3:
            merged.append(c)

    def border(f):
        h, w = int(H * .1), int(W * .1)
        ps = [f[:h, :w], f[:h, -w:], f[int(H * .6):int(H * .6) + h, :w], f[int(H * .6):int(H * .6) + h, -w:]]
        return np.median(np.array([p.reshape(-1, 3).mean(axis=0) for p in ps]), axis=0)
    sig = np.array([border(f) for f in fr])
    step = max(F // 2, 1)
    cur, changes, kinds = sig[0], [], [sig[0]]
    for i in range(0, n, step):
        s = sig[i]
        if np.abs(s - cur).max() > TH["base"]:
            j = min(n - 1, i + F)
            if np.abs(sig[j] - s).max() < TH["base"]:
                changes.append(round(start + i / F, 1))
                cur = s
                if all(np.abs(s - k).max() > TH["base"] for k in kinds):
                    kinds.append(s)
    body = fr[:, :int(H * 0.82)]
    still = np.abs(np.diff(body, axis=0)).mean(axis=(1, 2, 3)) < TH["static"]
    run, still_frames = 0, 0
    for s in list(still) + [False]:
        if s:
            run += 1
        else:
            if run >= F:
                still_frames += run
            run = 0
    edges = [0] + merged + [n]
    shots = [(round(start + a / F, 2), round(start + b / F, 2)) for a, b in zip(edges, edges[1:]) if b > a]
    return {"cuts": [round(start + c / F, 2) for c in merged], "base_changes": changes, "bases": len(kinds),
            "static_ratio": round(still_frames / max(n - 1, 1), 3), "shots": shots}


def contact_sheet(video, start, dur, out):
    """每秒 2 帧,10 列拼一张(拉片 skill 的接触表),每格宽 320"""
    rows = max(1, int(np.ceil(dur * 2 / 10)))
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", video,
                    "-vf", f"fps=2,scale=320:-1,tile=10x{rows}", "-frames:v", "1", "-q:v", "4", out], capture_output=True)
    return os.path.isfile(out)


def grab(video, t, out, width=640):
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf", f"scale={width}:-1", "-q:v", "4", out],
                   capture_output=True)
    return os.path.isfile(out)


def summary_metrics(shots, rh_list, total_dur):
    """汇总成可比的数字(拉片 skill 第 3 步的口径,机测能算的那部分)"""
    lens = [b - a for a, b in shots]
    mins = max(sum(lens) / 60, 1e-6)
    return {"镜头数": len(shots), "每分钟镜头数": round(len(shots) / mins, 1),
            "平均镜长秒": round(sum(lens) / max(len(lens), 1), 2), "最长镜秒": round(max(lens), 2) if lens else 0,
            "8秒以上镜头数": sum(1 for x in lens if x >= 8),
            "换底次数(机测,仅参考)": sum(len(r["base_changes"]) for r in rh_list),
            "底的种类(机测,仅参考)": max((r["bases"] for r in rh_list), default=0),
            "静止超过1秒占比": f"{round(100 * sum(r['static_ratio'] for r in rh_list) / max(len(rh_list), 1))}%"}


# ---------- 进场动效:半自动逐帧量 ----------
def measure_entry(video, start, end, fps=30, width=480):
    """镜头开头的进场:从镜头第一帧量到这个镜头稳定(最多 1.4 秒,不越过镜头结尾),每帧和第一帧做差、阈值化取包围盒,
    算中心位移、宽度比例、亮度比例,判断缓动与过冲。量不可靠的情况一律返回 {"估": 原因},不硬给数字"""
    span = min(1.4, end - start - 0.04)
    if span < 0.25:
        return {"估": "镜头太短(不到 0.3 秒),没有可量的进场"}
    h = int(width * 9 / 16)
    fr = _frames(video, start, span, fps, width, h)
    if len(fr) < 8:
        return {"估": "抽到的帧太少"}
    first, final = fr[0], fr[-1]
    if np.abs(final - first).mean() < 2.0:
        return {"估": "这一段画面几乎没变,没有明显的进场动作"}
    masks = [np.abs(f - first).mean(axis=2) > 25 for f in fr]
    if masks[-1].mean() > 0.6:
        return {"估": "整个画面都在变(像推拉摇、转场或换底),包围盒法量不了,要人看帧"}
    boxes = []
    for f, m in zip(fr, masks):
        ys, xs = np.nonzero(m)
        boxes.append((xs.min(), xs.max(), ys.min(), ys.max(), float(f[m].mean())) if len(xs) >= 30 else None)
    valid = [(i, b) for i, b in enumerate(boxes) if b]
    if len(valid) < 6:
        return {"估": "进场元素太小或和底太像,包围盒取不出来"}
    bx = valid[-1][1]
    cx_end, cy_end, w_end, lum_end = (bx[0] + bx[1]) / 2, (bx[2] + bx[3]) / 2, bx[1] - bx[0] + 1, bx[4]
    cx = np.array([(b[0] + b[1]) / 2 for _, b in valid])
    cy = np.array([(b[2] + b[3]) / 2 for _, b in valid])
    wd = np.array([b[1] - b[0] + 1 for _, b in valid], dtype=float)
    lum = np.array([b[4] for _, b in valid])
    dist = np.hypot(cx - cx_end, cy - cy_end)
    move = float(dist[0])
    if move > width * 0.03:
        prog, basis = 1 - dist / move, "位移"
    elif abs(wd[0] - w_end) > w_end * 0.08:
        prog, basis = (wd - wd[0]) / (w_end - wd[0]), "缩放"
    else:
        return {"估": "元素一出现就基本到位(位移不到 3% 画面宽、宽度变化不到 8%),只能看帧判断是不是渐显"}
    if len(prog) < 6 or np.any(np.isnan(prog)):
        return {"估": "能用的帧太少"}
    over = float(prog.max() - 1)
    if over > 0.4 or prog.min() < -0.4:
        return {"估": f"{basis}曲线来回跳(可能有多个元素同时动),量不可靠,要人看帧"}
    settle = next((k for k in range(len(prog)) if all(abs(p - 1) < 0.04 for p in prog[k:])), len(prog) - 1)
    v = np.diff(prog[:settle + 1]) if settle >= 3 else np.diff(prog)
    peak = int(np.argmax(v)) / max(len(v) - 1, 1)
    easing = "out(先快后慢)" if peak < 0.35 else "inOut(两头慢)" if peak < 0.65 else "in(先慢后快)"
    return {"frames": int(valid[settle][0] - valid[0][0] + 1), "依据": basis,
            "位移_%宽": round(100 * move / width, 1), "缩放起→止": f"{round(100 * wd[0] / w_end)}% → 100%",
            "缓动": easing, "过冲_%": round(100 * over, 1) if over > 0.03 else 0}

#!/usr/bin/env python3
"""从课程视频中抓取幻灯片画面关键帧(Windows 版;macOS / Linux 仍用 extract_frames.sh。两份实现参数与产物一致,改一边要同步改另一边)
用法: extract_frames.py <视频路径> [模式,默认 12s] [输出目录]
  模式两种:
    Ns   —— 每 N 秒定点采样,再由 mpdecimate 丢掉与前一帧几乎相同的画面(默认 12s;讲师全屏翻 PDF 时推荐)
    0.xx —— ffmpeg 场景变化检测阈值(越小截得越多;纯幻灯片 0.10-0.20,带摄像头画面 0.25-0.35)
           注意:动画逐行出现、鼠标晃动会造成连拍,翻页动作小则会漏页,已知不如定点模式稳
产出: <COURSE_ROOT 或 工具/ 的上级目录>/画面/<视频名>/t<秒数>s.jpg(文件名即该帧在视频中的时间点;同一秒多帧时追加 -2、-3)
注意: 重跑会先清掉输出目录里上一次的 t*.jpg
"""
import glob, os, re, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deps

def video_filter(mode):
    if re.fullmatch(r"[1-9][0-9]*s", mode):
        n = mode[:-1]
        return f"每 {n}s 采样 + 去重", f"fps=1/{n},mpdecimate=hi=64*12:lo=64*5:frac=0.33,metadata=add:key=keep:value=1,metadata=print:file=times.txt,scale=1280:-2"
    if re.fullmatch(r"0?\.[0-9]+", mode):
        return f"场景检测阈值 {mode}", f"select='eq(n,0)+gt(scene,{mode})',metadata=print:file=times.txt,scale=1280:-2"
    return None, None

def rename_frames(meta_text, tmp, out):
    """按 times.txt 里的 pts_time 把 raw_NNNNN.jpg 依次改名为 tXXXXXs.jpg(秒数取整数部分);同一秒多帧时加 -2、-3 后缀"""
    for i, t in enumerate(re.findall(r"pts_time:([0-9.]*)", meta_text), 1):
        name = "t%05ds" % int(t.split(".")[0] or 0)
        target, k = os.path.join(out, name + ".jpg"), 1
        while os.path.exists(target): k += 1; target = os.path.join(out, f"{name}-{k}.jpg")
        shutil.move(os.path.join(tmp, "raw_%05d.jpg" % i), target)

def old_frames(out): return glob.glob(os.path.join(glob.escape(out), "t*s*.jpg"))

def main():
    if len(sys.argv) < 2: sys.exit("用法: extract_frames.py <视频路径> [Ns|阈值] [输出目录]")
    inp = sys.argv[1]; mode = sys.argv[2] if len(sys.argv) > 2 else "12s"
    if not os.path.isfile(inp): sys.exit(f"错误: 找不到文件 {inp}")
    tools = os.path.dirname(os.path.abspath(__file__))
    root = os.environ.get("COURSE_ROOT") or os.path.dirname(tools)
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(root, "画面", os.path.splitext(os.path.basename(inp))[0])
    desc, vf = video_filter(mode)
    if not vf: print(f"错误: 模式应为 Ns(如 12s)或 0-1 之间的小数(如 0.20),收到: {mode}", file=sys.stderr); sys.exit(2)
    print(f"== 抓取画面: {inp} ({desc})", flush=True)
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, ".extract_tmp")
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    try:
        # 先抓到临时目录,成功后才替换上一次的帧,失败不破坏旧产物;
        # 在临时目录里运行、滤镜里只写相对文件名:Windows 路径里的 "C:\" 在 ffmpeg 滤镜参数里要转义
        r = subprocess.run([deps.exe("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", os.path.abspath(inp), "-vf", vf,
                            "-fps_mode", "vfr", "-q:v", "3", "raw_%05d.jpg"], cwd=tmp)
        if r.returncode != 0: print("错误: ffmpeg 抓帧失败(见上方 ffmpeg 输出),保留上次的帧", file=sys.stderr); sys.exit(1)
        meta = os.path.join(tmp, "times.txt")
        if not (os.path.isfile(meta) and os.path.getsize(meta) > 0):
            print("错误: 没有抓到任何帧(视频无画面轨或过短?),保留上次的帧", file=sys.stderr); sys.exit(1)
        old = old_frames(out)
        if old:
            print(f"== 清理上次的 {len(old)} 帧")
            for f in old: os.remove(f)
        rename_frames(open(meta, encoding="utf-8").read(), tmp, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    n = len(old_frames(out))
    print(f"== 完成: 共 {n} 帧 -> {out}")
    if n > 150: print("   帧数偏多,可加大采样间隔(如 20s)或提高阈值重跑", file=sys.stderr)

if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr): s.reconfigure(encoding="utf-8", errors="replace")   # Windows 终端/管道默认 GBK 或 cp1252,打印中文和 ✅⚠️🎯 会报 UnicodeEncodeError
    main()

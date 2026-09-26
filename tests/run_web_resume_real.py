#!/usr/bin/env python3
"""真实阶段恢复测试(需要 macOS + ffmpeg + whisper-cli + tesseract + 已下载的 whisper 模型):
1. 用示例视频真实跑 转写 → 抓帧;OCR 阶段运行时把 tesseract 从 PATH 里拿掉,让真实的 ocr_frames.py 失败
2. 恢复 PATH 后重试;用包在 whisper-cli 外面的计数脚本证明 whisper 没有再运行,并检查转写日志、完成时间没变
3. 检查最终产物可解析、字段完整
用法: python3 tests/run_web_resume_real.py   环境变量 WHISPER_MODEL(默认 tiny.en)
"""
import json, os, shutil, stat, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
work = tempfile.mkdtemp(prefix="lsk-resume-")
os.environ["LSK_DATA"] = os.path.join(work, "data")
from web import jobs, sources  # noqa: E402

def main():
    real = shutil.which("whisper-cli")
    if not real: sys.exit("SKIP: 没有 whisper-cli")
    shim_dir = os.path.join(work, "shim"); os.makedirs(shim_dir)
    count = os.path.join(work, "whisper-calls.txt")
    shim = os.path.join(shim_dir, "whisper-cli")
    open(shim, "w").write(f'#!/bin/bash\necho "$(date +%s) $*" >> "{count}"\nexec "{real}" "$@"\n')
    os.chmod(shim, os.stat(shim).st_mode | stat.S_IEXEC)
    os.environ["PATH"] = shim_dir + os.pathsep + os.environ["PATH"]
    video = os.path.join(work, "演示 录播.mp4")
    shutil.copy(os.path.join(ROOT, "examples", "demo", "课程视频", "DEMO1001 - 01 Jan 26-s1-demo.mp4"), video)

    job = jobs.create({"mode": "video"}); jid = job["id"]
    jobs.update(jid, lambda j: (j["inputs"].__setitem__("video", jobs.describe_input(video)),
                                j["options"].__setitem__("whisper_model", os.environ.get("WHISPER_MODEL", "tiny.en"))))
    orig_ocr = jobs.HANDLERS["ocr"]
    def failing_ocr(job, ctx):
        saved = os.environ["PATH"]
        tdir = os.path.dirname(shutil.which("tesseract"))
        os.environ["PATH"] = os.pathsep.join(p for p in saved.split(os.pathsep) if os.path.realpath(p) != os.path.realpath(tdir))
        try: orig_ocr(job, ctx)                 # 真实的 ocr_frames.py,因找不到 tesseract 失败
        finally: os.environ["PATH"] = saved
    jobs.HANDLERS["ocr"] = failing_ocr
    r = jobs.Runner()
    r.enqueue(jid)
    while jobs.load(jid)["state"] in ("queued", "running"): time.sleep(0.2)
    j = jobs.load(jid)
    print("第一次:", j["state"], {k: v["status"] for k, v in j["stages"].items()})
    assert j["state"] == "failed" and j["stages"]["ocr"]["status"] == "failed", j["stages"]
    print("   OCR 失败原因:", j["stages"]["ocr"]["error"]["what"], "|", j["stages"]["ocr"]["error"]["saved"])
    calls1 = open(count).read().splitlines()
    tlog = os.path.join(jobs.job_dir(jid), "logs", "transcribe.log")
    tlog_mtime = os.path.getmtime(tlog); t_end = j["stages"]["transcribe"]["ended"]
    srt_mtime = os.path.getmtime(os.path.join(jobs.job_dir(jid), "work", "lecture.srt"))
    print(f"   whisper-cli 调用 {len(calls1)} 次")

    jobs.HANDLERS["ocr"] = orig_ocr
    time.sleep(1.1)
    r.enqueue(jid)
    while jobs.load(jid)["state"] in ("queued", "running"): time.sleep(0.2)
    j = jobs.load(jid)
    print("重试后:", j["state"], {k: (v["status"], v.get("ended")) for k, v in j["stages"].items()})
    calls2 = open(count).read().splitlines()
    assert j["state"] == "done", j["stages"]
    assert calls2 == calls1, f"whisper 被再次调用: {calls2[len(calls1):]}"
    assert os.path.getmtime(tlog) == tlog_mtime and j["stages"]["transcribe"]["ended"] == t_end
    assert os.path.getmtime(os.path.join(jobs.job_dir(jid), "work", "lecture.srt")) == srt_mtime
    print(f"   whisper-cli 调用仍为 {len(calls2)} 次;转写日志与 lecture.srt 修改时间未变;转写完成时间仍为 {t_end}")
    reg = sources.load(jobs.job_dir(jid))
    ocr = json.load(open(os.path.join(jobs.job_dir(jid), "work", "frames", "ocr.json")))
    assert reg["segments"] and reg["frames"] and all("file" in e and "t" in e for e in ocr)
    assert "prime path" in " ".join(s["text"].lower() for s in reg["segments"])
    print(f"   产物:{len(reg['segments'])} 段转写,{len(reg['frames'])} 张截图,OCR {len(ocr)} 条,均可解析")
    print("PASS: 真实阶段恢复")

if __name__ == "__main__":
    try: main()
    finally: shutil.rmtree(work, ignore_errors=True)

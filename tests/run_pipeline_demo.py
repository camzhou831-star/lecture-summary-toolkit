#!/usr/bin/env python3
"""集成测试:用仓库自带的合成示例视频跑完整视频流水线(CI 用 tiny.en 模型,几十秒),再校验示例总结。macOS / Windows / Linux 共用
用法: python3 tests/run_pipeline_demo.py   环境变量: WHISPER_MODEL(默认 tiny.en,本机可设 large-v3-turbo)
需要: ffmpeg、whisper-cli、tesseract、Pillow;课件匹配用 pdftotext,没有时用 pypdf"""
import glob, os, platform, re, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "工具")
sys.path.insert(0, TOOLS)
import deps
NAME = "DEMO1001 - 01 Jan 26-s1-demo"

def version(cmd, *args):
    p = deps.find(cmd)
    if not p: return "没找到"
    r = subprocess.run([p, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return ((r.stdout or r.stderr).strip().splitlines() or ["?"])[0][:80]

def fail(msg, work):
    print("FAIL: " + msg)
    for f in glob.glob(os.path.join(work, "课程视频", "*.log")):
        print("--- " + f); print("\n".join(open(f, encoding="utf-8", errors="replace").read().splitlines()[-50:]))
    sys.exit(1)

def main():
    print(f"== 环境: {platform.system()} {platform.machine()} {os.cpu_count()} 核; whisper-cli: {deps.find('whisper-cli')}; "
          f"ffmpeg: {version('ffmpeg', '-version')}; tesseract: {version('tesseract', '--version')}; pdftotext: {deps.find('pdftotext') or '无(用 pypdf)'}")
    work = tempfile.mkdtemp(prefix="demo_")
    try:
        shutil.copytree(os.path.join(ROOT, "examples", "demo"), work, dirs_exist_ok=True)
        shutil.rmtree(os.path.join(work, "画面"), ignore_errors=True)
        for pat in ("*.srt", "*.txt", "*.json", "*.md"):
            for f in glob.glob(os.path.join(work, "课程视频", pat)): os.remove(f)
        env = dict(os.environ, COURSE_ROOT=work, WHISPER_MODEL=os.environ.get("WHISPER_MODEL", "tiny.en"))
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "lsk.py"), "run", NAME + ".mp4", "--lang-code", "en"], env=env)
        if r.returncode != 0: fail(f"lsk run 视频模式退出码 {r.returncode}", work)
        g = open(os.path.join(work, "课程视频", NAME + ".grounded.md"), encoding="utf-8").read()
        if "prime path" not in g.lower(): fail("转写里没有 'prime path'", work)
        if not re.search(r"📄 t=.*p[0-9]/6 DEMO1001", g): fail("PDF 页码匹配没有生效", work)
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "check_summary.py"), os.path.join(work, "总结", "DEMO1001", NAME + ".md")], env=env)
        if r.returncode != 0: fail("示例总结没通过 check_summary", work)
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "course_meta.py"), NAME + ".mp4", "--json"], env=env, capture_output=True, text=True, encoding="utf-8")
        if '"week": 1' not in r.stdout: fail("course_meta 周次不对", work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("PASS: pipeline demo")

if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr): s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)   # 和子进程输出按顺序交错
    main()

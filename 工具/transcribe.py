#!/usr/bin/env python3
"""ffmpeg 抽音频 + whisper.cpp 转写(Windows 版;macOS / Linux 仍用 transcribe.sh。两份实现参数与产物一致,改一边要同步改另一边)
用法: transcribe.py <视频或音频文件> [语言码,默认 auto]
输出: 与输入文件同目录的 <文件名>.srt 和 <文件名>.txt(stdout 打印这两个路径,过程信息走 stderr)
环境变量: WHISPER_MODEL(默认 large-v3-turbo) WHISPER_MODEL_DIR  NO_VAD=1 关闭静音检测  GLOSSARY=<文件> 指定术语表  NO_GPU=1 强制 CPU
          OUT_BASE=<不带扩展名的输出路径> 让 srt/txt 用别的名字(双路录像时从另一路取声音,但产物仍归主文件名)
          WHISPER_THREADS 线程数(默认 min(8, CPU 核数))
失败回退: GPU 崩溃(如 Metal 在 agent 沙箱内、Windows GPU 版遇到驱动太旧或不支持的显卡)→ 自动用 --no-gpu 重试 → 再失败用基础参数重试 → Windows 上最后换 CPU 版 whisper.cpp
Windows: whisper.cpp 按系统代码页读文件名,所以音频和输出都放在临时目录,模型路径换成 8.3 短路径
"""
import os, re, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deps
TOOLS = os.path.dirname(os.path.abspath(__file__))

def glossary_for(name, course_root):
    """按文件名开头的课程号(如 DEMO1001)找术语表:先 <COURSE_ROOT>/glossary/,再 工具/glossary/(兼容旧布局)"""
    m = re.match(r"[A-Z]{4}[0-9]{4}", os.path.basename(name))
    if not m: return None
    for g in (os.path.join(course_root, "glossary", m[0] + ".txt"), os.path.join(TOOLS, "glossary", m[0] + ".txt")):
        if os.path.isfile(g): return g
    return None

LEAD = {"en": "Welcome back, everyone. Today we will continue with the lecture.",
        "zh": "以下是一节课程录音的转写，使用简体中文和标点符号。"}
def lead_prompt(prompt, lang):
    """提示语里没有一句带标点的话时,按语言补一句开头:whisper 照提示语的风格输出,没有标点的提示(或没有提示)时,
    偶尔会整篇不带标点和大小写(第一段没写标点,后面就一直不写;Metal / Vulkan / CPU 都遇到过)"""
    lead = LEAD.get(lang)
    if lead and not re.search(r"[.?!。？！]", prompt): prompt = f"{lead} {prompt}"
    return prompt.rstrip()

def log(msg): print(msg, file=sys.stderr, flush=True)

def main():
    if len(sys.argv) < 2: sys.exit("用法: transcribe.py <视频或音频文件> [语言码]")
    inp, lang = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "auto")
    if not os.path.isfile(inp): sys.exit(f"错误: 找不到文件 {inp}")
    env = os.environ
    model_name = env.get("WHISPER_MODEL", "large-v3-turbo")
    whisper = deps.find("whisper-cli")
    if not whisper: sys.exit(f"错误: 找不到 whisper-cli;安装: {deps.how('whisper-cli')}")
    ffmpeg, ffprobe = deps.exe("ffmpeg"), deps.exe("ffprobe")
    model = deps.ensure_model(model_name)

    vad_args = []                                    # 静音检测(VAD):只把有人声的片段送给 whisper,静音段不再产生 "Thank you." 一类幻觉
    if env.get("NO_VAD", "0") != "1":
        vad_args = ["--vad", "-vm", deps.short_path(deps.ensure_vad()), "--vad-threshold", "0.5",
                    "--vad-min-speech-duration-ms", "250", "--vad-speech-pad-ms", "200"]
    prompt = ""                                      # 术语表:喂给 whisper 的 --prompt 提高专有名词准确率;术语表属于课程数据,不进工具仓库
    course_root = env.get("COURSE_ROOT") or os.path.dirname(TOOLS)
    glossary = env.get("GLOSSARY") or glossary_for(env.get("OUT_BASE") or inp, course_root)
    if glossary and os.path.isfile(glossary):
        log(f"== 术语表: {glossary}")
        prompt = open(glossary, encoding="utf-8").read().replace("\n", " ")
    prompt = lead_prompt(prompt, lang)
    prompt_args = ["--prompt", prompt] if prompt else []
    ncpu = os.cpu_count() or 4                        # CI 小机器上超额分配线程会拖慢甚至卡住
    threads = env.get("WHISPER_THREADS") or str(min(8, ncpu))
    base = env.get("OUT_BASE") or os.path.splitext(inp)[0]
    no_gpu = env.get("NO_GPU", "0") == "1"

    with tempfile.TemporaryDirectory(prefix="transcribe_") as tmp:
        tmp_s = deps.short_path(tmp)
        wav, out = os.path.join(tmp_s, "audio.wav"), os.path.join(tmp_s, "out")
        log("== 提取音频...")
        r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", inp, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav])
        if r.returncode != 0: sys.exit("错误: ffmpeg 提取音频失败")
        dur = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav], capture_output=True, text=True).stdout.strip()
        log(f"== 音频时长: {dur.split('.')[0]} 秒,开始转写 (模型: {model_name}, VAD: {'开' if vad_args else '关'}, 线程: {threads}, GPU: {'关' if no_gpu else '开'})...")

        def run_whisper(*extra, exe=whisper):
            cmd = [exe, "-m", deps.short_path(model), "-f", wav, "-l", lang, "-t", threads, *extra,
                   "--output-srt", "--output-txt", "--output-file", out, "--no-prints"]
            return subprocess.run(cmd).returncode
        gpu = ["--no-gpu"] if no_gpu else []
        rc = run_whisper(*gpu, *vad_args, *prompt_args, "--suppress-nst")
        if rc != 0 and not gpu:
            log(f"== whisper-cli 失败(退出码 {rc}),改用 CPU(--no-gpu)重试...")   # 沙箱里 Metal 会段错误、CUDA 驱动或显卡不支持;慢很多,但能跑
            rc = run_whisper("--no-gpu", *vad_args, *prompt_args, "--suppress-nst")
        if rc != 0:
            log(f"== whisper-cli 仍失败(退出码 {rc}),改用不带 VAD/术语表的基础参数最后重试一次...")
            rc = run_whisper(*gpu)
            cpu_cli = os.path.join(deps.whisper_win_dir("cpu"), "whisper-cli.exe")
            if rc != 0 and deps.WINDOWS and os.path.isfile(cpu_cli) and os.path.normcase(cpu_cli) != os.path.normcase(whisper):
                log(f"== GPU 版 whisper.cpp 启动不了(退出码 {rc},常见原因:显卡驱动太旧或没装),改用 CPU 版...")
                rc = run_whisper("--no-gpu", *vad_args, *prompt_args, "--suppress-nst", exe=cpu_cli)
            if rc != 0: sys.exit(f"错误: whisper-cli 三次都失败(最后退出码 {rc}),放弃")
        if not (os.path.isfile(out + ".srt") and os.path.getsize(out + ".srt") > 0): sys.exit(f"错误: 转写没有产出 {base}.srt")
        for ext in (".srt", ".txt"):
            if os.path.isfile(out + ext): shutil.move(out + ext, base + ext)
    log("== 完成:")
    print(base + ".srt"); print(base + ".txt")

if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr): s.reconfigure(encoding="utf-8", errors="replace")   # Windows 终端/管道默认 GBK 或 cp1252,打印中文和 ✅⚠️🎯 会报 UnicodeEncodeError
    main()

#!/usr/bin/env python3
"""浏览器自动化交互测试(Playwright 驱动本机 Chrome,无头)。这是自动化测试,不是人工测试。
运行: uv run --no-project --with playwright==1.55.0 python tests/e2e_web.py
需要: macOS 上安装了 Google Chrome;视频部分需要 ffmpeg / whisper-cli / tesseract / large-v3-turbo 模型(用来制造一个可取消的转写)
覆盖: 新建任务、上传字幕与课件、切换档位、开始处理、下载 AI 材料、复制提示词(读剪贴板核对)、分段页签、粘贴回复、检查结果、
      点击来源、导出笔记、刷新页面、视频任务取消与重试、关闭工作台后重启并「继续」。"""
import json, os, re, shutil, signal, subprocess, sys, tempfile, time, urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo")
work = tempfile.mkdtemp(prefix="lsk-e2e-")
DATA = os.path.join(work, "data"); PORT = 8911
files = os.path.join(work, "中文 材料"); os.makedirs(files)
SRT = os.path.join(files, "演示 字幕.srt"); shutil.copy(os.path.join(DEMO, "课程视频", "DEMO1001 - 01 Jan 26-s1-demo.srt"), SRT)
PDF = os.path.join(files, "演示 课件.pdf"); shutil.copy(os.path.join(DEMO, "课件", "DEMO1001", "DEMO1001-testing-loops.pdf"), PDF)
MP4 = os.path.join(files, "演示 录播.mp4"); shutil.copy(os.path.join(DEMO, "课程视频", "DEMO1001 - 01 Jan 26-s1-demo.mp4"), MP4)
LOG = []

def step(msg): LOG.append(msg); print("✔", msg, flush=True)

def start_server():
    env = dict(os.environ, LSK_DATA=DATA)
    # 用系统 python3 启动(与双击「启动工作台」相同),不用 uv 临时环境里的 Python
    p = subprocess.Popen([os.environ.get("LSK_PY", "/usr/bin/python3"), "-m", "web", "--no-browser", "--port", str(PORT)],
                         cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(100):
        line = p.stdout.readline()
        m = re.search(r"(http://127\.0\.0\.1:\d+/auth\?t=\S+)", line)
        if m: return p, m.group(1)
    raise RuntimeError("服务没有启动")

def stop_server(p):
    p.send_signal(signal.SIGTERM)
    try: p.wait(10)
    except subprocess.TimeoutExpired: p.kill()

def main():
    srv, url = start_server()
    base = url.split("/auth")[0]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(accept_downloads=True, permissions=["clipboard-read", "clipboard-write"], viewport={"width": 1300, "height": 900})
        page = ctx.new_page()
        errors = []; page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url); expect(page.get_by_text("把一节课整理成可回查来源的学习笔记")).to_be_visible(); step("从启动链接进入(会话 cookie 生效)")

        # ---- 字幕任务 ----
        page.get_by_role("button", name="+ 新建任务").click()
        page.locator("#form-new input[value=subtitle]").check()
        page.locator("#form-new select[name=template]").select_option("full")
        page.locator("#form-new button[value=ok]").click()
        expect(page.get_by_text("① 材料")).to_be_visible(); step("新建字幕任务(对话框)")
        page.set_input_files("#file-upload", [SRT, PDF])
        expect(page.get_by_text("字幕:演示 字幕.srt")).to_be_visible()
        expect(page.get_by_role("button", name="开始处理")).to_be_visible()      # 上传后不刷新也要能开始(曾因返回格式不对而空白)
        expect(page.get_by_text("课件:演示 课件.pdf")).to_be_visible()     # 一次选两个文件都要上传(曾经只传了第一个)
        step("上传字幕与课件(中文+空格文件名)")
        page.locator("#job").get_by_label("笔记档位").select_option("concise")
        page.wait_for_timeout(300); page.reload()
        expect(page.locator("#job").get_by_label("笔记档位")).to_have_value("concise"); step("切换档位为简明版,刷新后保持")
        page.get_by_role("button", name="开始处理").click()
        expect(page.get_by_role("button", name="复制提示词", exact=True)).to_be_visible(timeout=20000); step("本地处理完成,出现 AI 材料")
        with page.expect_download() as dl:
            page.get_by_role("link", name=re.compile(r"AI材料-.*\.md")).click()
        p = dl.value.path(); mat = open(p, encoding="utf-8").read()
        assert "[S1 ·" in mat and "[P1-1]" in mat, mat[:300]; step(f"下载 AI 材料({len(mat)} 字符,含 S/P 编号)")
        page.get_by_role("button", name="复制提示词", exact=True).click(); page.wait_for_timeout(300)
        clip = page.evaluate("navigator.clipboard.readText()")
        assert "【LSK 笔记 job=" in clip and "## 待复习问题" in clip, clip[:200]; step("复制提示词(剪贴板内容为简明版结构)")
        jid = re.search(r"job=([0-9a-z-]+)", clip).group(1)
        page.get_by_role("button", name=re.compile("分段复制")).click()
        expect(page.get_by_text("第 1/1 段")).to_be_visible(); step("切到分段复制页签")
        page.get_by_role("button", name=re.compile("复制第 1 段")).click(); page.wait_for_timeout(200)
        assert "【LSK 分段 1/1" in page.evaluate("navigator.clipboard.readText()"); step("复制第 1 段(含提示词)")

        reply = (f"```markdown\n【LSK 笔记 job={jid}】\n# DEMO · 循环测试\n### 1. 一句话概括\n循环要测 0/1/多次 [S1]。\n## 核心概念\n1. 素路径 [S2][P1-4]\n2. 没有来源的一条\n"
                 f"## 主要例题\n- while 循环 [P1-5]\n## 课堂重点\n- 🎯 下周测验考这套课件 ——依据:「quiz next week will cover this slide deck」[S2]\n- ⭐ 0/1/多次 [S1]\n"
                 f"## 待复习问题\n- 什么是素路径?[S9]\n```")
        page.locator("#paste").fill(reply)
        page.get_by_role("button", name="检查并保存").click()
        expect(page.get_by_text(re.compile(r"检查结果:1 个问题"))).to_be_visible()
        expect(page.get_by_text("引用的来源 [S9] 不存在")).to_be_visible()
        expect(page.get_by_text(re.compile("末尾没有结束标记"))).to_be_visible(); step("粘贴回复 → 检查结果(无效引用为问题,缺结束标记为提醒)")
        page.locator(".note .cite[data-id=P1-4]").click()
        expect(page.locator("#ev-body")).to_contain_text("Prime paths"); step("点击来源 P1-4,右侧显示课件原文")
        page.locator(".note .cite[data-id=S2]").first.click()
        expect(page.locator("#ev-body")).to_contain_text("prime path"); step("点击来源 S2,显示转写原文(无视频时没有播放器)")
        assert page.locator("#ev-body video").count() == 0
        with page.expect_download() as dl:
            page.get_by_role("link", name="导出 Markdown").click()
        md = open(dl.value.path(), encoding="utf-8").read()
        assert "## 来源" in md and "LSK" not in md and "[S2]" not in md; step("导出 Markdown(来源附录,无内部标记)")
        page.reload(); expect(page.locator("#preview .note")).to_contain_text("循环要测"); step("刷新页面后笔记仍在")

        # ---- 视频任务:取消与重试 ----
        page.get_by_role("button", name="+ 新建任务").click()
        page.locator("#form-new input[value=video]").check(); page.locator("#form-new button[value=ok]").click()
        expect(page.get_by_role("button", name="选择录播视频")).to_be_visible()     # 等新任务页面渲染完再上传
        page.set_input_files("#file-upload", [MP4])
        expect(page.get_by_text("视频:演示 录播.mp4")).to_be_visible(); step("新建视频任务并上传视频")
        try: page.get_by_role("button", name="开始处理").click(timeout=10000)
        except Exception:
            page.screenshot(path=os.environ.get("E2E_SHOT", os.path.join(work, "fail.png")), full_page=True); raise
        expect(page.get_by_text(re.compile("转写中"))).to_be_visible(timeout=20000)
        page.get_by_role("button", name="取消").click()
        expect(page.get_by_role("button", name="开始处理")).to_be_visible(timeout=15000)
        expect(page.locator(".stages")).to_contain_text("已取消"); step("转写中点「取消」,状态为已取消")
        page.get_by_role("button", name="开始处理").click()
        expect(page.get_by_text(re.compile("转写中"))).to_be_visible(timeout=20000); step("重试:重新开始转写")
        vjid = page.evaluate("location.hash").split("=")[1]
        stop_server(srv); step("转写进行中关闭工作台(SIGTERM)")
        st = json.load(open(os.path.join(DATA, "jobs", vjid, "job.json")))
        assert st["state"] == "interrupted", st["state"]
        srv, url2 = start_server(); assert url2 == url                            # 会话 token 持久化,旧页面仍可用
        page.reload()
        expect(page.get_by_role("button", name="继续")).to_be_visible(timeout=10000); step("重启工作台后刷新:任务显示「中断」和「继续」")
        page.get_by_role("button", name="继续").click()
        try: expect(page.get_by_role("button", name=re.compile("上传文件"))).to_be_visible(timeout=180000)
        except AssertionError:
            j = json.load(open(os.path.join(DATA, "jobs", vjid, "job.json")))
            print("JOB:", j["state"], {k: (v["status"], (v.get("error") or {}).get("what")) for k, v in j["stages"].items()})
            page.screenshot(path=os.environ.get("E2E_SHOT", os.path.join(work, "fail.png")), full_page=True); raise
        step("点「继续」后处理完成(出现 AI 材料页签)")
        expect(page.locator(".job-list")).to_contain_text("演示 字幕"); step("历史任务列表保留字幕任务")
        assert not errors, errors; step("页面没有 JavaScript 报错")
        browser.close()
    stop_server(srv)
    print("PASS: e2e", len(LOG), "步")

if __name__ == "__main__":
    try: main()
    finally: shutil.rmtree(work, ignore_errors=True)

#!/usr/bin/env python3
"""网页工作台的测试:不需要 whisper/tesseract/网络。运行: python3 -m unittest discover -s tests -v
覆盖:字幕解析与检查、仅课件模式不产生课堂来源、扫描版 PDF 的提示、材料分块与去重、回复检查(缺块/重复/错块/无效引用/截断/🎯)、
     安全渲染、阶段恢复(失败后只重跑失败的阶段)、输入变化使缓存失效、重启后识别中断任务、本地服务的访问控制、有/无视频时的来源面板。"""
import http.client, json, os, shutil, sys, tempfile, threading, time, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEMO = os.path.join(ROOT, "examples", "demo")
DEMO_SRT = os.path.join(DEMO, "课程视频", "DEMO1001 - 01 Jan 26-s1-demo.srt")
DEMO_PDF = os.path.join(DEMO, "课件", "DEMO1001", "DEMO1001-testing-loops.pdf")

_tmp = tempfile.mkdtemp(prefix="lsk-test-")
os.environ["LSK_DATA"] = _tmp
from web import subtitles, materials, checks, mdrender, sources, jobs, pdftext, server  # noqa: E402
from web import templates as T  # noqa: E402

def tearDownModule():
    shutil.rmtree(_tmp, ignore_errors=True)

def reg_lecture():
    """合成的来源登记表:3 分钟转写 + 2 张截图(同一页课件出现两次)+ 一份 3 页课件"""
    return {"mode": "video", "has_video": True, "duration": 400,
            "segments": [{"id": "S1", "start": 5, "end": 58, "text": "intro to loops"},
                         {"id": "S2", "start": 61, "end": 119, "text": "this will be on the exam: prime paths"},
                         {"id": "S3", "start": 330, "end": 390, "text": "after the break"}],
            "gaps": [{"start": 122, "end": 330}],
            "decks": [{"idx": 1, "name": "deck", "file": "/x/deck.pdf", "status": "ok",
                       "pages": [{"id": "P1-1", "page": 1, "text": "Title page UNIQUEPAGEONE"},
                                 {"id": "P1-2", "page": 2, "text": "Prime paths definition UNIQUEPAGETWO"},
                                 {"id": "P1-3", "page": 3, "text": "Unshown page UNIQUEPAGETHREE"}]}],
            "frames": [{"id": "F1", "file": "t00010s.jpg", "t": 10, "text": "", "chars": 0, "slide": "P1-2"},
                       {"id": "F2", "file": "t00070s.jpg", "t": 70, "text": "", "chars": 0, "slide": "P1-2"},
                       {"id": "F3", "file": "t00340s.jpg", "t": 340, "text": "terminal $ ls", "chars": 12, "slide": None}],
            "cam": []}

def reg_slides():
    r = reg_lecture(); r.update(mode="slides", has_video=False, segments=[], gaps=[], frames=[], duration=None)
    return r

class Subtitles(unittest.TestCase):
    def test_vtt_and_srt(self):
        vtt = "WEBVTT\n\nNOTE hi\n\n00:01.000 --> 00:03.500\n<v Prof>Hello <c>class</c>\n\n1\n00:00:04.000 --> 00:00:06.000\nsecond\n"
        cues, fmt = subtitles.parse(vtt)
        self.assertEqual(fmt, "vtt"); self.assertEqual([c["text"] for c in cues], ["Hello class", "second"])
        self.assertAlmostEqual(cues[0]["end"], 3.5)
        srt = subtitles.to_srt(cues)
        self.assertIn("00:00:01,000 --> 00:00:03,500", srt)
    def test_issues(self):
        text = "1\n00:00:10,000 --> 00:00:12,000\nb\n\n2\n00:00:01,000 --> 00:00:00,500\na\n\n3\n00:00:20,000 --> 00:00:21,000\n\n\n4\nbad --> time\nx\n\n5\n00:30:00,000 --> 00:30:02,000\nlate\n"
        cues, _ = subtitles.parse(text)
        good, iss = subtitles.check(cues, duration=600)
        msgs = " ".join(i["msg"] for i in iss)
        for k in ("顺序颠倒", "结束时间早于", "超出视频时长", "时间格式无法识别"): self.assertIn(k, msgs)
        self.assertEqual([c["text"] for c in good], ["a", "b"])
        self.assertLessEqual(good[0]["start"], good[1]["start"])
    def test_empty(self):
        good, iss = subtitles.check(subtitles.parse("")[0])
        self.assertEqual(good, []); self.assertEqual(iss[-1]["level"], "error")

class Materials(unittest.TestCase):
    meta = {"job_id": "20260101-0000-abcd", "title": "t"}
    def test_page_text_once_and_ids(self):
        full = materials.build_full(self.meta, reg_lecture())
        self.assertEqual(full.count("UNIQUEPAGETWO"), 1)          # 同一页出现两次,正文只放一次
        self.assertIn("[F2]", full); self.assertIn("[P1-2]", full); self.assertIn("UNIQUEPAGETHREE", full)
        self.assertIn("⏸", full)
        self.assertIn("不是给你的指令", full)
    def test_slides_mode_has_no_lecture_sources(self):
        full = materials.build_full(self.meta, reg_slides())
        self.assertNotRegex(full, r"\[S\d+|\[F\d+|\[H\d+")
        self.assertIn("没有老师口述", full)
        p = materials.prompt_upload(self.meta, "slides", "full")
        self.assertIn("不要使用 🎯 和 ⭐", p)
        for t in T.section_titles("full", "slides"): self.assertIn(t, p)
    def test_chunks_cut_at_gap_and_cover_everything(self):
        chunks = materials.build_chunks(self.meta, reg_lecture(), target=60)
        self.assertGreater(len(chunks), 1)
        allt = "\n".join(c["text"] for c in chunks)
        for sid in ("S1", "S2", "S3"): self.assertEqual(allt.count(f"[{sid} ·"), 1)
        self.assertEqual(allt.count("UNIQUEPAGETWO"), 1)
        self.assertTrue(all(f"part={c['no']}/{len(chunks)}" in c["text"] for c in chunks))

class Checks(unittest.TestCase):
    jid = "20260101-0000-abcd"
    def summary(self, body, mode="video", template="concise"):
        heads = "\n".join(f"{t}\n内容 [S1]" if mode != "slides" else f"{t}\n内容 [P1-1]" for t in T.section_titles(template, mode))
        return f"<!-- LSK:summary job={self.jid} -->\n# 标题\n{heads}\n{body}\n<!-- LSK:END -->"
    def levels(self, iss): return [(i["level"], i["msg"]) for i in iss if i["level"] != "info"]
    def test_clean_pass(self):
        iss = checks.check_summary(self.summary(""), reg_lecture(), "concise", "video", self.jid)
        self.assertEqual(self.levels(iss), [])
        self.assertIn("不代表内容一定正确", iss[-1]["msg"])
    def test_bad_citation_and_target(self):
        iss = checks.check_summary(self.summary("- 🎯 考这个 [P1-2]\n- 还有 [S99]"), reg_lecture(), "concise", "video", self.jid)
        msgs = " ".join(m for _, m in self.levels(iss))
        self.assertIn("[S99] 不存在", msgs); self.assertIn("🎯 标记没有引用", msgs)
    def test_slides_mode_rejects_lecture_claims(self):
        body = "- 🎯 老师强调这个 [P1-2]\n- ⭐ 重点 [P1-1]\n- 看 [S1] 和 12:30"
        iss = checks.check_summary(self.summary(body, "slides", "full"), reg_slides(), "full", "slides", self.jid)
        msgs = " ".join(m for _, m in self.levels(iss))
        for k in ("仅课件模式出现了 🎯", "仅课件模式出现了 ⭐", "仅课件模式出现了转写", "老师…", "像时间戳"): self.assertIn(k, msgs)
    def test_truncation_and_missing_sections(self):
        t = f"<!-- LSK:summary job={self.jid} -->\n# 标题\n## 一句话概括\n半截 [S1]"
        msgs = " ".join(m for _, m in self.levels(checks.check_summary(t, reg_lecture(), "concise", "video", self.jid)))
        self.assertIn("截断", msgs); self.assertIn("缺少小节「核心概念」", msgs)
    def test_wrong_job(self):
        t = self.summary("").replace(self.jid, "20250101-0000-zzzz")
        self.assertIn("不一致", " ".join(m for _, m in self.levels(checks.check_summary(t, reg_lecture(), "concise", "video", self.jid))))
    def test_timestamp_beyond_duration(self):
        msgs = " ".join(m for _, m in self.levels(checks.check_summary(self.summary("在 99:00 讲的"), reg_lecture(), "concise", "video", self.jid)))
        self.assertIn("超出录播时长", msgs)
    def test_parts(self):
        p2 = f"<!-- LSK:part 2/3 job={self.jid} -->\n## 本段要点\n- x [S1]\n<!-- LSK:END -->"
        self.assertIn("粘贴在第 1/3 块", " ".join(i["msg"] for i in checks.check_part(p2, 1, 3, reg_lecture(), "video", self.jid)))
        self.assertEqual([i for i in checks.check_part(p2, 2, 3, reg_lecture(), "video", self.jid) if i["level"] == "error"], [])
        st = " ".join(i["msg"] for i in checks.parts_status({"1": p2, "2": p2}, 3))
        self.assertIn("还缺第 3 块", st); self.assertIn("内容相同", st)
        both = p2 + "\n" + p2.replace("2/3", "3/3")
        self.assertIn("多个分块标记", " ".join(i["msg"] for i in checks.check_part(both, 2, 3, reg_lecture(), "video", self.jid)))

class Render(unittest.TestCase):
    def test_escapes_html_and_links_citations(self):
        idx = sources.index(reg_lecture())
        out = mdrender.render("# T\n<script>alert(1)</script> <img src=x onerror=alert(1)> [S1][S404] [x](javascript:alert(1))", idx)
        self.assertNotIn("<script", out); self.assertNotIn("<img", out); self.assertNotIn("javascript:", out.split("&lt;script")[0] + "")
        self.assertIn('data-id="S1"', out); self.assertIn("S404?", out)
        self.assertNotIn('href="javascript', out)

class Pdf(unittest.TestCase):
    def test_text_pdf_and_scanned(self):
        if not pdftext.backend(): self.skipTest("没有 pdftotext / pypdf")
        pages = pdftext.extract_pages(DEMO_PDF)
        self.assertEqual(len(pages), 6); self.assertEqual(pdftext.text_status(pages), "ok")
        from PIL import Image
        scan = os.path.join(_tmp, "扫描 版.pdf")
        Image.new("RGB", (400, 300), "white").save(scan)
        self.assertEqual(pdftext.text_status(pdftext.extract_pages(scan)), "none")

def wait_job(jid, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = jobs.load(jid)
        if j["state"] not in ("queued", "running"): return j
        time.sleep(0.05)
    raise AssertionError("任务没有结束")

class Pipeline(unittest.TestCase):
    """真实跑字幕模式与仅课件模式(纯 Python,不需要 whisper/ffmpeg);阶段恢复用替换过的处理函数测试"""
    @classmethod
    def setUpClass(cls):
        cls.runner = jobs.Runner()
        cls.dir = os.path.join(_tmp, "中文 路径"); os.makedirs(cls.dir, exist_ok=True)
        cls.srt = os.path.join(cls.dir, "字幕 文件.srt"); shutil.copy(DEMO_SRT, cls.srt)
        cls.pdf = os.path.join(cls.dir, "课件 一.pdf"); shutil.copy(DEMO_PDF, cls.pdf)

    def new(self, mode, **inputs):
        j = jobs.create({"mode": mode})
        def fn(x):
            for k, v in inputs.items():
                x["inputs"][k] = [jobs.describe_input(p) for p in v] if k == "slides" else jobs.describe_input(v)
        jobs.update(j["id"], fn)
        return j["id"]

    def test_subtitle_mode_skips_transcription_and_model(self):
        jid = self.new("subtitle", subtitle=self.srt, slides=[self.pdf])
        self.assertNotIn("transcribe", jobs.pipeline(jobs.load(jid))); self.assertNotIn("model", jobs.pipeline(jobs.load(jid)))
        self.runner.enqueue(jid); j = wait_job(jid)
        self.assertEqual(j["state"], "done", j["stages"])
        reg = sources.load(jobs.job_dir(jid))
        self.assertTrue(reg["segments"]); self.assertEqual(len(reg["decks"][0]["pages"]), 6)
        ev = server.evidence(j, "S1"); self.assertIsNone(ev["video"])   # 没有视频:不给播放链接
        self.assertTrue(os.path.exists(os.path.join(jobs.job_dir(jid), "work", "lecture.grounded.md")))

    def test_slides_only(self):
        if not pdftext.backend(): self.skipTest("没有 PDF 文字提取工具")
        jid = self.new("slides", slides=[self.pdf])
        self.runner.enqueue(jid); j = wait_job(jid)
        self.assertEqual(j["state"], "done", j["stages"])
        text = open(os.path.join(jobs.job_dir(jid), "ai", "material.md"), encoding="utf-8").read()
        self.assertNotRegex(text, r"\[S\d+|\[F\d+"); self.assertIn("[P1-6]", text)

    def test_scanned_pdf_slides_only_fails_clearly(self):
        if not pdftext.backend(): self.skipTest("没有 PDF 文字提取工具")
        from PIL import Image
        scan = os.path.join(self.dir, "扫描.pdf"); Image.new("RGB", (400, 300), "white").save(scan)
        jid = self.new("slides", slides=[scan])
        self.runner.enqueue(jid); j = wait_job(jid)
        self.assertEqual(j["state"], "failed")
        err = j["stages"]["slides"]["error"]
        self.assertIn("没有可提取的文字", err["what"]); self.assertTrue(err["next"])
        self.assertFalse(os.path.exists(os.path.join(jobs.job_dir(jid), "ai", "material.md")))   # 不静默生成空材料

    def test_retry_only_reruns_failed_stage_and_input_change_invalidates(self):
        jid = self.new("subtitle", subtitle=self.srt)
        calls = {"subtitle": 0, "sources": 0}
        orig = dict(jobs.HANDLERS)
        def sub(job, ctx): calls["subtitle"] += 1; orig["subtitle"](job, ctx)
        state = {"fail": True}
        def src(job, ctx):
            calls["sources"] += 1
            if state["fail"]: raise jobs.StageError("模拟失败", "重试")
            orig["sources"](job, ctx)
        jobs.HANDLERS.update(subtitle=sub, sources=src)
        try:
            self.runner.enqueue(jid); j = wait_job(jid)
            self.assertEqual(j["state"], "failed"); self.assertIn("已保存:读取字幕", j["stages"]["sources"]["error"]["saved"])
            state["fail"] = False
            self.runner.enqueue(jid); j = wait_job(jid)
            self.assertEqual(j["state"], "done"); self.assertEqual(calls, {"subtitle": 1, "sources": 2})
            self.runner.enqueue(jid); wait_job(jid)
            self.assertEqual(calls, {"subtitle": 1, "sources": 2})         # 全部命中缓存
            # 字幕文件内容变了 → 指纹变 → 读取字幕及其后续重做
            with open(self.srt, "a", encoding="utf-8") as f: f.write("\n99\n00:01:50,000 --> 00:01:51,000\nextra line\n")
            jobs.update(jid, lambda x: x["inputs"].__setitem__("subtitle", jobs.describe_input(self.srt)))
            self.runner.enqueue(jid); wait_job(jid)
            self.assertEqual(calls, {"subtitle": 2, "sources": 3})
            # 只改笔记档位不影响 AI 材料之前的步骤
            jobs.update(jid, lambda x: x.__setitem__("template", "concise"))
            self.runner.enqueue(jid); wait_job(jid)
            self.assertEqual(calls, {"subtitle": 2, "sources": 3})
        finally:
            jobs.HANDLERS.update(orig); shutil.copy(DEMO_SRT, self.srt)

    def test_recover_marks_interrupted(self):
        jid = self.new("subtitle", subtitle=self.srt)
        def fn(j):
            j["state"] = "running"; j["stages"]["subtitle"] = {"status": "done", "fp": "x"}; j["stages"]["sources"] = {"status": "running"}
        jobs.update(jid, fn)
        os.makedirs(os.path.join(jobs.job_dir(jid), "work", ".partial-frames"))
        jobs.recover_on_start()
        j = jobs.load(jid)
        self.assertEqual(j["state"], "interrupted"); self.assertEqual(j["stages"]["sources"]["status"], "interrupted")
        self.assertEqual(j["stages"]["subtitle"]["status"], "done")
        self.assertFalse(os.path.exists(os.path.join(jobs.job_dir(jid), "work", ".partial-frames")))

class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        server.TOKEN = "testtoken"; server.RUNNER = jobs.Runner()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        server.PORT = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.httpd.shutdown()
    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", server.PORT, timeout=5)
        h = {"Host": f"127.0.0.1:{server.PORT}"}; h.update(headers or {})
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse(); data = r.read(); c.close()
        return r.status, r.headers, data
    def test_access_control(self):
        self.assertEqual(self.req("GET", "/api/state")[0], 401)
        ck = {"Cookie": "lsk_s=testtoken"}
        self.assertEqual(self.req("GET", "/api/state", headers=ck)[0], 200)
        self.assertEqual(self.req("GET", "/api/state", headers=dict(ck, Host="attacker.example:80"))[0], 403)
        self.assertEqual(self.req("POST", "/api/jobs", {"mode": "slides"}, dict(ck, Origin="http://evil.example"))[0], 403)
        st, hd, _ = self.req("GET", "/auth?t=testtoken")
        self.assertEqual(st, 303); self.assertIn("HttpOnly", hd["Set-Cookie"]); self.assertIn("SameSite=Strict", hd["Set-Cookie"])
        self.assertEqual(self.req("GET", "/auth?t=wrong")[0], 401)
        st, hd, _ = self.req("GET", "/", headers=ck)
        self.assertIn("script-src 'self'", hd["Content-Security-Policy"])
    def test_file_access_is_restricted(self):
        ck = {"Cookie": "lsk_s=testtoken"}
        st, _, body = self.req("POST", "/api/jobs", {"mode": "slides"}, ck); jid = json.loads(body)["id"]
        self.assertEqual(self.req("GET", f"/files/{jid}/frame/..%2F..%2Fjob.json", headers=ck)[0], 400)
        self.assertEqual(self.req("GET", "/static/../server.py", headers=ck)[0], 404)
        self.assertEqual(self.req("GET", f"/files/{jid}/video", headers=ck)[0], 404)
        self.assertEqual(self.req("GET", "/files/..%2F..%2Fetc/video", headers=ck)[0], 404)

if __name__ == "__main__":
    unittest.main()

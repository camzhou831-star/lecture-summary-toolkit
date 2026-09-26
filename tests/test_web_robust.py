#!/usr/bin/env python3
"""网页工作台的可靠性测试(整改轮):指纹、缓存失效矩阵、旧版本笔记不被新规则覆盖、损坏产物不被复用、原文件移动/替换、
删除与并发、视频 Range、模型下载(完整/中断续传/不支持续传/校验失败)。不需要 whisper/tesseract/网络。"""
import hashlib, http.client, http.server, json, os, shutil, sys, tempfile, threading, time, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEMO = os.path.join(ROOT, "examples", "demo")
DEMO_SRT = os.path.join(DEMO, "课程视频", "DEMO1001 - 01 Jan 26-s1-demo.srt")
DEMO_PDF = os.path.join(DEMO, "课件", "DEMO1001", "DEMO1001-testing-loops.pdf")

_tmp = tempfile.mkdtemp(prefix="lsk-robust-")
os.environ["LSK_DATA"] = os.path.join(_tmp, "data")
os.environ["WHISPER_MODEL_DIR"] = os.path.join(_tmp, "models")       # 隔离目录,不碰真实模型
from web import jobs, server, util, models, courses, sources  # noqa: E402

def tearDownModule():
    shutil.rmtree(_tmp, ignore_errors=True)

def wait_job(jid, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = jobs.load(jid)
        if j["state"] not in ("queued", "running"): return j
        time.sleep(0.05)
    raise AssertionError("任务没有结束")

class Fingerprint(unittest.TestCase):
    def test_small_file_full_hash_sees_middle_change(self):
        p = os.path.join(_tmp, "a.srt")
        data = bytearray(b"x" * (3 << 20)); open(p, "wb").write(data)
        st = os.stat(p); f1 = util.file_fingerprint(p)
        data[len(data) // 2] = ord("y"); open(p, "wb").write(data); os.utime(p, (st.st_atime, st.st_mtime))
        self.assertNotEqual(f1, util.file_fingerprint(p))            # 同大小、同修改时间、只改中间 1 字节
    def test_moved_file_same_fingerprint(self):
        p = os.path.join(_tmp, "b.srt"); shutil.copy(DEMO_SRT, p); f1 = util.file_fingerprint(p)
        q = os.path.join(_tmp, "移动后 的.srt"); shutil.move(p, q); os.utime(q, None)
        self.assertEqual(f1, util.file_fingerprint(q))                 # 不看修改时间:移动/复制后仍认得
    def test_large_file_sampled(self):
        p = os.path.join(_tmp, "big.mp4")
        with open(p, "wb") as f: f.truncate(80 << 20)
        f1 = util.file_fingerprint(p); self.assertTrue(f1.startswith("s"))
        with open(p, "r+b") as f: f.seek((80 << 20) * 5 // 33 + 10); f.write(b"changed")
        self.assertNotEqual(f1, util.file_fingerprint(p))             # 改在采样块里:能识别(改在未采样处识别不了,见文档)

class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = jobs.Runner()
        cls.dir = tempfile.mkdtemp(dir=_tmp)
    def srt_copy(self, name="字幕 文件.srt"):
        p = os.path.join(self.dir, name); shutil.copy(DEMO_SRT, p); return p
    def new(self, mode, **inputs):
        j = jobs.create({"mode": mode})
        def fn(x):
            for k, v in inputs.items():
                x["inputs"][k] = [jobs.describe_input(p) for p in v] if k == "slides" else jobs.describe_input(v)
        jobs.update(j["id"], fn); return j["id"]
    def run_counted(self, jid):
        """跑一次,返回这次真正执行了哪些阶段"""
        ran = []
        orig = dict(jobs.HANDLERS)
        def wrap(name):
            def f(job, ctx): ran.append(name); orig[name](job, ctx)
            return f
        jobs.HANDLERS.update({k: wrap(k) for k in orig})
        try:
            self.runner.enqueue(jid); j = wait_job(jid)
        finally:
            jobs.HANDLERS.update(orig)
        self.assertEqual(j["state"], "done", j["stages"])
        return ran

class Invalidation(Base):
    def test_matrix(self):
        srt = self.srt_copy(); pdf = os.path.join(self.dir, "课件.pdf"); shutil.copy(DEMO_PDF, pdf)
        cid, _ = courses.upsert(None, {"name": "测试课"})
        jid = self.new("subtitle", subtitle=srt, slides=[pdf]); jobs.update(jid, lambda j: j.__setitem__("course_id", cid))
        self.assertEqual(self.run_counted(jid), ["subtitle", "slides", "sources", "material"])
        self.assertEqual(self.run_counted(jid), [])                                   # 全部复用
        jd = jobs.job_dir(jid); job = jobs.load(jid)
        p_before = server.materials.prompt_upload(jobs.material_meta(job), job["mode"], job["template"])
        jobs.update(jid, lambda j: (j.__setitem__("template", "concise"), j.__setitem__("note_lang", "en")))
        self.assertEqual(self.run_counted(jid), [])                                   # 档位/笔记语言:不重做任何处理阶段
        job = jobs.load(jid)
        p_after = server.materials.prompt_upload(jobs.material_meta(job), job["mode"], job["template"])
        self.assertNotEqual(p_before, p_after); self.assertIn("## 待复习问题", p_after); self.assertIn("用英文写", p_after)
        jobs.update(jid, lambda j: j["options"].__setitem__("chunk_chars", 9000))
        self.assertEqual(self.run_counted(jid), ["material"])                          # 分块大小:只重做材料
        courses.upsert(cid, {"glossary": ["prime path"]})
        self.assertEqual(self.run_counted(jid), ["material"])                          # 术语:进材料,不重读字幕
        self.assertIn("prime path", open(os.path.join(jd, "ai", "material.md"), encoding="utf-8").read())
        with open(srt, "a", encoding="utf-8") as f: f.write("\n99\n00:01:50,000 --> 00:01:51,000\nextra\n")
        jobs.update(jid, lambda j: j["inputs"].__setitem__("subtitle", jobs.describe_input(srt)))
        self.assertEqual(self.run_counted(jid), ["subtitle", "sources", "material"])  # 字幕变了:课件读取复用
        shutil.copy(DEMO_SRT, srt)

    def test_old_version_keeps_its_rules_and_sources(self):
        jid = self.new("subtitle", subtitle=self.srt_copy("v.srt"))
        self.run_counted(jid)
        jobs.update(jid, lambda j: j.__setitem__("template", "concise"))
        import web.templates as T
        body = "\n".join(f"{t}\n内容 [S1]" for t in T.section_titles("concise", "video"))
        text = f"【LSK 笔记 job={jid}】\n# 标题\n{body}\n【LSK 结束】"
        job = jobs.load(jid)
        # 模拟 POST /summary 的保存逻辑
        ent = {"v": 1, "file": "summary-v1.md", "created": util.now(), "template": "concise", "mode": "subtitle",
               "material_fp": job["material"]["fp"], "rules": server.CHECK_RULES}
        util.atomic_write_text(os.path.join(jobs.job_dir(jid), "ai", "summary-v1.md"), text)
        jobs.update(jid, lambda j: j["ai"]["versions"].append(ent))
        jobs.update(jid, lambda j: (j.__setitem__("template", "full"), j.__setitem__("title", "改过的标题")))
        self.run_counted(jid)                                                           # 材料内容变了,重新生成
        pl = server.summary_payload(jobs.load(jid), 1)
        self.assertFalse([i for i in pl["issues"] if i["level"] == "error"], pl["issues"])   # 仍按简明版检查,不因切到完整版而报缺小节
        self.assertTrue(pl["stale_material"]); self.assertEqual(pl["template_name"], "简明版")
        self.assertTrue(os.path.exists(os.path.join(jobs.job_dir(jid), "ai", "summary-v1.md")))

class CorruptOutputs(Base):
    def test_broken_outputs_are_redone(self):
        jid = self.new("subtitle", subtitle=self.srt_copy("c.srt"))
        self.run_counted(jid); jd = jobs.job_dir(jid)
        open(os.path.join(jd, "work", "lecture.srt"), "w").close()                      # 空文件
        self.assertIn("subtitle", self.run_counted(jid))
        open(os.path.join(jd, "sources.json"), "w").write('{"mode": "subtitle", "segm')  # 半截 JSON
        self.assertEqual(self.run_counted(jid)[:1], ["sources"])
        p = os.path.join(jd, "ai", "material.md"); t = open(p, encoding="utf-8").read()
        open(p, "w", encoding="utf-8").write(t[: len(t) // 2])                          # 材料被截断
        self.assertEqual(self.run_counted(jid), ["material"])
        open(os.path.join(jd, "work", "lecture.srt"), "w").write("1\nnot a time\ntext\n")  # 能打开但没有有效条目
        self.assertIn("subtitle", self.run_counted(jid))

class Originals(Base):
    def test_moved_missing_and_replaced(self):
        srt = self.srt_copy("orig.srt")
        jid = self.new("subtitle", subtitle=srt); self.run_counted(jid)
        moved = os.path.join(self.dir, "新位置 字幕.srt"); shutil.move(srt, moved)
        v = server.job_view(jobs.load(jid)); self.assertFalse(v["inputs"]["subtitle"]["exists"])
        # 历史结果仍可查看
        self.assertTrue(sources.load(jobs.job_dir(jid))["segments"])
        # 重新定位到同内容的文件:不重做
        r = server.set_input(jid, "subtitle", moved)
        self.assertEqual(r["relocate"], "same"); self.assertEqual(self.run_counted(jid), [])
        # 换成内容不同的文件:提示并重做
        other = os.path.join(self.dir, "other.srt")
        open(other, "w", encoding="utf-8").write("1\n00:00:01,000 --> 00:00:02,000\ndifferent lecture\n")
        r = server.set_input(jid, "subtitle", other)
        self.assertEqual(r["relocate"], "different"); self.assertIn("subtitle", self.run_counted(jid))

    def test_delete_keeps_originals_and_does_not_resurrect(self):
        srt = self.srt_copy("keep.srt"); jid = self.new("subtitle", subtitle=srt); self.run_counted(jid)
        jd = jobs.job_dir(jid)
        self.assertTrue(jobs.delete(jid))
        self.assertFalse(os.path.exists(jd)); self.assertTrue(os.path.exists(srt))
        with self.assertRaises(jobs.JobGone): jobs.update(jid, lambda j: j.__setitem__("state", "done"))
        self.assertFalse(os.path.exists(jd))                                            # 后台线程晚到的写入不会重建目录

    def test_cannot_delete_running_and_single_enqueue(self):
        jid = self.new("subtitle", subtitle=self.srt_copy("q.srt"))
        gate = threading.Event()
        orig = jobs.HANDLERS["subtitle"]
        jobs.HANDLERS["subtitle"] = lambda job, ctx: (gate.wait(5), orig(job, ctx))
        try:
            results = []
            def start():
                try: self.runner.enqueue(jid); results.append("ok")
                except jobs.AlreadyQueued: results.append("dup")
            ts = [threading.Thread(target=start) for _ in range(5)]
            for t in ts: t.start()
            for t in ts: t.join()
            self.assertEqual(sorted(results), ["dup"] * 4 + ["ok"])                      # 并发 5 次「开始」只排队 1 次
            time.sleep(0.2)
            self.assertFalse(jobs.delete(jid))                                           # 处理中不能删
        finally:
            gate.set(); wait_job(jid); jobs.HANDLERS["subtitle"] = orig

class HttpRange(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        server.TOKEN = "tok"; server.RUNNER = jobs.Runner()
        cls.httpd = server.Server(("127.0.0.1", 0), server.Handler)
        server.PORT = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.video = os.path.join(_tmp, "测试 视频.mp4")
        cls.data = os.urandom(3_000_000); open(cls.video, "wb").write(cls.data)
        j = jobs.create({"mode": "video"}); cls.jid = j["id"]
        jobs.update(cls.jid, lambda x: x["inputs"].__setitem__("video", jobs.describe_input(cls.video)))
    @classmethod
    def tearDownClass(cls): cls.httpd.shutdown()
    def get(self, path, headers=None, read=True):
        c = http.client.HTTPConnection("127.0.0.1", server.PORT, timeout=5)
        h = {"Host": f"127.0.0.1:{server.PORT}", "Cookie": "lsk_s=tok"}; h.update(headers or {})
        c.request("GET", path, headers=h); r = c.getresponse()
        return r.status, r.headers, (r.read() if read else r), c
    def test_ranges(self):
        n = len(self.data); u = f"/files/{self.jid}/video"
        st, hd, b, _ = self.get(u, {"Range": "bytes=100-199"}); self.assertEqual((st, b), (206, self.data[100:200])); self.assertEqual(hd["Content-Range"], f"bytes 100-199/{n}")
        st, hd, b, _ = self.get(u, {"Range": "bytes=2999000-"}); self.assertEqual((st, b), (206, self.data[2999000:]))
        st, hd, b, _ = self.get(u, {"Range": "bytes=-500"}); self.assertEqual((st, b), (206, self.data[-500:]))
        st, hd, b, _ = self.get(u, {"Range": f"bytes=0-{n + 999}"}); self.assertEqual((st, len(b)), (206, n))    # 终点超出:截到文件尾
        st, hd, b, _ = self.get(u, {"Range": f"bytes={n}-"}); self.assertEqual(st, 416); self.assertEqual(hd["Content-Range"], f"bytes */{n}")
        st, hd, b, _ = self.get(u, {"Range": "bytes=500-100"}); self.assertEqual((st, len(b)), (200, n))       # 无效区间:忽略 Range
        st, hd, b, _ = self.get(u, {"Range": "bytes=0-1,5-9"}); self.assertEqual((st, len(b)), (200, n))       # 多段:不支持,整段返回
        st, hd, b, _ = self.get(u, {"Range": "items=0-1"}); self.assertEqual(st, 200)
        st, hd, b, _ = self.get(u); self.assertEqual((st, b), (200, self.data))
    def test_api_responsive_while_video_streams(self):
        st, hd, resp, conn = self.get(f"/files/{self.jid}/video", read=False)
        resp.read(1000)                                             # 视频连接保持未读完
        t0 = time.time(); st2, _, b, _ = self.get("/api/state"); dt = time.time() - t0
        self.assertEqual(st2, 200); self.assertLess(dt, 2)
        st3, _, _, _ = self.get(f"/api/jobs/{self.jid}"); self.assertEqual(st3, 200)
        conn.close()

class _ModelServer(http.server.BaseHTTPRequestHandler):
    payload = b""; ranges = True; cut_at = None; sha = None
    def log_message(self, *a): pass
    def do_GET(self):
        data, start = self.payload, 0
        rng = self.headers.get("Range")
        if rng and self.ranges:
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(data): self.send_response(416); self.end_headers(); return
            self.send_response(206); self.send_header("Content-Range", f"bytes {start}-{len(data)-1}/{len(data)}")
        else: self.send_response(200)
        body = data[start:]
        self.send_header("Content-Length", str(len(body)))
        if self.sha: self.send_header("X-Linked-Etag", f'"{self.sha}"')
        self.end_headers()
        if self.cut_at is not None and start == 0:
            self.wfile.write(body[: self.cut_at]); self.wfile.flush(); self.connection.close(); return
        self.wfile.write(body)

class ModelDownload(unittest.TestCase):
    def setUp(self):
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ModelServer)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/m.bin"
        self.dest = os.path.join(_tmp, "models", f"m-{time.time_ns()}.bin"); os.makedirs(os.path.dirname(self.dest), exist_ok=True)
        _ModelServer.payload = os.urandom(3_500_000); _ModelServer.ranges = True; _ModelServer.cut_at = None
        _ModelServer.sha = hashlib.sha256(_ModelServer.payload).hexdigest()
    def tearDown(self): self.srv.shutdown()
    def dl(self): models._download(self.url, self.dest, "测试模型", lambda *a: None, lambda *a: None)
    def test_full(self):
        self.dl(); self.assertEqual(open(self.dest, "rb").read(), _ModelServer.payload)
        self.assertEqual(json.load(open(self.dest + ".lsk.json"))["verified"], "sha256")
    def test_interrupted_then_resumed(self):
        _ModelServer.cut_at = 1_000_000
        with self.assertRaises(models.DownloadError): self.dl()
        self.assertFalse(os.path.exists(self.dest)); self.assertEqual(os.path.getsize(self.dest + ".part"), 1_000_000)
        _ModelServer.cut_at = None
        self.dl(); self.assertEqual(open(self.dest, "rb").read(), _ModelServer.payload)
    def test_server_without_range_restarts(self):
        _ModelServer.cut_at = 1_000_000
        with self.assertRaises(models.DownloadError): self.dl()
        _ModelServer.cut_at = None; _ModelServer.ranges = False
        self.dl(); self.assertEqual(open(self.dest, "rb").read(), _ModelServer.payload)
    def test_corrupt_is_rejected(self):
        _ModelServer.sha = "0" * 64
        with self.assertRaises(models.DownloadError): self.dl()
        self.assertFalse(os.path.exists(self.dest)); self.assertFalse(os.path.exists(self.dest + ".part"))
    def test_present_rejects_truncated(self):
        name = "tiny.en"; p = models.model_path(name); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(b"x" * 2_000_000)
        util.atomic_write_json(p + ".lsk.json", {"size": 3_000_000})
        self.assertFalse(models.present(name))                    # 有校验记录:大小不符就不可用
        os.remove(p + ".lsk.json")
        self.assertFalse(models.present(name))                    # 无记录:明显小于预估大小也不可用
        os.remove(p)

class OcrMergeRuleA(unittest.TestCase):
    """工具栏页码相同但画面是盖在课件上的编辑器(现场写代码)时,不能被合并掉(DEMO1001 26 Aug 5712s 的真实案例)"""
    def test_editor_over_same_page_is_kept(self):
        import subprocess
        from PIL import Image
        d = tempfile.mkdtemp(dir=_tmp)
        slide = "Graph-based testing criteria node coverage edge coverage edge-pair coverage loop coverage heuristic"
        editor = "if len myarray and or not isAlpha isEven for int i less than ninety nine"
        rows = [("t00100s.jpg", 100, slide), ("t00112s.jpg", 112, editor), ("t00124s.jpg", 124, editor + " for int i")]
        for f, t, _ in rows: Image.new("RGB", (8, 8)).save(os.path.join(d, f))
        json.dump([{"file": f, "t": t, "page": 16, "pages": 20, "text": x, "chars": len(x)} for f, t, x in rows],
                  open(os.path.join(d, "ocr.json"), "w"))
        r = subprocess.run([sys.executable, os.path.join(ROOT, "工具", "ocr_frames.py"), d], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        kept = [e["file"] for e in json.load(open(os.path.join(d, "ocr.json")))]
        self.assertIn("t00100s.jpg", kept)                  # 课件页保留
        self.assertIn("t00124s.jpg", kept)                  # 编辑器的最新状态保留(112s 被 124s 包含,按规则 B 删掉)
        self.assertNotIn("t00112s.jpg", kept)

if __name__ == "__main__":
    unittest.main()

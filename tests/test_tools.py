#!/usr/bin/env python3
"""单元测试:不需要 whisper/tesseract/网络,只用合成数据。运行: python3 -m unittest discover -s tests -v
覆盖:course_meta 文件名与周次、compact 幻觉过滤与时间标签、check_summary 三类错误、add_links 幂等与路径别名、
     build_bundle 空档检测(含 VAD 填充段)、dedup_frames 严格去重、ocr_frames 页码模式、match_slides 词匹配、exam_bank 跨周考点库、cam_frames 手写帧挑选与 check_summary 的 cam/ 路径、
     双端一致性(AGENTS.md 由 SKILL 生成、CLAUDE.md 导入目标存在、技能 frontmatter)。"""
import json, os, re, shutil, subprocess, sys, tempfile, unittest, importlib.util
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "工具")
sys.path.insert(0, TOOLS)

def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(TOOLS, name + ".py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def run(cmd, env=None, cwd=None):
    e = dict(os.environ); e.update(env or {})
    return subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=cwd)

class CourseMeta(unittest.TestCase):
    def setUp(self):
        self.m = load("course_meta")
        self.cfg = {"year": 2026, "semester_start": "2026-07-20", "break_weeks_after": [6], "units": {"DEMO1001": {"alias": "1002"}}}
    def test_uwa_lms_name(self):
        r = self.m.parse("DEMO1001 - 26 Aug 20-s1-full.mp4", self.cfg)
        self.assertEqual((r["unit"], r["alias"], r["date"], r["week"]), ("DEMO1001", "1002", "2026-08-26", 6))
        self.assertEqual(r["notes_path"], os.path.join("总结", "1002", "DEMO1001 - 26 Aug 20-s1-full.md"))
    def test_week_after_break(self):
        self.assertEqual(self.m.parse("DEMO1001 - 09 Sep 20-s1-full.mp4", self.cfg)["week"], 7)
        self.assertEqual(self.m.parse("DEMO1001 - 22 Jul 20-s1-full.mp4", self.cfg)["week"], 1)
    def test_iso_name_year_from_filename(self):
        r = self.m.parse("DEMO1004_2025-03-05_lecture.mp4", self.cfg)
        self.assertEqual((r["date"], r["year_source"]), ("2025-03-05", "文件名"))
    def test_year_fallback_is_flagged(self):
        r = self.m.parse("DEMO1001 - 26 Aug 20-s1-full.mp4", {})
        self.assertIn("未确认", r["year_source"])
    def test_unknown_name(self):
        self.assertIsNone(self.m.parse("random.mp4", self.cfg))
    def test_multiple_breaks(self):
        cfg = dict(self.cfg); cfg["break_weeks_after"] = [6, 9]
        got = {n: self.m.parse(f"DEMO1001 - {n} 20-s1-full.mp4", cfg) for n in ["26 Aug", "02 Sep", "09 Sep", "23 Sep", "30 Sep", "07 Oct"]}
        self.assertEqual([got[n]["week"] for n in got], [6, None, 7, 9, None, 10])
        self.assertTrue(got["02 Sep"]["in_break"] and got["30 Sep"]["in_break"])
    def test_cross_year_semester(self):
        cfg = {"year": 2025, "semester_start": "2025-12-29"}
        r1 = self.m.parse("DEMO1001 - 30 Dec 26-s1.mp4", cfg); r2 = self.m.parse("DEMO1001 - 06 Jan 26-s1.mp4", cfg)
        self.assertEqual((r1["date"], r1["week"]), ("2025-12-30", 1))
        self.assertEqual((r2["date"], r2["week"]), ("2026-01-06", 2)); self.assertIn("调整为 2026", r2["year_source"])
    def test_non_monday_start_warns(self):
        r = self.m.parse("DEMO1001 - 26 Aug 20-s1-full.mp4", {"year": 2026, "semester_start": "2026-07-21"})
        self.assertTrue(any("不是周一" in w for w in r["warnings"]))
    def test_custom_pattern(self):
        cfg = dict(self.cfg); cfg["filename_patterns"] = [r"^Week(?P<week_ignored>\d+)_(?P<unit>[A-Z]{4}\d{4})_(?P<day>\d{2})(?P<mon>[A-Z][a-z]{2})"]
        r = self.m.parse("Week3_DEMO1001_05Aug.mp4", cfg)
        self.assertEqual(r["date"], "2026-08-05")

class Compact(unittest.TestCase):
    def test_filter_and_labels(self):
        with tempfile.TemporaryDirectory() as d:
            srt = os.path.join(d, "a.srt")
            open(srt, "w").write("1\n00:00:01,000 --> 00:00:03,000\n<i>Thank you.</i>\n\n"
                                 "00:00:04,000 --> 00:00:06,000\nWe'll start again at, uh, six minutes.\n\n"
                                 "3\n00:00:07,000 --> 00:00:09,000\nWe'll start again at graph theory.\n\n"
                                 "4\n00:00:10,000 --> 00:00:12,000\nRepeated content.\n\n5\n00:00:13,000 --> 00:00:15,000\nrepeated content\n\n"
                                 "6\n01:41:00,000 --> 01:41:02,000\nlate line\n")
            r = run(["bash", os.path.join(TOOLS, "compact.sh"), srt]); self.assertEqual(r.returncode, 0, r.stderr)
            out = open(os.path.join(d, "a.compact.txt")).read().splitlines()
            self.assertEqual(out, ["[00:00] We'll start again at graph theory. Repeated content.", "[01:41] late line"])

class CheckSummary(unittest.TestCase):
    def _write(self, d, body):
        os.makedirs(os.path.join(d, "课程视频"), exist_ok=True); os.makedirs(os.path.join(d, "总结", "X"), exist_ok=True)
        open(os.path.join(d, "课程视频", "DEMO1001 - 26 Aug 20-s1-full.srt"), "w").write("1\n00:00:05,000 --> 00:10:00,000\nhello\n")
        p = os.path.join(d, "总结", "X", "DEMO1001 - 26 Aug 20-s1-full.md"); open(p, "w").write(body); return p
    def test_detects_three_problem_classes(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "# DEMO1001 第一周(2026-08-26)— x\n## 一句话概括\n## 核心要点\n见 t99999s.jpg\n## 章节时间线\n- [200:00] bad\n- [12:99] bad2\n## 复习卡\n")
            r = run(["python3", os.path.join(TOOLS, "check_summary.py"), p], env={"COURSE_ROOT": d})
            self.assertEqual(r.returncode, 1)
            for needle in ["超出视频时长", "秒数不合法", "引用的截图不存在", "缺少小节 ## 金句"]: self.assertIn(needle, r.stdout)
    def test_date_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "# DEMO1001 第一周(2026-08-19)— x\n## 一句话概括\n## 核心要点\n## 章节时间线\n- [01:00] ok\n## 金句 / 考点信号\n## 复习卡\n")
            r = run(["python3", os.path.join(TOOLS, "check_summary.py"), p], env={"COURSE_ROOT": d})
            self.assertIn("与文件名日期", r.stdout)
    def test_passes(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "# DEMO1001 第一周(2026-08-26)— x\n## ⚠️ 课程通知\n无\n## 一句话概括\n## 核心要点\n## 章节时间线\n- [01:00] ok\n## 金句 / 考点信号\n## 复习卡\n- q::a\n")
            r = run(["python3", os.path.join(TOOLS, "check_summary.py"), p], env={"COURSE_ROOT": d})
            self.assertEqual(r.returncode, 0, r.stdout)

class AddLinks(unittest.TestCase):
    def test_idempotent_and_strict(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "课程视频")); os.makedirs(os.path.join(d, "总结", "X"))
            open(os.path.join(d, "课程视频", "DEMO1001 - x.mp4"), "w").close()
            p = os.path.join(d, "总结", "X", "DEMO1001 - x.md")
            open(p, "w").write("## 核心要点\n- [03:00] not here\n## 章节时间线\n- [01:00] a\n  - [02:00] nested\n")
            for _ in range(2): run(["python3", os.path.join(TOOLS, "add_links.py"), p], env={"COURSE_ROOT": d})
            s = open(p).read()
            self.assertEqual(s.count("#t="), 1); self.assertIn("(<../../课程视频/DEMO1001 - x.mp4#t=60>)", s)

class BuildBundle(unittest.TestCase):
    def _bundle(self, srt_text):
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "课程视频"))
        srt = os.path.join(d, "课程视频", "X - clip.srt"); open(srt, "w").write(srt_text)
        r = run(["python3", os.path.join(TOOLS, "build_bundle.py"), srt, "--frames-dir", os.path.join(d, "none")], env={"COURSE_ROOT": d})
        self.assertEqual(r.returncode, 0, r.stderr)
        return open(os.path.join(d, "课程视频", "X - clip.grounded.md")).read(), json.load(open(os.path.join(d, "课程视频", "X - clip.bundle.json")))
    def test_gap_and_vad_padding(self):
        # 第 2 段被 VAD 拉长到 250 秒但只有 2 个词 -> 真实结束按 start+3 算,空档应被标出
        g, b = self._bundle("1\n00:00:00,000 --> 00:00:05,000\nhello there\n\n2\n00:00:10,000 --> 00:04:20,000\nOokie doke.\n\n3\n00:04:25,000 --> 00:04:30,000\nback\n")
        self.assertIn("⏸", g); self.assertIn("无语音", g); self.assertAlmostEqual(b["duration"], 270, delta=1)
    def test_no_false_gap(self):
        g, _ = self._bundle("1\n00:00:00,000 --> 00:00:05,000\nhello\n\n2\n00:02:50,000 --> 00:03:00,000\nback after 165s\n")
        self.assertNotIn("⏸", g)
    def test_unsorted_and_empty(self):
        g, b = self._bundle("1\n00:05:00,000 --> 00:05:05,000\nlate\n\n2\n00:00:00,000 --> 00:00:05,000\nearly\n")
        self.assertEqual(b["segments"][0]["text"], "early")
        d = tempfile.mkdtemp(); srt = os.path.join(d, "bad.srt"); open(srt, "w").write("no times\n")
        self.assertNotEqual(run(["python3", os.path.join(TOOLS, "build_bundle.py"), srt]).returncode, 0)

class Frames(unittest.TestCase):
    def test_dedup_only_identical(self):
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as d:
            def slide(name, text):
                im = Image.new("RGB", (640, 360), "white"); ImageDraw.Draw(im).text((40, 40), text, fill="black"); im.save(os.path.join(d, name))
            slide("t00000s.jpg", "Slide one about loops"); slide("t00012s.jpg", "Slide one about loops")
            slide("t00024s.jpg", "Slide two about prime paths and a lot more text here")
            r = run(["python3", os.path.join(TOOLS, "dedup_frames.py"), d]); self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(sorted(f for f in os.listdir(d) if f.endswith(".jpg")), ["t00012s.jpg", "t00024s.jpg"])
    def test_page_patterns(self):
        m = load("ocr_frames")
        self.assertEqual(m.find_page("Browse Text Selection 12 of 20 Zoom"), (12, 20))
        self.assertEqual(m.find_page("Page 3 of 9"), (3, 9))
        self.assertEqual(m.find_page("footer 7 / 50"), (7, 50))
        self.assertEqual(m.find_page("no page here"), (None, None))
        self.assertEqual(m.find_page("50 of 20"), (None, None))
    def test_match_words(self):
        m = load("match_slides")
        self.assertEqual(m.words("The prime path, and the LOOP body!"), {"prime", "path", "loop", "body"})
        self.assertEqual(m.words("What has been covered until now?"), {"covered"})   # 泛用词全是停用词,这种帧不该配上任何页
    def test_deck_common(self):
        m = load("match_slides")
        hdr = {"demo1004", "systems", "programming"}
        decks = {"a": [hdr | {"arrays"}, hdr | {"pointers"}, hdr | {"files"}], "b": [hdr | {"malloc"}, {"orphan"}]}
        self.assertEqual(m.deck_common(decks), hdr)                 # 5 页里出现 4 次的页眉词
        self.assertEqual(m.deck_common({"a": [hdr, hdr]}), set())   # 页数太少不启用
    @unittest.skipUnless(shutil.which("pdftotext"), "需要 poppler")
    def test_match_preserves_toolbar_and_clear(self):
        with tempfile.TemporaryDirectory() as d:
            # 两页文字 PDF(手写 PDF 语法)
            def pdf(path, texts):
                objs = []; add = lambda o: (objs.append(o), len(objs))[1]
                font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"); pages_idx = add(b"P"); ids = []
                for t in texts:
                    c = ("BT /F1 20 Tf 50 700 Td (" + t + ") Tj ET").encode(); cid = add(b"<< /Length %d >>\nstream\n" % len(c) + c + b"\nendstream")
                    ids.append(add(("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 800 800] /Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>" % (pages_idx, cid, font)).encode()))
                objs[pages_idx - 1] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % i for i in ids), len(ids))).encode()
                cat = add(("<< /Type /Catalog /Pages %d 0 R >>" % pages_idx).encode()); out = b"%PDF-1.4\n"; offs = []
                for n, o in enumerate(objs, 1): offs.append(len(out)); out += b"%d 0 obj\n" % n + o + b"\nendobj\n"
                xref = len(out); out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
                out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, xref); open(path, "wb").write(out)
            pdf(os.path.join(d, "deck.pdf"), ["prime paths simple path cannot extend subsumes node edge coverage", "loop body zero once many times fault line coverage"])
            ocr = [{"file": "t00010s.jpg", "t": 10, "page": 7, "pages": 9, "chars": 80, "text": "prime paths: a simple path that cannot be extended; subsumes node and edge coverage"},
                   {"file": "t00020s.jpg", "t": 20, "page": None, "pages": None, "chars": 10, "text": "terminal"}]
            json.dump(ocr, open(os.path.join(d, "ocr.json"), "w"))
            ms = os.path.join(TOOLS, "match_slides.py")
            for _ in range(2): self.assertEqual(run(["python3", ms, d, os.path.join(d, "deck.pdf")]).returncode, 0)
            e = json.load(open(os.path.join(d, "ocr.json")))[0]
            self.assertEqual((e["page"], e["pages"], e["deck"]), (1, 2, "deck")); self.assertEqual(e["toolbar"], {"page": 7, "pages": 9})   # 工具栏值不被 PDF 页码污染
            run(["python3", ms, d, "--clear"]); e = json.load(open(os.path.join(d, "ocr.json")))[0]
            self.assertEqual((e["page"], e["pages"]), (7, 9)); self.assertNotIn("deck", e)

class ExamBank(unittest.TestCase):
    SUMMARY = """# DEMO1001 第六周(2026-08-26)— 逻辑测试

> 主讲:X

## ⚠️ 课程通知(07:08–07:35)

1. 项目 brief 今天发(07:08)。
2. 🎯 **项目不要求写 SQA 计划**(36:00,课件 p30)。

## 一句话概括

x

## 核心要点

1. 略

## 章节时间线

- **[07:08](<../../课程视频/DEMO1001 - 26 Aug 20-s1-full.mp4#t=428>) 通知** — 略

## 金句 / 考点信号

- 🎯 考试题型(73:09):写出满足 RACC 的测试集(lect06a p35–40)。
- 普通金句,没有时间。
  - 子条目并进上一条。

## 复习卡

- RACC 的含义?::其它子句固定时翻转主子句就翻转谓词
- MTBF = ==MTTF + MTTR==
- 这行不是卡片
"""
    def setUp(self):
        self.m = load("exam_bank")
        self.tmp = tempfile.mkdtemp(); self.m.ROOT = self.tmp
        os.makedirs(os.path.join(self.tmp, "总结", "1002")); os.makedirs(os.path.join(self.tmp, "课程视频"))
        open(os.path.join(self.tmp, "课程视频", "DEMO1001 - 26 Aug 20-s1-full.mp4"), "w").close()
        self.f = os.path.join(self.tmp, "总结", "1002", "DEMO1001 - 26 Aug 20-s1-full.md")
        open(self.f, "w", encoding="utf-8").write(self.SUMMARY)
        open(os.path.join(self.tmp, "总结", "1002", "其它笔记.md"), "w", encoding="utf-8").write("# 不是总结\n随便写")
        open(os.path.join(self.tmp, "course.json"), "w").write(json.dumps({"year": 2026, "semester_start": "2026-07-20", "units": {"DEMO1001": {"alias": "1002"}}}))
    def tearDown(self): shutil.rmtree(self.tmp)
    def test_parse(self):
        s = self.m.parse_summary(self.f, {"year": 2026, "semester_start": "2026-07-20"})
        self.assertEqual((s["week"], s["date"], s["topic"]), (6, "2026-08-26", "逻辑测试"))   # 中文数字周次、主题不含日期里的连字符
        it = s["items"]
        self.assertEqual(len(it["notice"]), 2); self.assertTrue(it["notice"][1]["flag"]); self.assertEqual(it["notice"][1]["timestamps"], [2160])
        self.assertEqual(it["notice"][1]["pages"], ["p30"])
        self.assertEqual(len(it["signal"]), 2); self.assertEqual(it["signal"][0]["timestamps"], [73*60+9]); self.assertEqual(it["signal"][0]["pages"], ["lect06a p35–40"])
        self.assertIn("▸ 子条目", it["signal"][1]["text"]); self.assertEqual(it["signal"][1]["timestamps"], [])
        self.assertEqual(len(it["card"]), 2)   # 没有 :: 或 == 的行不算卡
        self.assertIsNone(self.m.parse_summary(os.path.join(self.tmp, "总结", "1002", "其它笔记.md"), {}))
    def test_cli_writes_md_and_json(self):
        r = run(["python3", os.path.join(TOOLS, "exam_bank.py"), "1002"], env={"COURSE_ROOT": self.tmp})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("🎯 2 条", r.stdout)
        out = open(os.path.join(self.tmp, "总结", "1002", "考点库.md"), encoding="utf-8").read()
        self.assertIn("## 🎯 老师明说会考 / 不考 / 怎么考(2 条)", out)
        self.assertIn("[36:00](<../../课程视频/DEMO1001 - 26 Aug 20-s1-full.mp4#t=2160>)", out)
        self.assertIn("RACC 的含义? → 其它子句", out); self.assertIn("**MTTF + MTTR**", out); self.assertNotIn("::", out.split("## 🃏")[1])   # 卡片不再是 SR 语法
        j = json.load(open(os.path.join(self.tmp, "总结", "1002", "考点库.json"), encoding="utf-8"))
        self.assertEqual(j["unit"], "DEMO1001"); self.assertEqual(j["summaries"][0]["week"], 6)
        # 重跑幂等(考点库.md 自身不会被当成总结读进去)
        r2 = run(["python3", os.path.join(TOOLS, "exam_bank.py"), "1002", "--quiet"], env={"COURSE_ROOT": self.tmp})
        self.assertEqual(r2.returncode, 0); self.assertIn("1 份总结", open(os.path.join(self.tmp, "总结", "1002", "考点库.md"), encoding="utf-8").read())
    def test_missing_dir(self):
        self.assertNotEqual(run(["python3", os.path.join(TOOLS, "exam_bank.py"), "9999"], env={"COURSE_ROOT": self.tmp}).returncode, 0)

class CamFrames(unittest.TestCase):
    """cam_frames.select 是纯函数:用合成的 (t, ink, occl, dark) 序列验证换页检测、进度帧、黑屏过滤"""
    def setUp(self): self.m = load("cam_frames")
    def seq(self, spec, interval=10):
        # spec: [(帧数, ink, occl, dark), ...]
        out, t = [], 0
        for n, ink, occl, dark in spec:
            for _ in range(n): out.append({"t": t, "ink": ink, "occl": occl, "dark": dark}); t += interval
        return out
    def test_page_change_and_progress(self):
        fr = self.seq([(6, 0.005, 0.05, 0), (12, 0.02, 0.1, 0), (6, 0.03, 0.05, 0),   # 第一页:空白 → 写字 → 写满
                       (2, 0.012, 0.05, 0), (18, 0.015, 0.1, 0), (6, 0.028, 0.05, 0)])  # 换页(墨迹掉一半以上,无遮挡) → 第二页
        sel = self.m.select(fr, every=180, min_ink=0.010)
        ends = [x for x in sel if x["kind"] == "page_end"]
        self.assertEqual(len(ends), 2)
        self.assertEqual(ends[0]["ink"], 0.03); self.assertEqual(ends[1]["ink"], 0.028)
        self.assertTrue(any(x["kind"] == "progress" for x in sel))
        self.assertTrue(all(x["ink"] >= 0.010 for x in sel))          # 空白页不入选
        self.assertEqual([x["t"] for x in sel], sorted(x["t"] for x in sel))
    def test_hand_cover_is_not_page_change(self):
        fr = self.seq([(10, 0.03, 0.05, 0), (3, 0.01, 0.4, 0), (10, 0.03, 0.05, 0)])   # 手挡住 30 秒,墨迹骤降但遮挡高
        self.assertEqual(sum(1 for x in self.m.select(fr) if x["kind"] == "page_end"), 1)
    def test_black_camera(self):
        fr = self.seq([(40, 0.0, 1.0, 0.95)])
        self.assertEqual(self.m.select(fr), [])
    def test_check_summary_accepts_cam_path(self):
        cs = load("check_summary")
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "画面", "V", "cam")); os.makedirs(os.path.join(d, "课程视频"))
            open(os.path.join(d, "画面", "V", "cam", "t00120s.jpg"), "w").close()
            open(os.path.join(d, "课程视频", "V.srt"), "w").write("1\n00:00:01,000 --> 00:03:00,000\nhello\n")
            md = os.path.join(d, "V.md")
            open(md, "w", encoding="utf-8").write("# V 第1周(2026-07-20)— x\n\n## ⚠️ 课程通知\n无\n## 一句话概括\nx\n## 核心要点\n1. 见 cam/t00120s.jpg 与 cam/t00999s.jpg(02:00)\n## 章节时间线\n- **[02:00] a** — b\n## 金句 / 考点信号\n- x\n## 复习卡\n- q::a\n")
            r = run(["python3", os.path.join(TOOLS, "check_summary.py"), md, "--srt", os.path.join(d, "课程视频", "V.srt"), "--frames-dir", os.path.join(d, "画面", "V")], env={"COURSE_ROOT": d})
            self.assertIn("cam/t00999s.jpg", r.stdout); self.assertNotIn("cam/t00120s.jpg", r.stdout)

class DualAgent(unittest.TestCase):
    def test_agents_md_matches_skill(self):
        skill = open(os.path.join(ROOT, "skills", "video-summary", "SKILL.md"), encoding="utf-8").read()
        self.assertTrue(skill.startswith("---\nname: video-summary\ndescription:"))
        body = skill.split("---", 2)[2].lstrip("\n")
        agents = open(os.path.join(ROOT, "AGENTS.md"), encoding="utf-8").read()
        self.assertTrue(agents.rstrip().endswith(body.rstrip()), "AGENTS.md 与 SKILL.md 正文不一致,请跑 工具/sync_agents.sh")
    def test_claude_md_import_target_exists(self):
        s = open(os.path.join(ROOT, "CLAUDE.md"), encoding="utf-8").read()
        m = re.search(r"^@(\S+)", s, re.M); self.assertIsNotNone(m)
        self.assertTrue(os.path.exists(os.path.join(ROOT, m.group(1))))
    def test_install_links_three_dirs(self):
        # 用隔离的 HOME 真跑 install.sh 的第 3 步(前两步靠 PATH 里的假 brew 跳过)
        with tempfile.TemporaryDirectory() as home:
            fake = os.path.join(home, "bin"); os.makedirs(fake)
            open(os.path.join(fake, "brew"), "w").write("#!/bin/sh\n[ \"$1\" = list ] && exit 0\nexit 0\n"); os.chmod(os.path.join(fake, "brew"), 0o755)
            r = run(["bash", os.path.join(ROOT, "install.sh")], env={"HOME": home, "PATH": fake + ":" + os.environ["PATH"]})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            for d in [".claude/skills", ".codex/skills", ".agents/skills"]:
                link = os.path.join(home, d, "video-summary")
                self.assertTrue(os.path.islink(link) and os.path.exists(os.path.join(link, "SKILL.md")), d)
    def test_scripts_syntax(self):
        for f in os.listdir(TOOLS):
            p = os.path.join(TOOLS, f)
            if f.endswith(".sh"): self.assertEqual(run(["bash", "-n", p]).returncode, 0, f)
            if f.endswith(".py"): self.assertEqual(run(["python3", "-m", "py_compile", p]).returncode, 0, f)

if __name__ == "__main__":
    unittest.main()

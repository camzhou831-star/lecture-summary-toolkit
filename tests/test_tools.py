#!/usr/bin/env python3
"""单元测试:不需要 whisper/tesseract/网络,只用合成数据。运行: python3 -m unittest discover -s tests -v
覆盖:course_meta 文件名与周次、compact 幻觉过滤与时间标签、check_summary 三类错误、add_links 幂等与路径别名、
     build_bundle 空档检测(含 VAD 填充段)、dedup_frames 严格去重、ocr_frames 页码模式、match_slides 词匹配、
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
        with tempfile.TemporaryDirectory() as home:
            s = open(os.path.join(ROOT, "install.sh")).read()
            for d in [".claude/skills", ".codex/skills", ".agents/skills"]: self.assertIn(d, s)
    def test_scripts_syntax(self):
        for f in os.listdir(TOOLS):
            p = os.path.join(TOOLS, f)
            if f.endswith(".sh"): self.assertEqual(run(["bash", "-n", p]).returncode, 0, f)
            if f.endswith(".py"): self.assertEqual(run(["python3", "-m", "py_compile", p]).returncode, 0, f)

if __name__ == "__main__":
    unittest.main()

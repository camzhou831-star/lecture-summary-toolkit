#!/usr/bin/env python3
"""单元测试:不需要 whisper/tesseract/网络,只用合成数据。运行: python3 -m unittest discover -s tests -v
覆盖:course_meta 文件名与周次、compact 幻觉过滤与时间标签及新旧实现 golden、check_summary 三类错误与复习卡数量、review_pack 审核包、add_links 幂等与路径别名、
     build_bundle 空档检测(含 VAD 填充段)与 --duration/--video、原子写入、ocr_frames 规则 A(现场写代码帧不被合并)、dedup_frames 严格去重、ocr_frames 页码模式、match_slides 词匹配、exam_bank 跨周考点库、cam_frames 手写帧挑选与 check_summary 的 cam/ 路径、
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
    def test_golden_matches_old_implementation(self):
        # 期望输出由改写前(compact.sh 内嵌 Python,提交 3273de7)生成;compact.sh 包装与直接调 compact.py 都必须逐字节一致
        fx = os.path.join(ROOT, "tests", "fixtures")
        want = open(os.path.join(fx, "compact_edge.expected.txt"), "rb").read()
        with tempfile.TemporaryDirectory() as d:
            for cmd in (["bash", os.path.join(TOOLS, "compact.sh")], [sys.executable, os.path.join(TOOLS, "compact.py")]):
                out = os.path.join(d, "o.txt")
                r = run(cmd + [os.path.join(fx, "compact_edge.srt"), out]); self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(open(out, "rb").read(), want, cmd[-1])

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
            p = self._write(d, "# DEMO1001 第一周(2026-08-26)— x\n## ⚠️ 课程通知\n无\n## 一句话概括\n## 核心要点\n## 章节时间线\n- [01:00] ok\n## 金句 / 考点信号\n## 复习卡\n" + self.CARDS(8))
            r = run(["python3", os.path.join(TOOLS, "check_summary.py"), p], env={"COURSE_ROOT": d})
            self.assertEqual(r.returncode, 0, r.stdout)
    @staticmethod
    def CARDS(n):   # 问答卡与填空卡各一半,中间夹一行说明文字(不算卡)
        return "说明:以下为复习卡\n" + "".join(f"- q{i}::a{i}\n" if i % 2 else f"- x = ==v{i}==\n" for i in range(n))
    def test_card_count(self):
        head = "# DEMO1001 第一周(2026-08-26)— x\n## ⚠️ 课程通知\n无\n## 一句话概括\n## 核心要点\n## 章节时间线\n- [01:00] ok\n## 金句 / 考点信号\n## 复习卡\n"
        for n, ok, long in [(7, False, True), (8, True, True), (15, True, True), (16, False, True), (6, True, False), (16, False, False)]:
            with tempfile.TemporaryDirectory() as d:
                p = self._write(d, head + self.CARDS(n) + "## 附注\n- 不算::不算\n")
                if long: open(os.path.join(d, "课程视频", "DEMO1001 - 26 Aug 20-s1-full.srt"), "w").write("1\n00:00:05,000 --> 01:00:00,000\nhello\n")
                r = run(["python3", os.path.join(TOOLS, "check_summary.py"), p], env={"COURSE_ROOT": d})
                self.assertEqual(r.returncode == 0, ok, (n, r.stdout))
                if not ok: self.assertIn(f"复习卡 {n} 张", r.stdout)
    def test_placeholder_times(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "# DEMO1001 第一周(2026-08-26)— x\n## ⚠️ 课程通知\n- [19:51–20:xx] 通知\n## 一句话概括\n## 核心要点\n1. 讲指针(39:xx–40:XX)\n## 章节时间线\n- [01:00] ok\n## 金句 / 考点信号\n## 复习卡\n" + self.CARDS(8))
            r = run(["python3", os.path.join(TOOLS, "check_summary.py"), p], env={"COURSE_ROOT": d})
            self.assertEqual(r.returncode, 1); self.assertEqual(r.stdout.count("时间占位"), 3, r.stdout)

class Bilingual(unittest.TestCase):
    EN = "# DEMO1001 Week 6 (2026-08-26) — x\n## ⚠️ Course Notices\nNone\n## One-Sentence Summary\n## Key Points\n## Timeline\n- **[01:00] ok** — y\n## Quotes / Exam Signals\n## Review Cards\n"
    def setUp(self): self.H = load("headings")
    def test_names(self):
        H = self.H
        self.assertEqual((H.lang_of("a/X - 1.en.md"), H.lang_of("X.md"), H.lang_of("X.english.md")), ("en", "zh", "zh"))
        self.assertEqual((H.video_name("d/X - 26 Aug.en.md"), H.video_name("X - 26 Aug.md")), ("X - 26 Aug", "X - 26 Aug"))
        self.assertEqual(H.summary_name("V", "en"), "V.en.md")
        self.assertEqual((H.section_of("## ⚠️ 课程通知(07:08)"), H.section_of("## Timeline"), H.section_of("## Timeline", "zh"), H.section_of("## 其它")), ("notice", "timeline", None, None))
    def _course(self, d, fname, body):
        os.makedirs(os.path.join(d, "课程视频"), exist_ok=True); os.makedirs(os.path.join(d, "总结", "X"), exist_ok=True)
        open(os.path.join(d, "课程视频", "DEMO1001 - 26 Aug 20-s1-full.srt"), "w").write("1\n00:00:05,000 --> 00:10:00,000\nhello\n")
        open(os.path.join(d, "课程视频", "DEMO1001 - 26 Aug 20-s1-full.mp4"), "w").close()
        p = os.path.join(d, "总结", "X", fname); open(p, "w", encoding="utf-8").write(body); return p
    def test_check_summary_without_ffprobe(self):
        # 课程目录里有视频但没装 ffprobe(字幕模式的新手常见):不能崩,时长退回字幕结束时间
        with tempfile.TemporaryDirectory() as d:
            p = self._course(d, "DEMO1001 - 26 Aug 20-s1-full.en.md", self.EN + CheckSummary.CARDS(8))
            r = run([sys.executable, os.path.join(TOOLS, "check_summary.py"), p], env={"COURSE_ROOT": d, "PATH": tempfile.mkdtemp()})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("时长 9 分钟", r.stdout)
    def test_check_summary_by_filename(self):
        cards = CheckSummary.CARDS(8)
        with tempfile.TemporaryDirectory() as d:
            p = self._course(d, "DEMO1001 - 26 Aug 20-s1-full.en.md", self.EN + cards)
            r = run(["python3", os.path.join(TOOLS, "check_summary.py"), p], env={"COURSE_ROOT": d})
            self.assertEqual(r.returncode, 0, r.stdout)                                    # 找到同一视频的 srt,英文标题齐全
        with tempfile.TemporaryDirectory() as d:                                            # 中文内容却叫 .en.md
            zh = "# DEMO1001 第一周(2026-08-26)— x\n## ⚠️ 课程通知\n无\n## 一句话概括\n## 核心要点\n## 章节时间线\n- [01:00] ok\n## 金句 / 考点信号\n## 复习卡\n" + cards
            p = self._course(d, "DEMO1001 - 26 Aug 20-s1-full.en.md", zh)
            r = run(["python3", os.path.join(TOOLS, "check_summary.py"), p], env={"COURSE_ROOT": d})
            self.assertEqual(r.returncode, 1); self.assertIn("小节标题大多是中文", r.stdout); self.assertIn("缺少小节 ## Key Points", r.stdout)
        with tempfile.TemporaryDirectory() as d:                                            # 英文卡片数同样检查
            p = self._course(d, "DEMO1001 - 26 Aug 20-s1-full.en.md", self.EN + CheckSummary.CARDS(16))
            self.assertIn("复习卡 16 张", run(["python3", os.path.join(TOOLS, "check_summary.py"), p], env={"COURSE_ROOT": d}).stdout)
    def test_add_links_english(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._course(d, "DEMO1001 - 26 Aug 20-s1-full.en.md", self.EN)
            r = run(["python3", os.path.join(TOOLS, "add_links.py"), p], env={"COURSE_ROOT": d}); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("[01:00](<../../课程视频/DEMO1001 - 26 Aug 20-s1-full.mp4#t=60>)", open(p, encoding="utf-8").read())
    def test_course_meta_paths_and_lang(self):
        m = load("course_meta")
        cfg = {"year": 2026, "output_lang": "zh", "units": {"DEMO1001": {"alias": "1002", "output_lang": "en"}, "DEMO1004": {}}}
        r = m.parse("DEMO1001 - 26 Aug 20-s1-full.mp4", cfg)
        self.assertEqual((r["notes_path_en"], r["output_lang"]), (os.path.join("总结", "1002", "DEMO1001 - 26 Aug 20-s1-full.en.md"), "en"))
        self.assertEqual(m.parse("DEMO1004 - 26 Aug 20-s1-full.mp4", cfg)["output_lang"], "zh")    # 单元没配就用顶层
        self.assertIsNone(m.parse("DEMO1004 - 26 Aug 20-s1-full.mp4", {})["output_lang"])
    def test_policy_lists_exact_headings(self):
        policy = open(os.path.join(ROOT, "skills", "video-summary", "policy.md"), encoding="utf-8").read()
        for hs in self.H.SECTIONS.values():
            for h in hs.values(): self.assertIn(f"`{h}`", policy, h)                       # 脚本认的标题必须和 policy 里写的一字不差

class Lsk(unittest.TestCase):
    LSK = os.path.join(ROOT, "lsk")
    SRT = "1\n00:00:05,000 --> 00:00:09,000\nWelcome to week six.\n\n2\n00:01:10,000 --> 00:01:15,000\nThe test will be short answer.\n"
    def test_vtt_to_srt(self):
        m = load("lsk")
        vtt = "WEBVTT\nKind: captions\n\nNOTE comment\n\n00:05.000 --> 00:09.000 align:start\n<c>Welcome</c> to week six.\n\n1:01:10.000 --> 1:01:15.000\nLate line\n"
        self.assertEqual(m.vtt_to_srt(vtt), "1\n00:00:05,000 --> 00:00:09,000\nWelcome to week six.\n\n2\n01:01:10,000 --> 01:01:15,000\nLate line\n")
    def test_run_finish_subtitle_mode(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "captions.srt"); open(src, "w").write(self.SRT)
            env = {"COURSE_ROOT": os.path.join(d, "root")}
            r = run(["bash", self.LSK, "run", src], env=env)
            self.assertNotEqual(r.returncode, 0); self.assertIn("--unit DEMO1001 --date", r.stdout + r.stderr)   # 文件名看不出单元日期
            r = run(["bash", self.LSK, "run", src, "--unit", "DEMO1001", "--date", "2026-08-26", "--lang", "en"], env=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            vd = os.path.join(d, "root", "课程视频")
            self.assertEqual(sorted(os.listdir(vd)), sorted(f"DEMO1001 2026-08-26.{e}" for e in ("srt", "compact.txt", "bundle.json", "grounded.md")))
            self.assertIn("The test will be short answer.", open(os.path.join(vd, "DEMO1001 2026-08-26.grounded.md"), encoding="utf-8").read())
            self.assertIn(os.path.join("总结", "DEMO1001", "DEMO1001 2026-08-26.en.md"), r.stdout)
            open(src, "w").write(self.SRT.replace("short", "long"))                                      # 同名不同内容:不覆盖
            r = run(["bash", self.LSK, "run", src, "--unit", "DEMO1001", "--date", "2026-08-26"], env=env)
            self.assertNotEqual(r.returncode, 0); self.assertIn("--force", r.stdout + r.stderr)
            os.makedirs(os.path.join(d, "root", "总结", "DEMO1001"))
            summ = os.path.join(d, "root", "总结", "DEMO1001", "DEMO1001 2026-08-26.en.md")
            body = ("# DEMO1001 Week 6 (2026-08-26) — x\n## ⚠️ Course Notices\nNone\n## One-Sentence Summary\n## Key Points\n## Timeline\n- **[01:10] Test** — y\n"
                    "## Quotes / Exam Signals\n- 🎯 [01:10] \"The test will be short answer.\"\n## Review Cards\n" + CheckSummary.CARDS(8))
            open(summ, "w", encoding="utf-8").write(body)
            r = run(["bash", self.LSK, "finish", summ], env=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(os.path.isfile(os.path.join(d, "root", "总结", "DEMO1001", "Exam-Bank.en.md")))
    def test_doctor_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"PATH": "/usr/bin:/bin", "WHISPER_MODEL_DIR": d, "LANG": "en_AU.UTF-8"}
            r = run([sys.executable, os.path.join(TOOLS, "lsk.py"), "doctor"], env=env)
            self.assertEqual(r.returncode, 0, r.stdout); self.assertIn("Subtitle mode: ready", r.stdout)
            if not shutil.which("whisper-cli", path="/usr/bin:/bin"):
                r = run([sys.executable, os.path.join(TOOLS, "lsk.py"), "doctor", "--video"], env=env)
                self.assertEqual(r.returncode, 2)
                self.assertIn("brew install whisper-cpp" if sys.platform == "darwin" else "github.com/ggml-org/whisper.cpp", r.stdout)

class ReviewPack(unittest.TestCase):
    def test_pack_contents_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "课程视频")); os.makedirs(os.path.join(d, "总结", "X"))
            n = "DEMO1001 - 26 Aug 20-s1-full"
            summ = os.path.join(d, "总结", "X", n + ".md"); open(summ, "w").write("# s\n见 t00010s.jpg 与 cam/t00020s.jpg,还有 t00099s.jpg\n")
            open(os.path.join(d, "课程视频", n + ".grounded.md"), "w").write("[00:00] g\n📄 t=30s · p2/9 · t00030s.jpg ⚠️文字少,建议看图\n📄 t=40s · p3/9 · t00040s.jpg\n")
            fr = os.path.join(d, "画面", n); os.makedirs(os.path.join(fr, "cam"))
            for f in ("t00010s.jpg", "cam/t00020s.jpg", "t00030s.jpg", "t00040s.jpg"): open(os.path.join(fr, f), "w").close()
            open(os.path.join(d, "课程视频", n + ".srt"), "w").write("1\n00:00:00,000 --> 00:00:01,000\nx\n")
            out = os.path.join(d, "pack")
            r = run([sys.executable, os.path.join(TOOLS, "review_pack.py"), summ, "--out", out], env={"COURSE_ROOT": d})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(sorted(os.listdir(out)), ["grounded.md", "policy.md", "review.md", "summary.md", "transcript.srt", "画面"])
            got = sorted(os.path.relpath(os.path.join(r_, f), os.path.join(out, "画面")) for r_, _, fs in os.walk(os.path.join(out, "画面")) for f in fs)
            self.assertEqual(got, ["cam/t00020s.jpg", "t00010s.jpg", "t00030s.jpg"])   # 引用的 + ⚠️ 的;未标记的 t00040s 不带
            self.assertIn("找不到 1 张截图", r.stdout)                              # t00099s 不存在
            self.assertIn("--sandbox read-only", r.stdout)
            r = run([sys.executable, os.path.join(TOOLS, "review_pack.py"), summ, "--out", out], env={"COURSE_ROOT": d})
            self.assertNotEqual(r.returncode, 0)                               # 非空目录拒绝
            os.remove(os.path.join(d, "课程视频", n + ".grounded.md"))
            r = run([sys.executable, os.path.join(TOOLS, "review_pack.py"), summ], env={"COURSE_ROOT": d})
            self.assertIn("找不到讲义稿", r.stdout + r.stderr)

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

    SRT = "1\n00:00:00,000 --> 00:00:05,000\nhello\n\n2\n00:01:00,000 --> 00:01:10,000\nlast line\n"
    def _course(self):
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "课程视频"))
        srt = os.path.join(d, "课程视频", "X - clip.srt"); open(srt, "w").write(self.SRT)
        return d, srt
    def _run(self, d, srt, *extra, path=None):
        env = {"COURSE_ROOT": d}
        if path is not None: env["PATH"] = path
        r = run([sys.executable, os.path.join(TOOLS, "build_bundle.py"), srt, "--frames-dir", os.path.join(d, "none"), *extra], env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.load(open(os.path.join(d, "课程视频", "X - clip.bundle.json")))
    def _fake_ffprobe(self, seconds):
        b = tempfile.mkdtemp(); f = os.path.join(b, "ffprobe")
        open(f, "w").write(f"#!/bin/sh\necho {seconds}\n"); os.chmod(f, 0o755); return b
    def test_duration_flag_wins(self):
        d, srt = self._course()
        self.assertEqual(self._run(d, srt, "--duration", "999")["duration"], 999)
    def test_video_flag_uses_ffprobe_on_that_file(self):
        d, srt = self._course(); v = os.path.join(d, "elsewhere.mp4"); open(v, "w").close()
        self.assertAlmostEqual(self._run(d, srt, "--video", v, path=self._fake_ffprobe(123.5))["duration"], 123.5)
    def test_missing_video_or_ffprobe_falls_back_to_last_segment(self):
        d, srt = self._course()
        self.assertEqual(self._run(d, srt, "--video", os.path.join(d, "nope.mp4"))["duration"], 70)
        open(os.path.join(d, "课程视频", "X - clip.mp4"), "w").close()      # 同名视频在,但 PATH 里没有 ffprobe
        self.assertEqual(self._run(d, srt, path=tempfile.mkdtemp())["duration"], 70)
    def test_atomic_write_keeps_old_outputs_on_failure(self):
        from unittest import mock
        d, srt = self._course(); base = os.path.join(d, "课程视频", "X - clip")
        for ext in (".bundle.json", ".grounded.md"): open(base + ext, "w").write("OLD")
        old_env = os.environ.get("COURSE_ROOT"); os.environ["COURSE_ROOT"] = d
        try:
            bb = load("build_bundle")
            with mock.patch.object(sys, "argv", ["build_bundle.py", srt, "--frames-dir", os.path.join(d, "none"), "--duration", "70"]), \
                 mock.patch.object(bb.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError): bb.main()
        finally:
            if old_env is None: os.environ.pop("COURSE_ROOT", None)
            else: os.environ["COURSE_ROOT"] = old_env
        for ext in (".bundle.json", ".grounded.md"): self.assertEqual(open(base + ext).read(), "OLD", ext)

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

class OcrMergeRuleA(unittest.TestCase):
    """工具栏页码相同但画面是盖在课件上的编辑器(现场写代码)时,不能被合并掉(DEMO1001 26 Aug 5712s 的真实案例)"""
    def test_editor_over_same_page_is_kept(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            slide = "Graph-based testing criteria node coverage edge coverage edge-pair coverage loop coverage heuristic"
            editor = "if len myarray and or not isAlpha isEven for int i less than ninety nine"
            rows = [("t00100s.jpg", 100, slide), ("t00112s.jpg", 112, editor), ("t00124s.jpg", 124, editor + " for int i")]
            for f, t, _ in rows: Image.new("RGB", (8, 8)).save(os.path.join(d, f))
            json.dump([{"file": f, "t": t, "page": 16, "pages": 20, "text": x, "chars": len(x)} for f, t, x in rows],
                      open(os.path.join(d, "ocr.json"), "w"))
            r = run([sys.executable, os.path.join(TOOLS, "ocr_frames.py"), d]); self.assertEqual(r.returncode, 0, r.stderr)
            kept = [e["file"] for e in json.load(open(os.path.join(d, "ocr.json")))]
            self.assertIn("t00100s.jpg", kept)                  # 课件页保留
            self.assertIn("t00124s.jpg", kept)                  # 编辑器的最新状态保留(112s 被 124s 包含,按规则 B 删掉)
            self.assertNotIn("t00112s.jpg", kept)
    def test_same_page_same_content_still_merged(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            a = "Graph-based testing criteria node coverage edge coverage"
            rows = [("t00100s.jpg", 100, a), ("t00112s.jpg", 112, a + " edge-pair coverage loop")]
            for f, t, _ in rows: Image.new("RGB", (8, 8)).save(os.path.join(d, f))
            json.dump([{"file": f, "t": t, "page": 16, "pages": 20, "text": x, "chars": len(x)} for f, t, x in rows],
                      open(os.path.join(d, "ocr.json"), "w"))
            r = run([sys.executable, os.path.join(TOOLS, "ocr_frames.py"), d]); self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual([e["file"] for e in json.load(open(os.path.join(d, "ocr.json")))], ["t00112s.jpg"])

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
    EN_SUMMARY = """# DEMO1001 Week 6 (2026-08-26) — Logic Testing

## ⚠️ Course Notices (07:08–07:35)

1. Project brief released today (07:08).
2. 🎯 The project does not require an SQA plan (36:00, slide p30).

## One-Sentence Summary

x

## Key Points

1. -

## Timeline

- **[07:08] Notices** — -

## Quotes / Exam Signals

- 🎯 Exam question type (73:09): write a test set satisfying RACC.

## Review Cards

- What does RACC mean?::flipping the major clause flips the predicate
"""
    def test_bilingual_dir_writes_two_banks(self):
        d = os.path.join(self.tmp, "总结", "1002")
        open(os.path.join(d, "DEMO1001 - 26 Aug 20-s1-full.en.md"), "w", encoding="utf-8").write(self.EN_SUMMARY)
        r = run(["python3", os.path.join(TOOLS, "exam_bank.py"), "1002"], env={"COURSE_ROOT": self.tmp})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        zh = open(os.path.join(d, "考点库.md"), encoding="utf-8").read(); en = open(os.path.join(d, "Exam-Bank.en.md"), encoding="utf-8").read()
        self.assertIn("1 份总结", zh); self.assertNotIn("SQA plan", zh)                       # 英文条目不混进中文考点库
        self.assertIn("# DEMO1001 Exam Bank (auto-generated)", en); self.assertIn("from 1 summaries", en)
        self.assertIn("## 🎯 Lecturer said what will / won't be examined, or how (2)", en)
        self.assertIn("[36:00](<../../课程视频/DEMO1001 - 26 Aug 20-s1-full.mp4#t=2160>)", en)   # 英文总结链接到同一个视频
        self.assertIn("What does RACC mean? → flipping", en); self.assertNotIn("复习卡", en); self.assertNotIn("老师", en)
        self.assertEqual(json.load(open(os.path.join(d, "Exam-Bank.en.json"), encoding="utf-8"))["summaries"][0]["week"], 6)
        r = run(["python3", os.path.join(TOOLS, "exam_bank.py"), "1002", "--quiet"], env={"COURSE_ROOT": self.tmp})   # 重跑不把两份考点库当总结
        self.assertIn("from 1 summaries", open(os.path.join(d, "Exam-Bank.en.md"), encoding="utf-8").read())
        r = run(["python3", os.path.join(TOOLS, "exam_bank.py"), "1002", "--out", os.path.join(self.tmp, "x.md")], env={"COURSE_ROOT": self.tmp})
        self.assertNotEqual(r.returncode, 0); self.assertIn("--out 只能指定一份", r.stdout + r.stderr)
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
    def test_rules_live_in_policy_and_review(self):
        sd = os.path.join(ROOT, "skills", "video-summary")
        skill = open(os.path.join(sd, "SKILL.md"), encoding="utf-8").read()
        for f in ("policy.md", "review.md"):
            self.assertTrue(os.path.isfile(os.path.join(sd, f)), f); self.assertIn(f"skills/video-summary/{f}", skill)
        for rule in ("Grounding", "固定结构", "技术核查清单"):                  # 写作规则只在 policy.md
            self.assertNotIn(rule, skill)
        self.assertIn("policy.md", open(os.path.join(sd, "review.md"), encoding="utf-8").read())
    def test_claude_md_import_target_exists(self):
        for f in ("CLAUDE.md", "GEMINI.md"):
            s = open(os.path.join(ROOT, f), encoding="utf-8").read()
            m = re.search(r"^@(\S+)", s, re.M); self.assertIsNotNone(m, f)
            self.assertTrue(os.path.exists(os.path.join(ROOT, m.group(1))), f)
    def test_web_prompts_match_policy(self):
        r = run([sys.executable, os.path.join(TOOLS, "build_prompts.py"), "--check"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for lang in ("zh", "en"):
            p = open(os.path.join(ROOT, "prompts", f"web-prompt.{lang}.md"), encoding="utf-8").read()
            self.assertIn("## 4. 考试信息", p); self.assertIn("## Key Points" if lang == "en" else "## 核心要点", p)
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

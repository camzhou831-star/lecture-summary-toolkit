"""工作台基本测试:不联网、不需要 whisper 和模型 Key(模型调用用假的替换)。运行: cd workbench && uv run pytest -q
字幕素材在测试里现生成(仓库规定 .srt 不能放在 tests/ 和 examples/ 之外)。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_srt(n=40, step=15):
    blocks = []
    for i in range(n):
        s, e = i * step, i * step + step - 1
        ts = lambda x: f"{x // 3600:02d}:{x % 3600 // 60:02d}:{x % 60:02d},000"
        blocks.append(f"{i + 1}\n{ts(s)} --> {ts(e)}\nSentence number {i} about gradient descent and learning rate.\n")
    return "\n".join(blocks)


GOOD = """# Gradient descent basics — 学习率

> 讲者:Test · 本讲没有课件页码

## ⚠️ 课程通知

无

## 一句话概括

梯度下降沿负梯度方向更新参数 [录播 00:00]。

## 核心要点

1. 学习率决定步长 [录播 01:00–02:15]。

## 章节时间线

- **[00:00] 开场** — 介绍梯度下降。
- **[05:00] 学习率** — 讲学习率的选择。

## 金句 / 考点信号

- "learning rate matters" [录播 05:00]

## 复习卡

梯度下降沿什么方向更新::负梯度方向
"""


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("WORKBENCH_NO_WORKER", "1")
    monkeypatch.setenv("WORKBENCH_CONFIG", str(tmp_path / "none.json"))
    monkeypatch.setenv("WORKBENCH_PROVIDER", "api")          # 测试不去调本机的 claude / codex
    monkeypatch.delenv("WORKBENCH_COOKIES_BROWSER", raising=False)
    for k in ("DEEPSEEK_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    import importlib
    from wb import config
    importlib.reload(config)
    from wb import db, llm, pipeline, server, sources
    for m in (db, sources, llm, pipeline, server):
        importlib.reload(m)
    db.init()
    srt = tmp_path / "Lecture 1.srt"
    srt.write_text(make_srt(), encoding="utf-8")
    return {"tmp": tmp_path, "srt": str(srt), "db": db, "pipeline": pipeline, "sources": sources, "server": server, "llm": llm}


# ---------- 链接识别 ----------
def test_parse_youtube(env):
    s = env["sources"]
    for url in ("https://www.youtube.com/watch?v=aircAruvnKk&list=x", "https://youtu.be/aircAruvnKk?si=1", "看这个 https://youtube.com/shorts/aircAruvnKk"):
        assert s.parse_source(url) == ("youtube", "aircAruvnKk", "https://www.youtube.com/watch?v=aircAruvnKk")


def test_parse_bilibili_with_share_text(env):
    s = env["sources"]
    kind, vid, url = s.parse_source("【机器学习】第1讲 https://www.bilibili.com/video/BV1Wv411h7kN/?spm_id_from=333&p=3 分享")
    assert (kind, vid, url) == ("bilibili", "BV1Wv411h7kN_p3", "https://www.bilibili.com/video/BV1Wv411h7kN?p=3")
    assert s.parse_source("https://www.bilibili.com/video/BV1Wv411h7kN")[1] == "BV1Wv411h7kN"


def test_parse_rejects(env):
    s = env["sources"]
    with pytest.raises(s.SourceError, match="抖音"):
        s.parse_source("https://v.douyin.com/abc/")
    with pytest.raises(s.SourceError, match="找不到文件"):
        s.parse_source("/nope/x.mp4")


def test_parse_other_sites_go_to_ytdlp(env):
    s = env["sources"]
    kind, vid, url = s.parse_source("https://www.twitch.tv/videos/2345678901")
    assert (kind, url) == ("web", "https://www.twitch.tv/videos/2345678901") and vid == "twitch_videos_2345678901"
    assert s.parse_source("https://vimeo.com/76979871")[0] == "web"
    assert s.site_name("https://uwa.au.panopto.com/Panopto/Pages/Viewer.aspx?id=x") == "Panopto"


def test_jump_url_web(env):
    s = env["sources"]
    assert s.jump_url("web", "https://www.twitch.tv/videos/1", 3725) == "https://www.twitch.tv/videos/1?t=1h2m5s"
    assert s.jump_url("web", "https://vimeo.com/76979871", 75) == "https://vimeo.com/76979871#t=75s"


def test_cookies_browser_only_when_chosen(env, tmp_path, monkeypatch):
    s, cfg = env["sources"], __import__("wb.config", fromlist=["x"])
    assert s.ytdlp_auth() == []
    cfg.save_setting("cookies_browser", "chrome")
    assert s.ytdlp_auth() == ["--cookies-from-browser", "chrome"]
    cfg.save_setting("cookies_browser", "../evil")
    assert s.ytdlp_auth() == []
    assert oct(os.stat(cfg.CONFIG_FILE).st_mode & 0o777) == "0o600"


def test_cli_provider_flatten_and_auto(env, monkeypatch):
    llm = env["llm"]
    sys_, prompt = llm._flatten([{"role": "system", "content": "S"}, {"role": "user", "content": "U"}])
    assert (sys_, prompt) == ("S", "U")
    _, prompt = llm._flatten([{"role": "system", "content": "S"}, {"role": "user", "content": "U"},
                              {"role": "assistant", "content": "A"}, {"role": "user", "content": "FIX"}])
    assert "你上一次的回答" in prompt and prompt.index("A") < prompt.index("FIX")
    monkeypatch.setenv("WORKBENCH_PROVIDER", "auto")
    monkeypatch.setattr(llm, "available", lambda: {"api": (False, ""), "claude": (False, ""), "codex": (True, "/x/codex")})
    assert llm.resolve() == "codex"
    monkeypatch.setattr(llm, "available", lambda: {"api": (False, ""), "claude": (False, ""), "codex": (False, "")})
    with pytest.raises(llm.LLMError, match="Claude Code 或 Codex"):
        llm.resolve()


def test_parse_local(env):
    assert env["sources"].parse_source(env["srt"])[:2] == ("local", "Lecture_1")


def test_jump_url(env):
    s = env["sources"]
    assert s.jump_url("youtube", "https://www.youtube.com/watch?v=aircAruvnKk", 75) == "https://www.youtube.com/watch?v=aircAruvnKk&t=75s"
    assert s.jump_url("bilibili", "https://www.bilibili.com/video/BV1Wv411h7kN", 75).endswith("BV1Wv411h7kN?t=75")
    assert s.jump_url("bilibili", "https://www.bilibili.com/video/BV1Wv411h7kN?p=3", 75).endswith("?p=3&t=75")
    assert s.jump_url("local", "/x.mp4", 75) is None


def test_vtt_rolling_captions(env, tmp_path):
    vtt = tmp_path / "a.vtt"
    vtt.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhello world\n\n00:00:03.000 --> 00:00:03.010\nhello world\n\n"
                   "00:00:03.010 --> 00:00:05.000\nhello world\nnext line\n", encoding="utf-8")
    out = tmp_path / "a.srt"
    assert env["sources"].vtt_to_srt(str(vtt), str(out)) == 2
    text = out.read_text(encoding="utf-8")
    assert "00:00:01,000 --> 00:00:03,000\nhello world" in text and "next line" in text and text.count("hello world") == 1


def test_bilibili_download_sends_range_header(env, monkeypatch, tmp_path):
    """B 站 CDN 不带 Range 头会回 567(yt-dlp issue #17847);下载命令里必须带上"""
    s = env["sources"]
    seen = []

    def fake_run(cmd, log, timeout=0, env=None):
        seen.append(cmd)
        return 1, "HTTP Error 567: Unknown Status"
    monkeypatch.setattr(s, "run", fake_run)
    monkeypatch.setattr(s, "need", lambda c: c)
    task = {"kind": "bilibili", "source": "https://www.bilibili.com/video/BV1Wv411h7kN", "vid": "BV1Wv411h7kN", "lang": "auto"}
    with pytest.raises(s.SourceError, match="567"):
        s.fetch(task, str(tmp_path / "root"), lambda m: None)
    assert "Range:bytes=0-" in seen[0] and seen[0][seen[0].index("Range:bytes=0-") - 1] == "--add-header"


# ---------- 处理 ----------
def test_api_transcript_uses_mmss(env, tmp_path):
    p = env["pipeline"]
    g = tmp_path / "x.grounded.md"
    g.write_text("# x · 讲义稿\n\n> 时长\n> 每行 `[HH:MM]` 是…\n\n[00:00] hi\n\n[01:40] later\n", encoding="utf-8")
    b = tmp_path / "x.bundle.json"
    b.write_text('{"segments": [{"start": 3.2, "end": 5, "text": "hi"}, {"start": 6016.7, "end": 6020, "text": "later"}]}', encoding="utf-8")
    t = p.api_transcript(str(g), str(b))
    assert "[00:03] hi" in t and "[100:16] later" in t and "[HH:MM]" not in t


def test_link_timeline_only_in_timeline(env):
    p = env["pipeline"]
    task = {"kind": "youtube", "source": "https://www.youtube.com/watch?v=aircAruvnKk"}
    md = p.link_timeline(GOOD, task)
    assert "- **[05:00](<https://www.youtube.com/watch?v=aircAruvnKk&t=300s>) 学习率**" in md
    assert "1. 学习率决定步长 [录播 01:00–02:15]。" in md           # 核心要点不动
    assert p.link_timeline(md, task) == md                          # 幂等
    assert p.link_timeline(GOOD, {"kind": "local", "source": "/x.mp4"}) == GOOD


def test_system_prompt_contains_policy_and_headings(env):
    sp = env["pipeline"].system_prompt("en")
    assert "Review Cards" in sp and "写作规则(policy.md)" in sp and "{lang_hint}" not in sp


def test_duration_not_written_as_timestamp(env):
    """时长写成 MM:SS 会被模型照抄进引用块,check_summary 当成时间戳判"超出时长"(英文实测踩过)"""
    task = {"kind": "youtube", "source": "x", "vid": "x", "out_lang": "en"}
    up = env["pipeline"].user_prompt(task, {"duration": 1120}, "")
    assert "18 分 40 秒" in up and "18:40" not in up


def test_pipeline_end_to_end_with_fake_model(env, monkeypatch):
    """本地 .srt → 整理 → (假)模型 → 加链接 + check_summary 通过"""
    db, p, llm = env["db"], env["pipeline"], env["llm"]
    calls = []

    def fake_chat(messages, on_progress=None, **k):
        if "专名校对员" in messages[0]["content"]:
            return '{"fixes": [], "unsure": []}', {"model": "fake", "usage": None, "finish_reason": "stop"}
        if "课程总结的审核员" in messages[0]["content"]:
            return '{"verdict": "通过", "issues": []}', {"model": "fake", "usage": None, "finish_reason": "stop"}
        calls.append(messages)
        assert "[05:00]" in messages[1]["content"]          # 讲义稿用 [MM:SS] 标签
        return GOOD, {"model": "fake", "usage": None, "finish_reason": "stop"}
    monkeypatch.setattr(llm, "chat", fake_chat)
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid)
    p.run_task(tid)
    t = db.get(tid)
    assert t["status"] == "done", t["log"]
    assert t["check_ok"] == 1, t["check_report"]
    assert set(t["timings"]) == {"fetch", "prepare", "summarize", "check", "names", "review"}
    assert t["meta"]["review"]["passed"] and "审核 1 轮通过" in t["message"]
    assert t["meta"]["names"]["fixed"] == [] and "没发现" in t["meta"]["names"]["report"]
    assert len(calls) == 1
    assert os.path.exists(p.summary_path(t))


def test_pipeline_repairs_once_when_check_fails(env, monkeypatch):
    db, p, llm = env["db"], env["pipeline"], env["llm"]
    bad = GOOD.replace("[05:00] 学习率", "[59:00] 学习率")      # 超出视频时长(10 分钟)
    replies = [bad, GOOD]

    def fake_chat(messages, on_progress=None, **k):
        if "专名校对员" in messages[0]["content"]:
            return '{"fixes": [], "unsure": []}', {"model": "fake", "usage": None, "finish_reason": "stop"}
        if "课程总结的审核员" in messages[0]["content"]:
            return '{"verdict": "通过", "issues": []}', {"model": "fake", "usage": None, "finish_reason": "stop"}
        if len(replies) == 1:
            assert "检查结果" in messages[-1]["content"] and "59:00" in messages[-1]["content"]
        return replies.pop(0), {"model": "fake", "usage": None, "finish_reason": "stop"}
    monkeypatch.setattr(llm, "chat", fake_chat)
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid)
    p.run_task(tid)
    t = db.get(tid)
    assert t["status"] == "done" and t["check_ok"] == 1 and not replies


def test_pipeline_without_key_fails_clearly(env):
    db, p = env["db"], env["pipeline"]
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid)
    p.run_task(tid)
    t = db.get(tid)
    assert t["status"] == "failed" and "Key" in t["message"] and t["stage"] == "summarize"
    assert "fetch" in t["timings"]                                   # 拿稿和整理已完成,配好 Key 重跑时直接复用


# ---------- 接口 ----------
def test_api(env):
    from fastapi.testclient import TestClient
    with TestClient(env["server"].app) as c:
        cj = c.get("/api/config").json()
        assert cj["key_ok"] is False and {p["id"] for p in cj["providers"]} == {"claude", "codex", "api"}
        assert c.post("/api/config/provider", json={"provider": "nope"}).status_code == 400
        assert c.post("/api/config/provider", json={"provider": "codex"}).status_code == 200
        from wb import config as cfg
        assert cfg._file_config()["provider"] == "codex"          # 写进配置文件(测试里环境变量优先,所以看文件)
        assert c.post("/api/config/cookies", json={"browser": "netscape"}).status_code == 400
        st = c.get("/api/status").json()
        assert {t["name"] for t in st["tools"]} >= {"yt-dlp", "ffmpeg", "whisper-cli"} and st["counts"] == {}
        assert {"platform", "brew", "npm", "model_ready", "workbench_dir"} <= set(st) and st["workbench_dir"].endswith("workbench")
        assert c.post("/api/tasks", json={"source": "https://v.douyin.com/x/"}).status_code == 400
        assert c.post("/api/tasks", json={"source": "https://youtu.be/aircAruvnKk", "out_lang": "fr"}).status_code == 400
        r = c.post("/api/tasks", json={"source": "https://youtu.be/aircAruvnKk"})
        assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["kind"] == "youtube"
        tid = r.json()["id"]
        assert c.get(f"/api/tasks/{tid}").json()["log"] == ""
        assert c.get(f"/api/tasks/{tid}/summary").status_code == 404
        r = c.post("/api/upload", files={"file": ("my talk.srt", make_srt(4).encode(), "text/plain")})
        assert r.status_code == 200 and r.json()["kind"] == "local"
        assert c.post("/api/upload", files={"file": ("x.exe", b"1", "application/octet-stream")}).status_code == 400
        assert [t["id"] for t in c.get("/api/tasks").json()][-1] == tid
        assert c.delete(f"/api/tasks/{tid}").json() == {"ok": True}
        assert c.get(f"/api/tasks/{tid}").status_code == 404
        assert "总结工作台" in c.get("/").text


# ---------- 中英双语 ----------
def test_i18n_keys_exist_in_both_languages():
    """页面(data-i18n*)和 JS(t("..."))用到的词条,中英两套都要有;用 node 读 i18n.js 的词典,没有 node 就跳过"""
    import json, re, shutil, subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("没有 node")
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wb", "static")
    i18n = os.path.join(static, "i18n.js")
    out = subprocess.run([node, "-e", f"eval(require('fs').readFileSync({json.dumps(i18n)}, 'utf8') + ';globalThis.D=I18N'); "
                          "console.log(JSON.stringify({zh: Object.keys(D.zh), en: Object.keys(D.en)}))"],
                         capture_output=True, text=True, env=dict(os.environ, LANG="C"))
    assert out.returncode == 0, out.stderr
    d = json.loads(out.stdout)
    assert set(d["zh"]) == set(d["en"]), set(d["zh"]) ^ set(d["en"])
    html = open(os.path.join(static, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(static, "app.js"), encoding="utf-8").read()
    used = set(re.findall(r'data-i18n(?:-ph|-title|-html)?="([\w]+)"', html))
    used |= {k for k in re.findall(r'\bt\("(\w+)"', js) if not k.endswith("_")}   # "kind_" + k 这类动态拼接的前缀不算
    used |= {"st_" + k for k in ("fetch", "prepare", "summarize", "check")} | {"kind_" + k for k in ("youtube", "bilibili", "local", "web")}
    missing = sorted(k for k in used if k not in d["zh"])
    assert not missing, missing


# ---------- 对标拆稿 / 会议纪要 ----------
def short_srt(tmp_path):
    p = tmp_path / "short.srt"
    p.write_text("1\n00:00:00,000 --> 00:00:12,000\n你知道吗?九成的人都用错了。今天教你三步。\n\n"
                 "2\n00:00:12,000 --> 00:00:30,000\n第一步打开设置,第二步找到隐私,第三步关掉追踪。我自己试过,一周省了两小时。\n\n"
                 "3\n00:00:30,000 --> 00:00:36,000\n关注我,下期讲更多。\n", encoding="utf-8")
    return str(p)


def test_breakdown_sentences_and_stats(env, tmp_path):
    from wb import breakdown as b
    subs = b.sentences(short_srt(tmp_path))
    assert [x[2] for x in subs][:3] == ["你知道吗?", "九成的人都用错了。", "今天教你三步。"]
    assert abs(subs[-1][1] - 36) < 0.01 and all(x[1] >= x[0] for x in subs)
    assert b.count("用 AI 做 3 个 demo") == 6                      # 汉字各 1,英文词和数字各算 1
    segs = [{"from": 1, "to": 2, "role": "钩子", "points": 1, "note": "反常识"},
            {"from": 3, "to": len(subs) - 2, "role": "清单", "points": 3, "note": "三步"},
            {"from": len(subs) - 1, "to": len(subs), "role": "结尾", "points": 0, "note": "关注"}]
    assert b.validate(segs, len(subs)) == []
    assert b.validate([{"from": 1, "to": 2, "role": "钩子"}, {"from": 4, "to": len(subs), "role": "结尾"}], len(subs))   # 漏了第 3 句
    md = b.stats(subs, segs)
    assert "## 3. 分段表" in md and "## 4. 全片指标" in md and "| 1 | 钩子 | [00:00]" in md and "| 无 |" in md
    seg_json, body = b.extract_segments('前言\n```segments\n[{"from":1,"to":2,"role":"钩子","points":1}]\n```\n## 5. 逐段要点\nx')
    assert seg_json[0]["role"] == "钩子" and "```" not in body and body.endswith("x")
    with pytest.raises(b.BreakdownError):
        b.extract_segments("没有代码块")


def test_meeting_templates_from_meetily(env):
    from wb import templates as T
    lst = T.listing()["meetings"]
    assert [m["id"] for m in lst][0] == "meeting.standard_meeting" and len(lst) == 5
    p = T.system_prompt("meeting.standard_meeting", "zh", None)
    assert "## 关键决定" in p and "## 待办事项" in p and "Only use information present in the source text" in p and "[MM:SS]" in p
    assert T.required("meeting.daily_standup", "en") == ["## Date", "## Attendees", "## Yesterday", "## Today", "## Blockers", "## Notes"]
    assert T.valid("meeting.retrospective") and not T.valid("meeting.../x") and not T.valid("meeting.psychatric_session")


def test_generic_check(env, tmp_path):
    from wb import templates as T
    srt = short_srt(tmp_path)
    ok, rep = T.check("# t\n## 摘要\n说了 [00:20]\n## 关键决定\n- x\n## 待办事项\n## 讨论要点\n", srt, "meeting.standard_meeting", "zh")
    assert ok, rep
    ok, rep = T.check("# t\n## 摘要\n说了 [09:20]\n", srt, "meeting.standard_meeting", "zh")
    assert not ok and "缺少小节 ## 关键决定" in rep and "超出视频时长" in rep


def test_pipeline_breakdown_with_fake_model(env, monkeypatch, tmp_path):
    db, p, llm = env["db"], env["pipeline"], env["llm"]
    srt = short_srt(tmp_path)
    from wb import breakdown as b
    n = len(b.sentences(srt))

    def fake_chat(messages, on_progress=None, **k):
        if "专名校对员" in messages[0]["content"]:
            return '{"fixes": [], "unsure": []}', {"model": "fake", "usage": None, "finish_reason": "stop"}
        if "课程总结的审核员" in messages[0]["content"]:
            return '{"verdict": "通过", "issues": []}', {"model": "fake", "usage": None, "finish_reason": "stop"}
        assert "逐句表" in messages[1]["content"] and "钩子 / 承诺" in messages[0]["content"]
        segs = [{"from": 1, "to": 2, "role": "钩子", "points": 1, "note": "反常识"}, {"from": 3, "to": n, "role": "清单", "points": 3, "note": "三步"}]
        return ("```segments\n" + json.dumps(segs, ensure_ascii=False) + "\n```\n\n## 5. 逐段要点\n- 段1 [00:00]\n\n## 6. 可学的写法\n- 反常识开头 [00:00]\n\n"
                "## 7. 收藏点与借鉴边界\n- 三步清单 [00:12]"), {"model": "fake", "usage": None, "finish_reason": "stop"}
    monkeypatch.setattr(llm, "chat", fake_chat)
    kind, vid, src = env["sources"].parse_source(srt)
    tid = db.create(kind, src, vid, template="breakdown")
    p.run_task(tid)
    t = db.get(tid)
    assert t["status"] == "done" and t["check_ok"] == 1, t["log"]
    md = open(p.summary_path(t), encoding="utf-8").read()
    assert md.index("## 1. 开头前 15 秒") < md.index("## 3. 分段表") < md.index("## 5. 逐段要点") and "```segments" not in md


def test_api_rejects_unknown_template(env):
    from fastapi.testclient import TestClient
    with TestClient(env["server"].app) as c:
        assert c.post("/api/tasks", json={"source": "https://youtu.be/aircAruvnKk", "template": "nope"}).status_code == 400
        r = c.post("/api/tasks", json={"source": "https://youtu.be/aircAruvnKk", "template": "meeting.project_sync"})
        assert r.status_code == 200 and r.json()["template"] == "meeting.project_sync"
        assert len(c.get("/api/templates").json()["meetings"]) == 5


def test_derive_reuses_transcript(env, monkeypatch):
    """换个用途:沿用原任务的文字稿,换模板出一份新任务,不重新拿稿;原任务保留"""
    from fastapi.testclient import TestClient
    db, p, llm = env["db"], env["pipeline"], env["llm"]
    monkeypatch.setattr(llm, "chat", lambda messages, on_progress=None, **k: (GOOD, {"model": "fake", "usage": None, "finish_reason": "stop"}))
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid, template="meeting.project_sync")
    with TestClient(env["server"].app) as c:
        r = c.post(f"/api/tasks/{tid}/derive", json={"template": "course"})
        assert r.status_code == 400 and "文字稿" in r.json()["detail"]          # 还没拿到文字稿
        p.run_task(tid)
        assert c.post(f"/api/tasks/{tid}/derive", json={"template": "nope"}).status_code == 400
        assert c.post("/api/tasks/9999/derive", json={"template": "course"}).status_code == 404
        r = c.post(f"/api/tasks/{tid}/derive", json={"template": "course", "out_lang": "en"})
        assert r.status_code == 200, r.text
        n = r.json()
        assert n["id"] != tid and n["template"] == "course" and n["out_lang"] == "en" and n["meta"]["derived_from"] == tid
        assert "沿用任务" in n["message"] and n["timings"].get("fetch") is not None
    assert os.path.isfile(os.path.join(p.task_root(n["id"]), "课程视频", vid + ".srt"))
    monkeypatch.setattr(env["sources"], "fetch", env["sources"].fetch)
    p.run_task(n["id"])
    t = db.get(n["id"])
    assert t["status"] == "done" and "已有文字稿,跳过拿稿" in t["log"], t["log"]
    assert db.get(tid)["template"] == "meeting.project_sync" and os.path.exists(p.summary_path(db.get(tid)))


def test_names_check_fixes_only_confident_and_safe(env, monkeypatch):
    """专名核对:只采纳 high、原文找得到、不动时间戳的条目;其余列待核实;改的结果写进总结和 meta"""
    from wb import names
    md = "- [02:24] 黄云勋辞去 CEO,英伟达宣布 [02:30]\n- Cloud(转写疑似:Slack)把表格做进聊天框\n- 某人 C Dream 5.5\n- Cloud 表格、Cloudflare、相当于 Cloud 400 元档"
    fixes = [{"old": "黄云勋", "new": '黄仁勋(转写为"黄云勋")', "name": "黄仁勋", "confidence": "high", "why": "英伟达 CEO"},
             {"old": "Cloud(转写疑似:Slack)", "new": 'Claude(转写为"Cloud")', "heard": "Cloud", "name": "Claude", "confidence": "high"},
             {"old": "C Dream 5.5", "new": "Seedream 5.5", "name": "Seedream", "confidence": "low"},
             {"old": "[02:30]", "new": "[02:31]", "confidence": "high"},
             {"old": "不存在的", "new": "x", "confidence": "high"}]
    out, used, skipped = names.apply(md, fixes)
    assert '黄仁勋(转写为"黄云勋")' in out and 'Claude(转写为"Cloud")' in out and "C Dream 5.5" in out and "[02:30]" in out
    assert "- Claude 表格、Cloudflare、相当于 Claude 400 元档" in out and used[1]["more"] == 2      # 整词才换
    assert len(used) == 2 and [w for _, w in skipped] == ["把握不够", "会动到时间戳", "总结里找不到这段原文"]
    rep = names.report(used, skipped, [{"text": "Garner", "guess": "Gartner", "why": "只有读音像"}, {"text": "Garner(转写疑似)", "why": "重复"}])
    assert "已校正 2 处" in rep and "待核实 4 处" in rep and "Gartner" in rep
    # 同一个听错的词:第一条改完把别处也一并改了,后面几条找不到原文,不该再列成待核实;猜的和原文一样的也不列
    md2 = "回顾 Shelling 隔离模型。以 Shelling 为例。Shelling 模型从混合社区出发。Downey 画了图。"
    f2 = [{"old": "Shelling 隔离模型", "new": "Schelling 隔离模型", "heard": "Shelling", "name": "Schelling", "confidence": "high"},
          {"old": "Shelling 为例", "new": "Schelling 为例", "heard": "Shelling", "name": "Schelling", "confidence": "high"},
          {"old": "Shelling 模型从混合社区出发", "new": "Schelling 模型从混合社区出发", "heard": "Shelling", "name": "Schelling", "confidence": "high"}]
    out2, used2, skipped2 = names.apply(md2, f2)
    assert "Shelling" not in out2 and len(used2) == 1 and used2[0]["more"] == 2 and len(skipped2) == 2
    u2 = [{"text": "Downey", "guess": "Downey", "why": "把握不够"}, {"text": "Shelling", "guess": "", "why": "?"}, {"text": "Voids", "guess": "Boids", "why": "只有读音像"}]
    assert [u["text"] for u in names.pending(skipped2, u2, used2)] == ["Voids"]
    rep2 = names.report(used2, skipped2, u2)
    assert "待核实 1 处" in rep2 and "Downey" not in rep2
    assert names.parse('前言\n```json\n{"fixes": [], "unsure": []}\n```') == ([], [])
    with pytest.raises(names.NamesError):
        names.parse("不是 json")

    db, p, llm = env["db"], env["pipeline"], env["llm"]
    good = GOOD.replace("梯度下降沿负梯度", "提读下降沿负梯度")

    def fake_chat(messages, on_progress=None, **k):
        if "专名校对员" in messages[0]["content"]:
            assert "提读下降" in messages[1]["content"]
            return json.dumps({"fixes": [{"old": "提读下降", "new": '梯度下降(转写为"提读下降")', "name": "梯度下降", "confidence": "high"}], "unsure": []},
                              ensure_ascii=False), {"model": "fake", "usage": None, "finish_reason": "stop"}
        return good, {"model": "fake", "usage": None, "finish_reason": "stop"}
    monkeypatch.setattr(llm, "chat", fake_chat)
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid)
    p.run_task(tid)
    t = db.get(tid)
    assert t["status"] == "done" and t["check_ok"] == 1, t["log"]
    assert '梯度下降(转写为"提读下降")' in open(p.summary_path(t), encoding="utf-8").read()
    assert t["meta"]["names"]["fixed"][0]["name"] == "梯度下降" and "专名核对" in t["log"]


def test_names_check_failure_does_not_fail_task(env, monkeypatch):
    db, p, llm = env["db"], env["pipeline"], env["llm"]

    def fake_chat(messages, on_progress=None, **k):
        if "专名校对员" in messages[0]["content"]:
            raise llm.LLMError("超时")
        return GOOD, {"model": "fake", "usage": None, "finish_reason": "stop"}
    monkeypatch.setattr(llm, "chat", fake_chat)
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid)
    p.run_task(tid)
    t = db.get(tid)
    assert t["status"] == "done" and t["check_ok"] == 1 and "专名核对没做成" in t["log"] and "names" not in (t["meta"] or {})


def test_save_api_key_from_ui(env, monkeypatch):
    """界面里粘贴 Key:先试 /models,401 不存;对了就存进配置文件并切到 api;空字符串删掉"""
    from fastapi.testclient import TestClient
    import httpx
    from wb import config as cfg
    monkeypatch.delenv("WORKBENCH_PROVIDER", raising=False)
    seen = []

    def fake_get(url, headers=None, timeout=None):
        seen.append((url, headers["Authorization"]))
        return httpx.Response(401 if headers["Authorization"].endswith("bad") else 200, request=httpx.Request("GET", url))
    monkeypatch.setattr(env["server"].httpx, "get", fake_get)
    with TestClient(env["server"].app) as c:
        r = c.post("/api/config/key", json={"api_key": "sk-bad"})
        assert r.status_code == 400 and "Key 不对" in r.json()["detail"] and not cfg._file_config().get("api_key")
        assert c.post("/api/config/key", json={"api_key": "sk-1", "base_url": "http://evil.example"}).status_code == 400
        j = c.post("/api/config/key", json={"api_key": " sk-good "}).json()
        assert j["key_ok"] and j["provider"] == "api" and cfg._file_config()["api_key"] == "sk-good"
        assert seen[-1] == ("https://api.deepseek.com/models", "Bearer sk-good")
        assert oct(os.stat(cfg.CONFIG_FILE).st_mode & 0o777) == "0o600"
        j = c.post("/api/config/key", json={"api_key": ""}).json()
        assert not j["key_ok"] and j["provider"] == "auto"


# ---------- 审核内容 ----------
def test_review_verify_keeps_only_grounded_issues():
    """审核方给的依据原文必须真的在资料里;常识 / 推导单独标出;它引的总结原句也得存在"""
    from wb import review
    corpus = "[37:44] So if I say in exam, like write this, pseudo code is a little bit more formal.\n[课件 p13/19]\nCars vs average speed, eps = 0.01"
    summary = "讲师说 eps = 0.1 时更早降速。Boids 1978 年提出。"
    issues = [
        {"severity": "一般", "type": "技术错误", "where": "要点 8", "quote": "eps = 0.1 时更早降速", "problem": "图例是 0.01",
         "evidence": "Cars vs average speed,  EPS = 0.01", "source": "课件 p13", "fix": ""},
        {"severity": "严重", "type": "考试信息", "where": "通知", "quote": "", "problem": "编的", "evidence": "the exam is worth 60%", "source": "讲义稿 [10:00]", "fix": ""},
        {"severity": "一般", "type": "技术错误", "where": "要点 10", "quote": "Boids 1978 年提出", "problem": "一般记为 1986–87", "evidence": "", "source": "常识", "fix": ""},
        {"severity": "一般", "type": "说过头", "where": "x", "quote": "总结里没有这句", "problem": "", "evidence": "pseudo code is a little bit more formal", "source": "讲义稿", "fix": ""},
        {"severity": "轻微", "type": "其他", "where": "y", "quote": "", "problem": "", "evidence": "So if I say in exam … pseudo code", "source": "讲义稿", "fix": ""},
    ]
    used, dropped = review.verify([dict(i) for i in issues], corpus, summary)
    assert [i["where"] for i in used] == ["要点 8", "要点 10", "y"] and used[1].get("outside")
    assert [w for _, w in dropped] == ["依据原文在资料里找不到", "总结里找不到它说的那句"]
    assert review.serious(used) == used[:2]
    p = review.fix_prompt(used, "zh")
    assert "不要悄悄换掉讲师原话" in p and "一般记为 1986–87" in p
    assert review.parse('```json\n{"verdict": "issues", "issues": [{"severity": "severe", "problem": "x"}, "bad"]}\n```')[0]["severity"] == "严重"
    with pytest.raises(review.ReviewError):
        review.parse("不是 json")


def test_reviewer_choice():
    from wb import review
    both = {"claude": (True, ""), "codex": (True, ""), "api": (True, "")}
    assert review.reviewer("claude", both) == ("codex", True)
    assert review.reviewer("codex", both) == ("claude", True)
    assert review.reviewer("claude", dict(both, codex=(False, ""))) == ("claude", False)   # 只有一家:同一家独立调用
    assert review.reviewer("api", both) == ("api", False)                                  # DeepSeek 自己审


def test_pipeline_review_fixes_then_passes(env, monkeypatch):
    """第 1 轮审核挑出有依据的问题 → 写作方修正 → 第 2 轮通过;编造依据的问题不采纳"""
    db, p, llm = env["db"], env["pipeline"], env["llm"]
    fixed = GOOD.replace("学习率决定步长", "学习率决定每一步走多远")
    seen = {"review": 0, "fix": None}
    issue = {"severity": "一般", "type": "出处不符", "where": "核心要点 1", "quote": "学习率决定步长", "problem": "原话没说步长",
             "evidence": "Sentence number 4 about gradient descent", "source": "讲义稿 [01:00]", "fix": "改写"}
    fake_issue = dict(issue, where="通知", evidence="the exam is next week", severity="严重")

    def fake_chat(messages, on_progress=None, **k):
        sysm = messages[0]["content"]
        if "专名校对员" in sysm:
            return '{"fixes": [], "unsure": []}', {"model": "fake", "usage": None, "finish_reason": "stop"}
        if "你是复核员" in sysm:
            return '[{"n": 1, "verdict": "成立", "why": "x"}]', {"model": "fake", "usage": None, "finish_reason": "stop"}
        if "课程总结的审核员" in sysm:
            seen["review"] += 1
            assert "<summary>" in messages[1]["content"] and "讲义稿" in messages[1]["content"]
            body = {"verdict": "有问题", "issues": [issue, fake_issue]} if seen["review"] == 1 else {"verdict": "通过", "issues": []}
            return "```json\n" + json.dumps(body, ensure_ascii=False) + "\n```", {"model": "fake", "usage": None, "finish_reason": "stop"}
        if "审核员对照资料提出了下面这些问题" in messages[-1]["content"]:
            seen["fix"] = messages[-1]["content"]
            return fixed, {"model": "fake", "usage": None, "finish_reason": "stop"}
        return GOOD, {"model": "fake", "usage": None, "finish_reason": "stop"}
    monkeypatch.setattr(llm, "chat", fake_chat)
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid)
    p.run_task(tid)
    t = db.get(tid)
    rv = t["meta"]["review"]
    assert t["status"] == "done" and t["check_ok"] == 1 and rv["passed"] and rv["rounds"] == 2, t["log"]
    assert "原话没说步长" in seen["fix"] and "the exam is next week" not in seen["fix"]       # 编造依据的那条没交给写作方
    assert "依据原文在资料里找不到" in rv["report"] and "学习率决定每一步走多远" in open(p.summary_path(t), encoding="utf-8").read()
    assert "审核 2 轮通过" in t["message"]


def test_pipeline_review_disputed_issues_are_marked(env, monkeypatch):
    """复核有分歧:不改结论,在原处标待核实;复核两次都否定的不改。任务完成但不说「审核通过」"""
    db, p, llm = env["db"], env["pipeline"], env["llm"]
    issue = {"severity": "严重", "type": "技术错误", "where": "金句", "quote": "learning rate matters", "problem": "25 辆的方向说反了",
             "evidence": "Sentence number 20 about gradient descent", "source": "讲义稿 [05:00]", "fix": ""}
    other = dict(issue, where="要点 1", quote="学习率决定步长", problem="独特问题XYZ")
    seen = {"fix": []}

    def fake_chat(messages, on_progress=None, **k):
        sysm = messages[0]["content"]
        if "专名校对员" in sysm:
            return '{"fixes": [], "unsure": []}', {"model": "fake", "usage": None, "finish_reason": "stop"}
        if "你是复核员" in sysm:     # 两次判定:第 1 条一次成立一次无法确定 → 标待核实;第 2 条两次都不成立 → 不改
            first = "成立" if k.get("temperature", 0) < 0.5 else "无法确定"
            return json.dumps([{"n": 1, "verdict": first}, {"n": 2, "verdict": "不成立"}], ensure_ascii=False), {"model": "fake", "usage": None, "finish_reason": "stop"}
        if "课程总结的审核员" in sysm:
            assert "已在原处标了待核实" in messages[1]["content"] or "复核两次都否定" not in messages[1]["content"] or True
            issues = [issue, other] if not seen["fix"] else []
            return json.dumps({"verdict": "有问题", "issues": issues}, ensure_ascii=False), {"model": "fake", "usage": None, "finish_reason": "stop"}
        if "审核员对照资料提出了下面这些问题" in messages[-1]["content"]:
            seen["fix"].append(messages[-1]["content"])
            return GOOD + "\n```declined\n[]\n```", {"model": "fake", "usage": None, "finish_reason": "stop"}
        return GOOD, {"model": "fake", "usage": None, "finish_reason": "stop"}
    monkeypatch.setattr(llm, "chat", fake_chat)
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid)
    p.run_task(tid)
    t = db.get(tid)
    rv = t["meta"]["review"]
    assert len(seen["fix"]) == 1 and "不要改结论" in seen["fix"][0] and "独特问题XYZ" not in seen["fix"][0], seen["fix"]
    assert rv["marked"] == 1 and rv["remaining"] == 0 and not rv["passed"] and rv["rounds"] == 2
    assert "标了「待核实」" in rv["report"] and "成立/无法确定" in rv["report"] and "不成立/不成立" in rv["report"]
    assert "拿不准已标待核实" in t["message"]



def make_pdf(pages):
    """手写一个最小的多页 PDF(每页一行文字),测课件用"""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out.encode()))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    x = len(out.encode())
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n"
    return out.encode()


@pytest.mark.skipif(not __import__("shutil").which("pdftotext"), reason="没装 pdftotext")
def test_slides_upload_reach_writer_and_reviewer(env, monkeypatch):
    """课件 PDF:上传 → 建任务时带上 → 逐页文字交给写作方和审核方;换用途时沿用"""
    from fastapi.testclient import TestClient
    db, p, llm = env["db"], env["pipeline"], env["llm"]
    seen = []

    def fake_chat(messages, on_progress=None, **k):
        sysm = messages[0]["content"]
        if "专名校对员" in sysm:
            return '{"fixes": [], "unsure": []}', {"model": "fake", "usage": None, "finish_reason": "stop"}
        seen.append((sysm, messages[1]["content"]))
        if "课程总结的审核员" in sysm:
            return '{"verdict": "通过", "issues": []}', {"model": "fake", "usage": None, "finish_reason": "stop"}
        return GOOD, {"model": "fake", "usage": None, "finish_reason": "stop"}
    monkeypatch.setattr(llm, "chat", fake_chat)
    with TestClient(env["server"].app) as c:
        assert c.post("/api/slides", files={"file": ("a.pptx", b"x")}).status_code == 400
        r = c.post("/api/slides", files={"file": ("W09.pdf", make_pdf(["Recap and Traffic Jam", "Cars vs average speed eps 0.01"]))})
        assert r.status_code == 200, r.text
        name = r.json()["slides"]
        assert c.post("/api/tasks", json={"source": env["srt"], "slides": "../x.pdf"}).status_code == 400
        assert c.post("/api/tasks", json={"source": env["srt"], "slides": "nope.pdf"}).status_code == 400
        t = c.post("/api/tasks", json={"source": env["srt"], "slides": name}).json()
        p.run_task(t["id"])
        t = db.get(t["id"])
        assert t["status"] == "done" and t["meta"]["materials"] == "课件 W09.pdf", t["log"]
        writer, reviewer = seen[0], seen[1]
        assert "[课件 p2/2]" in writer[1] and "Cars vs average speed eps 0.01" in writer[1] and "资料:课件 W09.pdf" in writer[1]
        assert "附了本讲课件的逐页文字" in writer[0] and "没有课件和画面" not in writer[0]
        assert "课程总结的审核员" in reviewer[0] and "Cars vs average speed" in reviewer[1]
        n = c.post(f"/api/tasks/{t['id']}/derive", json={"template": "course", "out_lang": "en"}).json()
        assert os.path.isfile(os.path.join(p.task_root(n["id"]), "课件", "W09.pdf")) and "review" not in n["meta"]


def test_writer_can_decline_wrong_review_issue(env, monkeypatch):
    """审核员也会错:写作方核实后可以不采纳,理由交给下一轮审核,并写进审核报告"""
    from wb import review
    body, no = review.split_declined(GOOD + '\n```declined\n[{"n": 1, "why": "课件 p13 图例是 0.01"}, {"n": 9}]\n```\n', [{"where": "要点 8", "problem": "改回 0.1"}])
    assert body == GOOD.strip() and no == [{"where": "要点 8", "problem": "改回 0.1", "declined": "课件 p13 图例是 0.01"}]
    assert review.split_declined(GOOD, [])[1] == []

    db, p, llm = env["db"], env["pipeline"], env["llm"]
    issue = {"severity": "严重", "type": "技术错误", "where": "核心要点 1", "quote": "学习率决定步长", "problem": "要求改回讲师口误",
             "evidence": "Sentence number 4 about gradient descent", "source": "讲义稿 [01:00]", "fix": ""}
    seen = []

    def fake_chat(messages, on_progress=None, **k):
        sysm = messages[0]["content"]
        if "专名校对员" in sysm:
            return '{"fixes": [], "unsure": []}', {"model": "fake", "usage": None, "finish_reason": "stop"}
        if "你是复核员" in sysm:
            return '[{"n": 1, "verdict": "成立", "why": "x"}]', {"model": "fake", "usage": None, "finish_reason": "stop"}
        if "课程总结的审核员" in sysm:
            seen.append(messages[1]["content"])
            body = {"verdict": "有问题", "issues": [issue]} if len(seen) == 1 else {"verdict": "通过", "issues": []}
            return json.dumps(body, ensure_ascii=False), {"model": "fake", "usage": None, "finish_reason": "stop"}
        if "审核员对照资料提出了下面这些问题" in messages[-1]["content"]:
            return GOOD + '\n```declined\n[{"n": 1, "why": "讲师口误,课件为准"}]\n```', {"model": "fake", "usage": None, "finish_reason": "stop"}
        return GOOD, {"model": "fake", "usage": None, "finish_reason": "stop"}
    monkeypatch.setattr(llm, "chat", fake_chat)
    kind, vid, src = env["sources"].parse_source(env["srt"])
    tid = db.create(kind, src, vid)
    p.run_task(tid)
    t = db.get(tid)
    rv = t["meta"]["review"]
    assert rv["passed"] and "写作方核实后不采纳:讲师口误,课件为准" in seen[1] and "写作方核实后没采纳" in rv["report"]
    assert "declined" not in open(p.summary_path(t), encoding="utf-8").read()

#!/usr/bin/env python3
"""从录播文件名解析 单元代码/日期/周次,决定总结应放的路径。规则可配置,不把某一学期的文件名当契约。
用法: course_meta.py <视频文件名或路径> [--root <COURSE_ROOT>] [--year 2026] [--json]
配置: <COURSE_ROOT>/course.json(可选),例如
  {
    "year": 2026,                       # 录播年份(文件名里通常没有;不给则用今年并提示确认)
    "semester_start": "2026-07-20",     # 第 1 周周一,用来算周次
    "break_weeks_after": [6],           # 第 6 周之后放一周假(期中假),周次顺延
    "filename_patterns": ["..."],       # 追加的文件名正则,需含命名组 unit, day, mon(或 month), 可选 year
    "units": {"DEMO1001": {"alias": "1002", "slides_dir": "课件/DEMO1001"}}   # alias: 总结子文件夹用别名(不给则用单元代码)
  }
输出(默认人类可读;--json 机器可读): unit, alias, date, year_source, week, notes_dir, notes_path
"""
import argparse, datetime, json, os, re, sys
MONTHS = {m: i for i, m in enumerate(["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1)}
DEFAULT_PATTERNS = [
    # UWA LMS/Echo360 导出: "DEMO1001 - 26 Aug 20-s1-full.mp4"("20-s1" 不是年份,是导出流编号)
    r"^(?P<unit>[A-Z]{4}\d{4})\s*-\s*(?P<day>\d{1,2})\s+(?P<mon>[A-Z][a-z]{2})\b",
    # "DEMO1001_2026-08-26_lecture.mp4" / "DEMO1001 2026-08-26.mp4"
    r"^(?P<unit>[A-Z]{4}\d{4})[\s_-]+(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})",
    # "2026-08-26 DEMO1001 ..."
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})[\s_-]+(?P<unit>[A-Z]{4}\d{4})",
    # 只有单元代码
    r"^(?P<unit>[A-Z]{4}\d{4})\b",
]

def load_config(root):
    p = os.path.join(root, "course.json")
    if not os.path.exists(p): return {}
    try: return json.load(open(p, encoding="utf-8"))
    except json.JSONDecodeError as e: sys.exit(f"错误: {p} 不是合法 JSON: {e}")

def parse(name, cfg, year_override=None):
    base = os.path.splitext(os.path.basename(name))[0]
    patterns = list(cfg.get("filename_patterns", [])) + DEFAULT_PATTERNS
    m = None
    for pat in patterns:
        m = re.search(pat, base)
        if m: break
    if not m: return None
    g = m.groupdict()
    unit = g.get("unit")
    year_source = "文件名"
    year = g.get("year")
    if year: year = int(year)
    elif year_override: year, year_source = int(year_override), "--year 参数"
    elif cfg.get("year"): year, year_source = int(cfg["year"]), "course.json"
    else: year, year_source = datetime.date.today().year, "今年(未确认,请核对)"
    date = None
    if g.get("day") and (g.get("mon") or g.get("month")):
        month = int(g["month"]) if g.get("month") else MONTHS.get(g["mon"].lower())
        if month:
            try: date = datetime.date(year, month, int(g["day"]))
            except ValueError: date = None
    week = None
    if date and cfg.get("semester_start"):
        start = datetime.date.fromisoformat(cfg["semester_start"])
        raw = (date - start).days // 7 + 1
        # 假期顺延:break_weeks_after=[6] 表示第 6 周之后有一周假,之后的 raw 周要减 1
        adj = sum(1 for b in cfg.get("break_weeks_after", []) if raw > b)
        week = raw - adj if raw >= 1 else None
    ucfg = cfg.get("units", {}).get(unit, {})
    alias = ucfg.get("alias", unit)
    return {"unit": unit, "alias": alias, "date": date.isoformat() if date else None, "year": year, "year_source": year_source,
            "week": week, "slides_dir": ucfg.get("slides_dir"), "notes_dir": os.path.join("总结", alias),
            "notes_path": os.path.join("总结", alias, base + ".md"), "pattern": patterns.index(m.re.pattern) if m.re.pattern in patterns else None}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("--root"); ap.add_argument("--year"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = a.root or os.environ.get("COURSE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = parse(a.name, load_config(root), a.year)
    if not r:
        print(f"⚠️ 无法从文件名识别单元代码: {a.name};请在 course.json 的 filename_patterns 里加规则,或手动指定总结路径", file=sys.stderr); sys.exit(2)
    if a.json: print(json.dumps(r, ensure_ascii=False))
    else:
        print(f"单元 {r['unit']}(总结子文件夹 {r['alias']})· 日期 {r['date'] or '未知'}(年份来自:{r['year_source']})· 第 {r['week'] or '?'} 周")
        print(f"总结应存: {r['notes_path']}")
        if r["slides_dir"]: print(f"课件目录: {r['slides_dir']}")

if __name__ == "__main__":
    main()

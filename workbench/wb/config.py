"""工作台配置:路径与模型 Key。

Key 不进仓库,按顺序找:
  1. 环境变量 DEEPSEEK_API_KEY(或通用的 LLM_API_KEY)
  2. 本机配置文件 ~/.config/lecture-workbench/config.json(可用 WORKBENCH_CONFIG 指定别的路径),格式:
     {"api_key": "sk-...", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"}
base_url / model 也可以用环境变量 LLM_BASE_URL / LLM_MODEL 覆盖。
"""
import json
import os
from dataclasses import dataclass

WB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # workbench/
TOOLKIT = os.path.dirname(WB_DIR)                                          # 录播课工具仓库根目录
TOOLS = os.path.join(TOOLKIT, "工具")
POLICY = os.path.join(TOOLKIT, "skills", "video-summary", "policy.md")
TEMPLATES = os.path.join(WB_DIR, "templates")
DATA = os.environ.get("WORKBENCH_DATA") or os.path.join(WB_DIR, "data")   # 已在 .gitignore,含下载的转写和总结
CONFIG_FILE = os.environ.get("WORKBENCH_CONFIG") or os.path.join(os.path.expanduser("~"), ".config", "lecture-workbench", "config.json")

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


@dataclass
class LLMConfig:
    api_key: str | None
    base_url: str
    model: str
    source: str            # Key 从哪来的(给页面显示,不显示 Key 本身)
    provider: str = "auto"  # auto / claude / codex / api(见 llm.py)


def _file_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def llm_config() -> LLMConfig:
    fc = _file_config()
    key, source = None, "未配置"
    for name in ("DEEPSEEK_API_KEY", "LLM_API_KEY"):
        if os.environ.get(name):
            key, source = os.environ[name], f"环境变量 {name}"
            break
    if not key and fc.get("api_key"):
        key, source = fc["api_key"], f"配置文件 {CONFIG_FILE}"
    base = os.environ.get("LLM_BASE_URL") or fc.get("base_url") or DEFAULT_BASE_URL
    model = os.environ.get("LLM_MODEL") or fc.get("model") or DEFAULT_MODEL
    provider = os.environ.get("WORKBENCH_PROVIDER") or fc.get("provider") or "auto"
    return LLMConfig(key, base.rstrip("/"), model, source, provider)


def review_model():
    """审核 / 复核用的模型(只对 API 有效)。DeepSeek 默认用推理更强的 deepseek-v4-pro;别的接口默认和写总结同一个"""
    fc = _file_config()
    m = os.environ.get("LLM_REVIEW_MODEL") or fc.get("review_model")
    if m:
        return m
    return "deepseek-v4-pro" if "deepseek.com" in llm_config().base_url else None


def update_check():
    """打开工作台时自动检查新版(默认开;设置里可以关)"""
    v = _file_config().get("update_check")
    return True if v is None else bool(v)


def parallel_tasks():
    """最多同时跑几个任务(1–4,默认 2)。转写仍一次一个,同时跑的是写总结、审核这些调模型的步骤"""
    v = os.environ.get("WORKBENCH_PARALLEL") or _file_config().get("parallel_tasks")
    try:
        return min(4, max(1, int(v))) if v not in (None, "") else 2
    except (TypeError, ValueError):
        return 2


def quick_review_minutes():
    """多短的内容用快速审核(分钟):审核用写总结同一个快模型、只审一轮,挑出严重问题才用推理模型复核。0 = 一律严格审核"""
    v = os.environ.get("WORKBENCH_QUICK_REVIEW_MIN") or _file_config().get("quick_review_minutes")
    try:
        return max(0.0, float(v)) if v not in (None, "") else 20.0
    except ValueError:
        return 20.0


BROWSERS = ("chrome", "safari", "firefox", "edge", "brave", "arc")


def cookies_browser():
    """要登录的网站用哪个浏览器的登录状态(yt-dlp --cookies-from-browser);默认空 = 不用"""
    b = os.environ.get("WORKBENCH_COOKIES_BROWSER") or _file_config().get("cookies_browser") or ""
    return b if b in BROWSERS else ""


def save_provider(provider):
    save_setting("provider", provider)


def save_setting(key, value):
    """只改配置文件里的一项,其余(包括 Key)原样保留;文件权限 600"""
    fc = _file_config()
    fc[key] = value
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    fd = os.open(CONFIG_FILE + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, indent=1)
    os.replace(CONFIG_FILE + ".tmp", CONFIG_FILE)

#!/usr/bin/env bash
# 防泄漏门禁:examples/ 之外不允许出现任何可能是课程内容的文件(CI 与 pre-commit 都可用)
# 允许的例外:顶层文档 .md、tests/ 下的合成素材
# 课程术语表属于课程数据,放在课程目录 <COURSE_ROOT>/glossary/ 里,不进本仓库(合成示例放 examples/)
set -euo pipefail
cd "$(dirname "$0")/.."
bad=$(git ls-files | grep -vE '^(examples|tests)/' \
  | grep -E '\.(srt|vtt|txt|mp4|mkv|mov|webm|m4a|mp3|wav|aiff|jpg|jpeg|png|pdf|pptx|docx)$|grounded\.md$|bundle\.json$|compact\.txt$|ocr\.json$|^(课程视频|画面|总结|课件)/' || true)
if [ -n "$bad" ]; then echo "❌ 发现疑似课程内容(不允许提交到 examples/ 之外):"; echo "$bad"; exit 1; fi
echo "✅ 未发现课程内容"

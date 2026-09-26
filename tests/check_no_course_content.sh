#!/usr/bin/env bash
# 防泄漏门禁:examples/ 之外不允许出现任何可能是课程内容的文件(CI 与 pre-commit 都可用)
# 允许的例外:工具/glossary/*.txt(术语表)、顶层 requirements*.txt(依赖清单)、顶层文档 .md、tests/ 下的合成素材
set -euo pipefail
cd "$(dirname "$0")/.."
bad=$(git ls-files | grep -vE '^(examples|tests)/' | grep -vE '^工具/glossary/[^/]+\.txt$' | grep -vE '^requirements[^/]*\.txt$' \
  | grep -E '\.(srt|vtt|txt|mp4|mkv|mov|webm|m4a|mp3|wav|aiff|jpg|jpeg|png|pdf|pptx|docx)$|grounded\.md$|bundle\.json$|compact\.txt$|ocr\.json$|^(课程视频|画面|总结|课件)/' || true)
if [ -n "$bad" ]; then echo "❌ 发现疑似课程内容(不允许提交到 examples/ 之外):"; echo "$bad"; exit 1; fi
echo "✅ 未发现课程内容"

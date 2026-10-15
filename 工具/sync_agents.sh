#!/usr/bin/env bash
# 从 skills/video-summary/SKILL.md 生成仓库根目录的 AGENTS.md(Codex CLI 读)、CLAUDE.md(Claude Code 读)、GEMINI.md(Gemini CLI 读),
# 并从 policy.md 生成降级模式提示词 prompts/web-prompt.{zh,en}.md
# 用法: bash 工具/sync_agents.sh   (改了 SKILL.md 之后跑一次;只在工具仓库里有意义)
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
skill="$root/skills/video-summary/SKILL.md"
[ -f "$skill" ] || { echo "错误: 找不到 $skill(本脚本只在工具仓库里使用)" >&2; exit 1; }
{
  echo "# AGENTS.md — 录播课总结工具(Codex CLI 项目指令)"
  echo
  echo "> 本文件由 \`工具/sync_agents.sh\` 从 \`skills/video-summary/SKILL.md\` 生成,不要手改。"
  echo "> 当用户要求\"总结视频 / 总结录播课 / 这个视频讲了什么\"时,按下面流程执行;其它任务照常。"
  echo
  awk 'BEGIN{fm=0} /^---$/{fm++; next} fm>=2{print}' "$skill"
} > "$root/AGENTS.md"
cat > "$root/CLAUDE.md" <<'EOC'
# 录播课总结工具(Claude Code 项目指令)

工作流程见技能文件(与 Codex 共用同一份):

@skills/video-summary/SKILL.md

安装到全局技能目录后,在任何目录说"总结 xxx.mp4"即可触发:`bash install.sh` 会把它链接到 `~/.claude/skills/`、`~/.codex/skills/` 与 `~/.agents/skills/`。
EOC
cat > "$root/GEMINI.md" <<'EOG'
# 录播课总结工具(Gemini CLI 项目指令)

工作流程见技能文件(与 Claude Code、Codex 共用同一份):

@skills/video-summary/SKILL.md
EOG
python3 "$root/工具/build_prompts.py"
echo "== 已生成 AGENTS.md ($(wc -l < "$root/AGENTS.md") 行)、CLAUDE.md、GEMINI.md"

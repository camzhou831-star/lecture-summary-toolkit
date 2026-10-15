# 贡献指南

- **不要提交任何课程内容**:录播、课件、转写、截图、讲义稿、总结、考试题。CI 会拒绝 `examples/` 之外的媒体、转写、OCR、课件与总结文件(规则见 `tests/check_no_course_content.sh`,提交前可本地跑)。示例请用 `examples/demo/` 的合成素材,或自己录制并声明授权。
- **术语表**:课程目录下 `glossary/<单元代码>.txt`(属于课程数据,不提交到本仓库;示例见 `examples/demo/glossary/`),英文、逗号分隔、控制在 300 词以内(whisper prompt 有长度上限)。只放专有名词和缩写,不放句子。
- **文件名规则**:新学校/新 LMS 的录播命名请加到 `工具/course_meta.py` 的 `DEFAULT_PATTERNS`,并在 `tests/test_tools.py` 加一个用例。
- **改流程**:改 `skills/video-summary/SKILL.md`,然后 `bash 工具/sync_agents.sh` 重新生成 `AGENTS.md` / `CLAUDE.md`;CI 会检查两者一致。
- **测试**:`python3 -m unittest discover -s tests`(秒级,无外部依赖);`bash tests/run_pipeline_demo.sh`(需要 ffmpeg/whisper-cpp/tesseract/poppler,默认用 tiny.en 模型)。
- 提 PR 前跑一遍 `bash -n 工具/*.sh` 与 `python3 -m py_compile 工具/*.py`。

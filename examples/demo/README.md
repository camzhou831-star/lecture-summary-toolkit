# 示例:合成的两分钟"讲座"

`课程视频/DEMO1001 - 01 Jan 26-s1-demo.mp4` 是用程序生成的幻灯片 + macOS 语音合成朗读的**原创**内容(主题:循环测试与素路径),前 8 秒是黑屏静音,模拟真实录播。没有任何学校版权内容,可随意分发、用作 CI 素材。

```bash
COURSE_ROOT=examples/demo bash 工具/prepare.sh "DEMO1001 - 01 Jan 26-s1-demo.mp4" en
```

产物(已随仓库提供,可对照):
- `课程视频/*.srt / .compact.txt / .grounded.md / .bundle.json` — 转写与讲义稿
- `画面/DEMO1001 - 01 Jan 26-s1-demo/` — 幻灯片帧与 `ocr.json`(含课件 PDF 匹配到的页码)
- `总结/DEMO1001/DEMO1001 - 01 Jan 26-s1-demo.md` — agent 按技能文件写出的总结样例
- `课件/DEMO1001/DEMO1001-testing-loops.pdf` — 课件,用来演示 PDF 页码匹配

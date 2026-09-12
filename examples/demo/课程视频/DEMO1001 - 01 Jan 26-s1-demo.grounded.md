# DEMO1001 - 01 Jan 26-s1-demo · 讲义稿(转写 + 幻灯片 OCR 对齐)

> 时长 0:01:51 · 转写段 14 · 幻灯片帧 7 · 生成于 2026-09-12
> 每行 `[HH:MM]` 是该分钟的转写(时:分)。`📄 t=秒 · p页/总页 · 文件名` 是该分钟出现的幻灯片及其 OCR 文本,图片在 `画面/DEMO1001 - 01 Jan 26-s1-demo/`。
> OCR 文本很短(<60 字符)或看起来是代码/图表/终端的帧,建议直接打开图片看。课件页码来自 Okular 工具栏的 "N of M",没有的帧是终端/浏览器/桌面等非课件画面。

[00:00] Welcome to this short demo lecture. Everything you hear and see here was generated for testing the summary toolkit. So there is no copyright problem in sharing it. Today's topic is testing loops. Loops are surprisingly hard to test. The body of a loop can run zero times, exactly once, or many times, and each of those counts can hide a different fault. Line coverage tells you the but not how many times. So here is the informal heuristic that most teams use. Write one test where the loop body never runs, one where it runs exactly once, and one where it runs more than once. This is informal, but it catches a lot of off by one errors. The textbook formal eases this with prime paths. A simple path visits no node twice. A prime path is a simple path that cannot be extended
📄 t=0s · 非课件画面 · t00000s.jpg ⚠️文字少,建议看图
📄 t=12s · p1/6 DEMO1001-testing-loops · t00012s.jpg
    Testing Loops: A Tiny Lecture
    + Demo unit DEMO1001
    - A two-minute synthetic lecture
    + All content in this video is original and free to reuse
📄 t=24s · p2/6 DEMO1001-testing-loops · t00024s.jpg
    Why loops are hard to test
    - A loop body can run zero, one, or many times
    + Each count can hide a different fault
    + Line coverage says nothing about how many times
📄 t=36s · p3/6 DEMO1001-testing-loops · t00036s.jpg
    Loop coverage heuristic
    - Write one test where the body runs 0 times
    * One where it runs exactly once
    * One where it runs more than once
    - This is informal but catches off-by-one errors

[00:01] without repeating a node. Prime path coverage subsumes node coverage and edge coverage. Let us look at a tiny example. While i is less than n, add a of i to the total and increment i with n equal to zero the body never runs. With n equal to one it runs once. With n equal to three it runs three times. Those three tests give you loop coverage. To summarize, test loop counts of zero, one and many, and use prime paths when you need something rigorous. The quiz next week will cover this slide deck, so make sure you can state the definition of a prime path. Thanks. See you next time.
📄 t=60s · p4/6 DEMO1001-testing-loops · t00060s.jpg
    Prime paths, informally
    - Asimple path visits no node twice
    + Aprime path is a simple path that cannot be extended
    + Prime path coverage subsumes node and edge coverage
📄 t=72s · p5/6 DEMO1001-testing-loops · t00072s.jpg
    Worked example
    * while i <n: total += afi]; i+= 1
    *n=0 ->body never runs
    *n=1 ->body runs once
    *n=3 ->body runs three times
📄 t=84s · p6/6 DEMO1001-testing-loops · t00084s.jpg
    * Test loop counts: 0, 1, many
    + Prime paths formalise the idea
    * Quiz next week covers this slide deck

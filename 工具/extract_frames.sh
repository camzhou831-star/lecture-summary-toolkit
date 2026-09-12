#!/usr/bin/env bash
# 从课程视频中抓取幻灯片画面关键帧
# 用法: extract_frames.sh <视频路径> [模式,默认 12s] [输出目录]
#   模式两种:
#     Ns   —— 每 N 秒定点采样,再由 mpdecimate 丢掉与前一帧几乎相同的画面(默认 12s;讲师全屏翻 PDF 时推荐)
#     0.xx —— ffmpeg 场景变化检测阈值(越小截得越多;纯幻灯片 0.10-0.20,带摄像头画面 0.25-0.35)
#            注意:动画逐行出现、鼠标晃动会造成连拍,翻页动作小则会漏页,已知不如定点模式稳
# 产出: <COURSE_ROOT 或 工具/ 的上级目录>/画面/<视频名>/t<秒数>s.jpg(文件名即该帧在视频中的时间点;同一秒多帧时追加 -2、-3)
# 注意: 重跑会先清掉输出目录里上一次的 t*.jpg
set -euo pipefail

in="${1:?用法: extract_frames.sh <视频路径> [Ns|阈值] [输出目录]}"
mode="${2:-12s}"
[ -f "$in" ] || { echo "错误: 找不到文件 $in" >&2; exit 1; }
base="$(basename "${in%.*}")"
root="${COURSE_ROOT:-$(dirname "$(cd "$(dirname "$0")" && pwd)")}"
out="${3:-$root/画面/$base}"
mkdir -p "$out"
tmp="$out/.extract_tmp"
meta="$tmp/times.txt"
trap 'rm -rf "$tmp"' EXIT

if [[ "$mode" =~ ^[1-9][0-9]*s$ ]]; then
  n="${mode%s}"
  echo "== 抓取画面: $in (每 ${n}s 采样 + 去重)"
  vf="fps=1/$n,mpdecimate=hi=64*12:lo=64*5:frac=0.33,metadata=add:key=keep:value=1,metadata=print:file=$meta,scale=1280:-2"
elif [[ "$mode" =~ ^0?\.[0-9]+$ ]]; then
  echo "== 抓取画面: $in (场景检测阈值 $mode)"
  vf="select='eq(n,0)+gt(scene,$mode)',metadata=print:file=$meta,scale=1280:-2"
else
  echo "错误: 模式应为 Ns(如 12s)或 0-1 之间的小数(如 0.20),收到: $mode" >&2; exit 2
fi

# 先抓到临时目录,成功后才替换上一次的帧,失败不破坏旧产物
rm -rf "$tmp"; mkdir -p "$tmp"
if ! ffmpeg -hide_banner -loglevel error -i "$in" -vf "$vf" -fps_mode vfr -q:v 3 "$tmp/raw_%05d.jpg"; then
  echo "错误: ffmpeg 抓帧失败(见上方 ffmpeg 输出),保留上次的帧" >&2; exit 1
fi
if [ ! -s "$meta" ]; then echo "错误: 没有抓到任何帧(视频无画面轨或过短?),保留上次的帧" >&2; exit 1; fi

old=$(find "$out" -maxdepth 1 -name 't*s*.jpg' | wc -l | tr -d ' ')
if [ "$old" -gt 0 ]; then echo "== 清理上次的 $old 帧"; find "$out" -maxdepth 1 -name 't*s*.jpg' -delete; fi

# 按 times.txt 里的 pts_time 把 raw_NNNNN.jpg 重命名为 tXXXXXs.jpg;同一秒多帧时加 -2、-3 后缀
i=0
grep -o 'pts_time:[0-9.]*' "$meta" | cut -d: -f2 | while read -r t; do
  i=$((i+1))
  sec="${t%.*}"
  printf -v name "t%05ds" "$sec"
  target="$out/$name.jpg"; k=1
  while [ -e "$target" ]; do k=$((k+1)); target="$out/$name-$k.jpg"; done
  mv "$tmp/$(printf 'raw_%05d.jpg' "$i")" "$target"
done

n=$(find "$out" -maxdepth 1 -name 't*s*.jpg' | wc -l | tr -d ' ')
echo "== 完成: 共 $n 帧 -> $out"
if [ "$n" -gt 150 ]; then echo "   帧数偏多,可加大采样间隔(如 20s)或提高阈值重跑" >&2; fi

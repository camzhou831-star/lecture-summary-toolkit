# 总结工作台:Windows 一键安装 + 启动(由仓库根目录的 启动工作台.bat 调用)
# Lecture Workbench: one-step setup and launch on Windows (called by 启动工作台.bat / Start Workbench.bat in the package root)
#   用 winget 装缺的 uv / yt-dlp / ffmpeg;用录播课工具自带的 lsk setup 装 whisper.cpp(Vulkan GPU 版 + CPU 备用)、下载语音模型并做 GPU 自检;
#   然后启动工作台并打开浏览器。已经装好的会跳过,可以放心重复运行。不会替你登录任何账号,也不会改你的 API Key。
param([switch]$NoStart)
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = "1"
Set-Location -LiteralPath $PSScriptRoot
$zh = (Get-UICulture).Name -like "zh*"
function Say($cn, $en) { if ($zh) { Write-Host $cn } else { Write-Host $en } }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
# 安装记录:每一步都写进这个文件,出问题时把它发过来就能看到卡在哪
$logDir = Join-Path $env:USERPROFILE ".local\share\lecture-summary-toolkit"
New-Item -ItemType Directory -Force $logDir | Out-Null
$installLog = Join-Path $logDir "install-log.txt"
try { Start-Transcript -Path $installLog -Append | Out-Null } catch {}
# 装的时候不让电脑睡眠(睡着后网会断,下载到一半就失败);窗口开着时一直有效,开着工作台跑长录播也不会被睡眠打断。
# 再关掉命令行窗口的「快速编辑」:不然在窗口里点一下,程序就暂停了,看起来像卡死,要按一下键才继续
$keepAwake = $false
try {
  Add-Type -Namespace WB -Name Native -MemberDefinition @'
[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] public struct REASON { public uint Version; public uint Flags; public string Text; }
[DllImport("kernel32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr PowerCreateRequest(ref REASON r);
[DllImport("kernel32.dll")] public static extern bool PowerSetRequest(IntPtr h, int type);
[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);
[DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int h);
[DllImport("kernel32.dll")] public static extern bool GetConsoleMode(IntPtr h, out uint m);
[DllImport("kernel32.dll")] public static extern bool SetConsoleMode(IntPtr h, uint m);
'@
  $reason = New-Object WB.Native+REASON; $reason.Version = 0; $reason.Flags = 1; $reason.Text = "Lecture Workbench is installing / running"   # POWER_REQUEST_CONTEXT_SIMPLE_STRING
  $script:powerReq = [WB.Native]::PowerCreateRequest([ref]$reason)
  $keepAwake = [WB.Native]::PowerSetRequest($script:powerReq, 1)          # PowerRequestSystemRequired:屏幕可以黑,电脑不睡
  [WB.Native]::SetThreadExecutionState(0x80000001) | Out-Null          # 老办法也设上:ES_CONTINUOUS | ES_SYSTEM_REQUIRED
} catch {}
try {
  $h = [WB.Native]::GetStdHandle(-10); $m = [uint32]0
  if ([WB.Native]::GetConsoleMode($h, [ref]$m)) { [WB.Native]::SetConsoleMode($h, (($m -band (-bnot [uint32]0x40)) -bor [uint32]0x80)) | Out-Null }   # 去掉 QUICK_EDIT,加 EXTENDED_FLAGS
} catch {}
function Stamp { Get-Date -Format "HH:mm:ss" }
function Refresh-Path {
  $links = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $links + ";" + (Join-Path $env:USERPROFILE ".local\bin")
}

Say "== 总结工作台:检查和安装($(Stamp);安装记录:$installLog)" "== Lecture Workbench: checking and installing ($(Stamp); install log: $installLog)"
if (-not $keepAwake) { Say "   (没能阻止电脑自动睡眠;装的时候请别让电脑睡着)" "   (Could not stop the PC from sleeping; please keep it awake while installing)" }
Say "   第一次要下载约 2 GB,网慢的话要半小时以上;下面一直有新的进度就是正常在装,别关窗口" "   The first run downloads about 2 GB and can take over half an hour on a slow connection; as long as new lines keep appearing it is working — keep this window open"
Refresh-Path
if (-not (Have "winget")) {
  Say "没找到 winget(Windows 自带的软件安装器)。请在 Microsoft Store 里安装或更新「应用安装程序 / App Installer」,再双击一次 启动工作台.bat。" `
      "winget (Windows' built-in installer) was not found. Install or update 'App Installer' from the Microsoft Store, then double-click the start file (Start Workbench.bat) again."
  exit 1
}
$pkgs = @(@("uv", "astral-sh.uv"), @("yt-dlp", "yt-dlp.yt-dlp"), @("ffmpeg", "Gyan.FFmpeg"))
foreach ($p in $pkgs) {
  if (Have $p[0]) { Say "   ✓ $($p[0]) 已安装" "   ✓ $($p[0]) installed"; continue }
  Say "   … 安装 $($p[0])($(Stamp))" "   … installing $($p[0]) ($(Stamp))"
  winget install -e --id $p[1] --accept-package-agreements --accept-source-agreements --silent | Out-Host
  Refresh-Path
  if (-not (Have $p[0])) { Say "   ! $($p[0]) 装完还找不到;关掉这个窗口,再双击一次 启动工作台.bat" "   ! $($p[0]) still not found; close this window and double-click Start Workbench.bat again"; exit 1 }
}
# 可选:读视频画面文字(课程总结对课件页码用)。装不上不影响别的功能;课件 PDF 用 Python 包 pypdf 读,不用另装
if (-not (Have "tesseract") -and -not (Test-Path "$env:ProgramFiles\Tesseract-OCR\tesseract.exe")) {
  Say "   … 安装 tesseract(读视频画面文字,可选)" "   … installing tesseract (reads on-screen text; optional)"
  winget install -e --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements --silent | Out-Host
}

Say "== Python 依赖" "== Python dependencies"
uv sync --quiet
if ($LASTEXITCODE -ne 0) { Say "uv sync 失败,见上面的报错" "uv sync failed, see the error above"; exit 1 }

$data = Join-Path $env:USERPROFILE ".local\share\lecture-summary-toolkit"
$model = Join-Path $env:USERPROFILE ".local\share\whisper-models\ggml-large-v3-turbo.bin"
$cli = @("whisper.cpp-b5130-vulkan", "whisper.cpp-b5130-cuda", "whisper.cpp-b5130") | ForEach-Object { Join-Path $data "$_\whisper-cli.exe" } | Where-Object { Test-Path $_ }
if ($cli -and (Test-Path $model)) {
  Say "   ✓ whisper.cpp 和语音模型已安装" "   ✓ whisper.cpp and the speech model are installed"
} else {
  Say "== 转写工具 whisper.cpp + 语音模型(约 1.6 GB,只下一次,会花几分钟)" "== Transcription: whisper.cpp + speech model (about 1.6 GB, downloaded once, takes a few minutes)"
  # 下载进度打在 stderr 上;合进来一起显示并记进安装记录。PowerShell 5 把 stderr 当错误,这一段临时不按错误停
  $ErrorActionPreference = "Continue"
  uv run python ..\工具\lsk.py setup 2>&1 | ForEach-Object { "$_" } | Out-Host   # 工具缺 tesseract 之类时 doctor 会报 ❌,工作台用不到,不算失败
  $ErrorActionPreference = "Stop"
  if (-not (Test-Path $model)) {
    Say "   ! 语音模型没下载完(多半是网断了或电脑睡着了)。工作台照样先打开;处理第一个视频时会再下载,也可以关掉窗口再双击一次 启动工作台.bat 重装" "   ! The speech model did not finish downloading (usually the network dropped or the PC went to sleep). The workbench still opens and retries on your first video; or close this window and double-click Start Workbench.bat again"
  }
}

Say "== 写总结的 AI(三选一)" "== AI for summaries (you need one)"
$ai = $false
if (Have "claude") { Say "   ✓ Claude Code(没登录过的话,运行一次 claude 登录)" "   ✓ Claude Code (run claude once to sign in if you haven't)"; $ai = $true }
if (Have "codex") { Say "   ✓ Codex(没登录过的话,运行一次 codex 登录)" "   ✓ Codex (run codex once to sign in if you haven't)"; $ai = $true }
$cfg = if ($env:WORKBENCH_CONFIG) { $env:WORKBENCH_CONFIG } else { Join-Path $env:USERPROFILE ".config\lecture-workbench\config.json" }
if ((Test-Path $cfg) -or $env:DEEPSEEK_API_KEY -or $env:LLM_API_KEY) { Say "   ✓ 已有 API 配置" "   ✓ API configuration found"; $ai = $true }
if (-not $ai) {
  Say "   还没有。有会员的话不用 API Key,装一个就行(需要先装 Node.js:winget install OpenJS.NodeJS.LTS):" "   None yet. With a paid plan you don't need an API key — install one (needs Node.js first: winget install OpenJS.NodeJS.LTS):"
  Write-Host "     Claude Pro / Max:   npm i -g @anthropic-ai/claude-code; claude"
  Write-Host "     ChatGPT Plus / Pro: npm i -g @openai/codex; codex"
  Say "   工作台照样能打开,首页会提示你。" "   The workbench still opens; its home page will remind you."
}

if ($NoStart) { Say "== 装好了" "== Done"; exit 0 }
$port = if ($env:PORT) { $env:PORT } else { "8770" }
$url = "http://127.0.0.1:$port"
try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "$url/api/config" | Out-Null; Say "== 工作台已经在运行:$url" "== The workbench is already running: $url"; Start-Process $url; exit 0 } catch {}
Say "== 装好了,启动工作台($(Stamp)):$url" "== All set, starting the workbench ($(Stamp)): $url"
Say "   浏览器几秒后会自己打开;没打开的话,自己在浏览器地址栏输入 $url" "   Your browser opens in a few seconds; if it doesn't, type $url into the address bar"
Say "   用工作台的时候这个窗口别关,关掉工作台就停了" "   Keep this window open while you use the workbench; closing it stops the workbench"
try { Stop-Transcript | Out-Null } catch {}
Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 3; Start-Process $u } -ArgumentList $url | Out-Null
uv run python -m wb

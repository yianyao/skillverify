# run-arms.ps1 — gate-D 双跑对照执行脚本（按 agent-skill-quality-ab v1.2 编排协议）
# 用法：在具备 codebuddy CLI 的环境中，于本目录执行  powershell -File run-arms.ps1
# 前置：codebuddy CLI 在 PATH 中；python 可用（用于 grade_ab.py）
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

# 0. CLI 预检
if (-not (Get-Command codebuddy -ErrorAction SilentlyContinue)) {
    Write-Error "codebuddy CLI 不在 PATH 中：无法派出全新子代理进程，双跑将不满足'异臂干净'铁律，拒绝执行。请在具备子代理能力的会话中运行。"
}

# 1. 防污染快照（运行前留痕 sha256，轮后比对）
Get-ChildItem -Recurse -File inputs, prompts, assertions.txt |
    Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLower())  $($_.Path)" } | Set-Content snapshot-before.sha256

# 2. 双臂执行（两个全新进程，互不引用）
codebuddy -p (Get-Content prompts/arm-a-prompt.txt -Raw)
codebuddy -p (Get-Content prompts/arm-b-prompt.txt -Raw)

if (-not (Test-Path outputs/with-skill-report.md))    { Write-Error "Arm-A 未产出报告" }
if (-not (Test-Path outputs/without-skill-report.md)) { Write-Error "Arm-B 未产出报告" }

# 3. 轮后比对快照
Get-ChildItem -Recurse -File inputs, prompts, assertions.txt |
    Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLower())  $($_.Path)" } | Set-Content snapshot-after.sha256
$polluted = Compare-Object (Get-Content snapshot-before.sha256) (Get-Content snapshot-after.sha256)
if ($polluted) { Write-Error "工作区留痕被改动，本轮作废（铁律 1）" }

# 4. 双评盲评：评委1 甲=A/乙=B，评委2 甲=B/乙=A（顺序对调防位置偏差）
$assertions = Get-Content assertions.txt -Raw
$repA = Get-Content outputs/with-skill-report.md -Raw
$repB = Get-Content outputs/without-skill-report.md -Raw
$jp = (Get-Content prompts/judge-prompt.txt -Raw)

$j1 = ($jp -replace '\{ASSERTIONS\}', $assertions) -replace '\{REPORT_X\}', $repA -replace '\{REPORT_Y\}', $repB
$j2 = ($jp -replace '\{ASSERTIONS\}', $assertions) -replace '\{REPORT_X\}', $repB -replace '\{REPORT_Y\}', $repA
codebuddy -p $j1 | Set-Content judge1.json -Encoding UTF8
codebuddy -p $j2 | Set-Content judge2.json -Encoding UTF8
Write-Output "评委产出已落盘 judge1.json / judge2.json —— 请人工核对双评零分歧后再组装 grading.json（有分歧条目升级人工裁决，铁律 2）"

# 5. 防污染收尾：脚本不代填 grading.json 的 passed/evidence，必须由人工从双评 JSON 核对后填入
Write-Output "下一步：人工核对 judge1/judge2 -> 填 grading.json -> python <quality-ab>/scripts/grade_ab.py --grading grading.json --out delta-report.md --cost-a outputs/with-skill-report.md --cost-b outputs/without-skill-report.md"

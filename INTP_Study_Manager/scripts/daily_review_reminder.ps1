$ErrorActionPreference = "SilentlyContinue"

$projectRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $projectRoot "start_intp_study_manager.bat"
$appUrl = "http://localhost:8501"

function Test-StudyManagerRunning {
    try {
        $response = Invoke-WebRequest -Uri $appUrl -UseBasicParsing -TimeoutSec 2
        return [int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500
    } catch {
        return $false
    }
}

if (-not (Test-StudyManagerRunning)) {
    if (Test-Path $startScript) {
        Start-Process -FilePath $startScript -WorkingDirectory $projectRoot
        Start-Sleep -Seconds 5
    }
}

Start-Process $appUrl

Add-Type -AssemblyName PresentationFramework
$message = @"
现在是每日复盘时间。

建议按 INTP 问题驱动学习法完成：
1. 今天学了什么核心问题？
2. 哪些知识点达到 70% 可以前进？
3. 哪些卡点、错因、插问需要进入复习？
4. 是否生成闭卷回忆 Prompt？
"@

[System.Windows.MessageBox]::Show(
    $message,
    "INTP Study Manager 每日复盘提醒",
    "OK",
    "Information"
) | Out-Null

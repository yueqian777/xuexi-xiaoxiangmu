param(
    [int]$Port = 8502
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonCandidates = @(
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
    "D:\SoftwareDownload\python.exe"
)

$PythonExe = $PythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $PythonExe) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        $PythonExe = $PythonCommand.Source
    }
}
if (-not $PythonExe) {
    throw "Python was not found. Install Python or create a project .venv."
}

$BaseUrl = "http://127.0.0.1:$Port"
$HealthUrl = "$BaseUrl/_stcore/health"
$Ready = $false
try {
    $Health = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 1
    $Ready = $Health.StatusCode -eq 200
} catch {
    $Ready = $false
}

if (-not $Ready) {
    $StreamlitArgs = @(
        "-m",
        "streamlit",
        "run",
        "app.py",
        "--server.headless=true",
        "--server.port=$Port"
    )
    Start-Process -FilePath $PythonExe -ArgumentList $StreamlitArgs -WorkingDirectory $ProjectRoot -WindowStyle Minimized | Out-Null
    # Give the server a short head start; the browser can finish loading while
    # Streamlit imports the project. The launcher must return quickly when run
    # from a hidden desktop shortcut.
    for ($Attempt = 0; $Attempt -lt 12; $Attempt++) {
        try {
            $Ready = Test-NetConnection `
                -ComputerName "127.0.0.1" `
                -Port $Port `
                -InformationLevel Quiet `
                -WarningAction SilentlyContinue
        } catch {
            $Ready = $false
        }
        if ($Ready) {
            break
        }
        Start-Sleep -Milliseconds 500
    }
}

Start-Process "$BaseUrl/?page=chatgpt_mcp"

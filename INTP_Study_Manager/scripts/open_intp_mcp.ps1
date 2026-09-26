param(
    [int]$Port = 8501
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

# Reuse the standard app port when it is already running.  Starting the MCP
# shortcut on a second port would create a second Streamlit process against
# the same SQLite/WAL files and makes transient write failures much more
# likely, especially while the data directory is being cloud-synced.
$Ready = $false
$CandidatePorts = @($Port)
if ($Port -eq 8501) {
    # 8502 was used by the first version of the desktop shortcut. Reuse it if
    # it is still the only healthy instance instead of creating another one.
    $CandidatePorts += 8502
}
foreach ($CandidatePort in $CandidatePorts) {
    $CandidateBaseUrl = "http://127.0.0.1:$CandidatePort"
    try {
        $Health = Invoke-WebRequest -Uri "$CandidateBaseUrl/_stcore/health" -UseBasicParsing -TimeoutSec 1
        if ($Health.StatusCode -eq 200) {
            $Port = $CandidatePort
            $BaseUrl = $CandidateBaseUrl
            $Ready = $true
            break
        }
    } catch {
        # Try the next candidate or start a new instance below.
    }
}

if (-not $Ready) {
    $BaseUrl = "http://127.0.0.1:$Port"
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

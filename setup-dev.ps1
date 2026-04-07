[CmdletBinding()]
param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$OverwriteBackendEnv
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Require-Command {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$InstallHint
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found. $InstallHint"
    }
}

function Get-PythonInvocation {
    $candidates = @(
        @{ Command = "python"; Args = @() },
        @{ Command = "py"; Args = @("-3") }
    )

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) {
            continue
        }

        try {
            $versionText = (& $candidate.Command @($candidate.Args + @(
                        "-c",
                        "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
                    ))).Trim()

            if (-not $versionText) {
                continue
            }

            $version = [version]$versionText
            if ($version -lt [version]"3.10") {
                continue
            }

            return @{
                Command = $candidate.Command
                Args = $candidate.Args
                Version = $version
            }
        }
        catch {
            continue
        }
    }

    throw "Python 3.10 or newer is required. Install Python and ensure 'python' or 'py -3' is available in PATH."
}

$repoRoot = $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$backendEnvExample = Join-Path $backendDir ".env.example"
$backendEnvFile = Join-Path $backendDir ".env"
$backendVenvDir = Join-Path $backendDir ".venv"
$backendVenvPython = Join-Path $backendVenvDir "Scripts\python.exe"

if (-not (Test-Path $backendDir)) {
    throw "Backend directory was not found at $backendDir"
}

if (-not (Test-Path $frontendDir)) {
    throw "Frontend directory was not found at $frontendDir"
}

$python = $null
if (-not $SkipBackend) {
    Write-Step "Checking backend prerequisites"
    $python = Get-PythonInvocation
    Write-Host "Using Python $($python.Version) via '$($python.Command)'" -ForegroundColor Green

    if (-not (Test-Path $backendVenvPython)) {
        Write-Step "Creating backend virtual environment"
        Push-Location $backendDir
        try {
            & $python.Command @($python.Args + @("-m", "venv", ".venv"))
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Host "Backend virtual environment already exists at $backendVenvDir" -ForegroundColor DarkYellow
    }

    Write-Step "Installing backend dependencies"
    Push-Location $backendDir
    try {
        & $backendVenvPython -m pip install --upgrade pip
        & $backendVenvPython -m pip install -e .
    }
    finally {
        Pop-Location
    }

    Write-Step "Preparing backend environment file"
    if (-not (Test-Path $backendEnvExample)) {
        throw "Expected backend env template at $backendEnvExample"
    }

    if ((Test-Path $backendEnvFile) -and -not $OverwriteBackendEnv) {
        Write-Host "Preserved existing backend/.env" -ForegroundColor DarkYellow
    }
    else {
        Copy-Item $backendEnvExample $backendEnvFile -Force
        Write-Host "Created backend/.env from .env.example" -ForegroundColor Green
    }
}

if (-not $SkipFrontend) {
    Write-Step "Checking frontend prerequisites"
    Require-Command -Name "npm" -InstallHint "Install Node.js 18+ from https://nodejs.org/ and reopen your terminal."

    Write-Step "Installing frontend dependencies"
    Push-Location $frontendDir
    try {
        if (Test-Path (Join-Path $frontendDir "package-lock.json")) {
            & npm ci
        }
        else {
            & npm install
        }
    }
    finally {
        Pop-Location
    }
}

Write-Step "Setup complete"
Write-Host "Next steps:" -ForegroundColor Green
Write-Host ""
Write-Host "1. Set your provider credentials in backend/.env" -ForegroundColor White
Write-Host "   - DEFAULT_MODEL_PROVIDER=openai or anthropic"
Write-Host "   - OPENAI_API_KEY=... or ANTHROPIC_API_KEY=..."
Write-Host ""
Write-Host "2. Start the backend:" -ForegroundColor White
Write-Host "   cd backend"
Write-Host "   . .\.venv\Scripts\Activate.ps1"
Write-Host "   uvicorn ask_jeremy_backend.main:app --reload"
Write-Host ""
Write-Host "3. Start the frontend in a second terminal:" -ForegroundColor White
Write-Host "   cd frontend"
Write-Host "   npm run dev"
Write-Host ""
Write-Host "4. Open http://localhost:5173" -ForegroundColor White

[CmdletBinding()]
param(
    [string]$PythonPath = '',
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'

function Get-LitePythonInfo {
    # Probe the executable itself; launcher registrations and PATH may disagree.
    param([string]$Executable, [string[]]$LauncherArguments = @())
    $probe = 'import json,sys,tkinter,venv; print(json.dumps(dict(executable=sys.executable,base_executable=sys._base_executable,version=list(sys.version_info[:3]),bits=64 if sys.maxsize>2**32 else 32)))'
    try {
        $raw = & $Executable @LauncherArguments -c $probe 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return ($raw | ConvertFrom-Json)
    } catch { return $null }
}

function Test-LitePythonSupported {
    param($Info)
    return ($null -ne $Info -and $Info.bits -eq 64 -and
        $Info.version[0] -eq 3 -and $Info.version[1] -in @(11, 12))
}

function Resolve-LitePython {
    param([string]$RequestedPath)
    if ($RequestedPath) {
        if (-not (Test-Path -LiteralPath $RequestedPath -PathType Leaf)) {
            throw 'The supplied -PythonPath does not point to a Python executable.'
        }
        $info = Get-LitePythonInfo ((Resolve-Path -LiteralPath $RequestedPath).Path)
        if (-not (Test-LitePythonSupported $info)) {
            throw 'Use an approved 64-bit Python 3.11 or 3.12 installation with tkinter and venv. The supplied executable could not pass that check.'
        }
        return $info
    }
    $launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) {
        foreach ($version in @('-3.12', '-3.11')) {
            $info = Get-LitePythonInfo $launcher.Source @($version)
            if (Test-LitePythonSupported $info) { return $info }
        }
    }
    $onPath = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($onPath) {
        $info = Get-LitePythonInfo $onPath.Source
        if (Test-LitePythonSupported $info) { return $info }
    }
    throw 'No usable 64-bit Python 3.11 or 3.12 with tkinter and venv was found. Run this script with -PythonPath pointing to your approved python.exe.'
}

Push-Location -LiteralPath $PSScriptRoot
try {
    $venvRoot = Join-Path $PSScriptRoot '.venv'
    $venvPython = Join-Path $venvRoot 'Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $selected = Get-LitePythonInfo $venvPython
        if (-not (Test-LitePythonSupported $selected)) {
            throw 'The existing .venv is unusable or has an unsupported Python. Keep your data project; close Lite and repair its app environment or install Lite in a fresh application folder.'
        }
        if ($PythonPath) {
            $requested = Resolve-LitePython $PythonPath
            if (($requested.version -join '.') -ne ($selected.version -join '.') -or
                [IO.Path]::GetFullPath($requested.base_executable) -ne [IO.Path]::GetFullPath($selected.base_executable)) {
                throw 'The existing .venv belongs to a different Python installation. It was left unchanged. To switch Python, close Lite and use a fresh application folder with -PythonPath; keep the same external data project.'
            }
        }
        Write-Output ('Reusing the existing application environment: Python ' + ($selected.version -join '.'))
    } else {
        if (Test-Path -LiteralPath $venvRoot) {
            throw 'An incomplete .venv already exists. It was left unchanged; repair it or install Lite in a fresh application folder.'
        }
        $selected = Resolve-LitePython $PythonPath
        Write-Output ('Selected Python ' + ($selected.version -join '.') + ': ' + $selected.executable)
        if (-not $CheckOnly) {
            & $selected.executable -m venv $venvRoot
            if ($LASTEXITCODE -ne 0) { throw 'Could not create the application environment; check permissions and available disk space.' }
        }
    }
    if ($CheckOnly) {
        Write-Output 'Python compatibility check passed. No environment or dependencies were changed.'
        return
    }
    & $venvPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; check approved network/proxy access. Re-run setup after resolving it; project data is unchanged.' }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Installed dependencies are inconsistent; review the pip check output.' }
    & $venvPython -c 'import tkinter, swotflow_lite.app; from swotflow_lite import __version__; print(__version__)'
    if ($LASTEXITCODE -ne 0) { throw 'The application import check failed. Review the error before launching.' }
    Write-Output 'Ready. Launch Start_SWOTFlow_Lite.cmd. Your GDAL Python is selected separately in Project settings; it need not have the same Python version.'
} finally {
    Pop-Location
}

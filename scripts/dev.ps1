param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('up', 'down', 'logs', 'test', 'test-docs', 'test-rebuild', 'test-fast', 'test-e2e', 'test-api', 'test-unit')]
    [string]$Task,

    [int]$Workers = 4,

    [int]$Slowest = 20,

    [double]$SlowestMinSeconds = 1.0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-DockerCompose {
    param([string[]]$Arguments)

    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao executar: docker compose $($Arguments -join ' ')"
    }
}

function Invoke-DockerComposeRun {
    param([string[]]$Arguments)

    & docker compose run --rm @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao executar: docker compose run --rm $($Arguments -join ' ')"
    }
}

function Invoke-ProjectPython {
    param([string[]]$Arguments)

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & python @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao executar: python $($Arguments -join ' ')"
        }
        return
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & py -3 @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao executar: py -3 $($Arguments -join ' ')"
        }
        return
    }

    Invoke-DockerComposeRun (@('app', 'python') + $Arguments)
}

function Format-Duration {
    param([TimeSpan]$Elapsed)

    if ($Elapsed.TotalHours -ge 1) {
        return "{0:hh\:mm\:ss\.ff}" -f $Elapsed
    }
    if ($Elapsed.TotalMinutes -ge 1) {
        return "{0:mm\:ss\.ff}" -f $Elapsed
    }
    return ("{0:N2}s" -f $Elapsed.TotalSeconds)
}

function Invoke-TimedStep {
    param(
        [string]$Label,
        [scriptblock]$Action
    )

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Host ("`n==> {0}" -f $Label) -ForegroundColor Cyan

    try {
        & $Action | Out-Host
        $stopwatch.Stop()
        $formatted = Format-Duration -Elapsed $stopwatch.Elapsed
        Write-Host ("[OK] {0} ({1})" -f $Label, $formatted) -ForegroundColor Green
        return [pscustomobject]@{
            Label   = $Label
            Elapsed = $stopwatch.Elapsed
        }
    }
    catch {
        $stopwatch.Stop()
        $formatted = Format-Duration -Elapsed $stopwatch.Elapsed
        Write-Host ("[FAIL] {0} ({1})" -f $Label, $formatted) -ForegroundColor Red
        throw
    }
}

function Show-StepSummary {
    param(
        [string]$Task,
        [object[]]$Steps
    )

    if (-not $Steps -or $Steps.Count -eq 0) {
        return
    }

    $totalSeconds = 0.0
    foreach ($step in $Steps) {
        $totalSeconds += $step.Elapsed.TotalSeconds
    }

    Write-Host ("`nResumo da etapa '{0}':" -f $Task) -ForegroundColor Yellow
    foreach ($step in $Steps) {
        $formatted = Format-Duration -Elapsed $step.Elapsed
        Write-Host ("- {0}: {1}" -f $step.Label, $formatted) -ForegroundColor Yellow
    }
    Write-Host ("- Total: {0}" -f ("{0:N2}s" -f $totalSeconds)) -ForegroundColor Yellow
}

function Get-PytestArguments {
    param(
        [string[]]$BaseArguments,
        [int]$Workers,
        [int]$Slowest,
        [double]$SlowestMinSeconds
    )

    $parallelArguments = @()
    if ($Workers -gt 0) {
        $parallelArguments = @('-n', $Workers.ToString())
    }

    $durationArguments = @(
        '--durations', $Slowest.ToString(),
        '--durations-min', $SlowestMinSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    )

    return @('exec', 'app', 'pytest') + $parallelArguments + $BaseArguments + $durationArguments
}

function Get-PytestRunArguments {
    param(
        [string[]]$BaseArguments,
        [int]$Workers,
        [int]$Slowest,
        [double]$SlowestMinSeconds
    )

    $parallelArguments = @()
    if ($Workers -gt 0) {
        $parallelArguments = @('-n', $Workers.ToString())
    }

    $durationArguments = @(
        '--durations', $Slowest.ToString(),
        '--durations-min', $SlowestMinSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    )

    return @('app', 'pytest') + $parallelArguments + $BaseArguments + $durationArguments
}

switch ($Task) {
    'up' {
        $steps = @()
        $steps += Invoke-TimedStep -Label 'docker compose up --build -d' -Action {
            Invoke-DockerCompose @('up', '--build', '-d')
        }
        Show-StepSummary -Task $Task -Steps $steps
    }
    'down' {
        $steps = @()
        $steps += Invoke-TimedStep -Label 'docker compose down' -Action {
            Invoke-DockerCompose @('down')
        }
        Show-StepSummary -Task $Task -Steps $steps
    }
    'logs' {
        $steps = @()
        $steps += Invoke-TimedStep -Label 'docker compose logs -f app' -Action {
            Invoke-DockerCompose @('logs', '-f', 'app')
        }
        Show-StepSummary -Task $Task -Steps $steps
    }
    'test' {
        $steps = @()
        Write-Host ("Configuracao de teste: workers={0}, slowest={1}, durations-min={2}s" -f $Workers, $Slowest, $SlowestMinSeconds) -ForegroundColor DarkCyan
        $steps += Invoke-TimedStep -Label 'pytest suite completa' -Action {
            Invoke-DockerCompose (Get-PytestArguments -BaseArguments @('-q') -Workers $Workers -Slowest $Slowest -SlowestMinSeconds $SlowestMinSeconds)
        }
        Show-StepSummary -Task $Task -Steps $steps
    }
    'test-docs' {
        $steps = @()
        $steps += Invoke-TimedStep -Label 'validador rapido de docs' -Action {
            Invoke-ProjectPython @('scripts/check_docs.py', 'docs')
        }
        Show-StepSummary -Task $Task -Steps $steps
    }
    'test-rebuild' {
        $steps = @()
        Write-Host ("Configuracao de teste: workers={0}, slowest={1}, durations-min={2}s" -f $Workers, $Slowest, $SlowestMinSeconds) -ForegroundColor DarkCyan
        $steps += Invoke-TimedStep -Label 'docker compose down --remove-orphans' -Action {
            Invoke-DockerCompose @('down', '--remove-orphans')
        }
        $steps += Invoke-TimedStep -Label 'docker compose up --build -d --force-recreate --wait' -Action {
            Invoke-DockerCompose @('up', '--build', '-d', '--force-recreate', '--wait')
        }
        $steps += Invoke-TimedStep -Label 'pytest suite completa apos rebuild' -Action {
            Invoke-DockerComposeRun (Get-PytestRunArguments -BaseArguments @('-q') -Workers $Workers -Slowest $Slowest -SlowestMinSeconds $SlowestMinSeconds)
        }
        Show-StepSummary -Task $Task -Steps $steps
    }
    'test-fast' {
        $steps = @()
        Write-Host ("Configuracao de teste: workers={0}, slowest={1}, durations-min={2}s" -f $Workers, $Slowest, $SlowestMinSeconds) -ForegroundColor DarkCyan
        $steps += Invoke-TimedStep -Label 'pytest suite rapida' -Action {
            Invoke-DockerCompose (Get-PytestArguments -BaseArguments @('-q', '-m', 'not e2e') -Workers $Workers -Slowest $Slowest -SlowestMinSeconds $SlowestMinSeconds)
        }
        Show-StepSummary -Task $Task -Steps $steps
    }
    'test-e2e' {
        $steps = @()
        Write-Host ("Configuracao de teste: workers={0}, slowest={1}, durations-min={2}s" -f $Workers, $Slowest, $SlowestMinSeconds) -ForegroundColor DarkCyan
        $steps += Invoke-TimedStep -Label 'pytest e2e' -Action {
            Invoke-DockerCompose (Get-PytestArguments -BaseArguments @('-q', '-s', '-m', 'e2e') -Workers $Workers -Slowest $Slowest -SlowestMinSeconds $SlowestMinSeconds)
        }
        Show-StepSummary -Task $Task -Steps $steps
    }
    'test-api' {
        $steps = @()
        Write-Host ("Configuracao de teste: workers={0}, slowest={1}, durations-min={2}s" -f $Workers, $Slowest, $SlowestMinSeconds) -ForegroundColor DarkCyan
        $steps += Invoke-TimedStep -Label 'pytest API' -Action {
            Invoke-DockerCompose (Get-PytestArguments -BaseArguments @('-q', 'tests/test_api.py') -Workers $Workers -Slowest $Slowest -SlowestMinSeconds $SlowestMinSeconds)
        }
        Show-StepSummary -Task $Task -Steps $steps
    }
    'test-unit' {
        $steps = @()
        Write-Host ("Configuracao de teste: workers={0}, slowest={1}, durations-min={2}s" -f $Workers, $Slowest, $SlowestMinSeconds) -ForegroundColor DarkCyan
        $steps += Invoke-TimedStep -Label 'pytest unitario' -Action {
            Invoke-DockerCompose (Get-PytestArguments -BaseArguments @('-q', 'tests/test_unit_rules.py') -Workers $Workers -Slowest $Slowest -SlowestMinSeconds $SlowestMinSeconds)
        }
        Show-StepSummary -Task $Task -Steps $steps
    }
}

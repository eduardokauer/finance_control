param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('up', 'down', 'logs', 'test', 'test-fast', 'test-e2e', 'test-api', 'test-unit')]
    [string]$Task,

    [int]$Workers = 4
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

function Get-PytestArguments {
    param(
        [string[]]$BaseArguments,
        [int]$Workers
    )

    $parallelArguments = @()
    if ($Workers -gt 0) {
        $parallelArguments = @('-n', $Workers.ToString())
    }

    return @('exec', 'app', 'pytest') + $parallelArguments + $BaseArguments
}

switch ($Task) {
    'up' {
        Invoke-DockerCompose @('up', '--build', '-d')
    }
    'down' {
        Invoke-DockerCompose @('down')
    }
    'logs' {
        Invoke-DockerCompose @('logs', '-f', 'app')
    }
    'test' {
        Invoke-DockerCompose (Get-PytestArguments -BaseArguments @('-vv') -Workers $Workers)
    }
    'test-fast' {
        Invoke-DockerCompose (Get-PytestArguments -BaseArguments @('-vv', '-m', 'not e2e') -Workers $Workers)
    }
    'test-e2e' {
        Invoke-DockerCompose (Get-PytestArguments -BaseArguments @('-vv', '-s', '-m', 'e2e') -Workers $Workers)
    }
    'test-api' {
        Invoke-DockerCompose (Get-PytestArguments -BaseArguments @('-vv', 'tests/test_api.py') -Workers $Workers)
    }
    'test-unit' {
        Invoke-DockerCompose (Get-PytestArguments -BaseArguments @('-vv', 'tests/test_unit_rules.py') -Workers $Workers)
    }
}

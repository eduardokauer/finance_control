Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [string]$Command,
        [string]$FailureMessage
    )

    & powershell -NoProfile -Command $Command
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Get-EnvValue {
    param([string]$Name)

    $envFile = Join-Path $root '.env'
    if (-not (Test-Path $envFile)) {
        throw 'Arquivo .env não encontrado. Copie .env.example para .env antes de rodar.'
    }

    $line = Get-Content -Path $envFile | Where-Object {
        $_ -match "^\s*$Name=" -and -not $_.TrimStart().StartsWith('#')
    } | Select-Object -First 1

    if (-not $line) {
        throw "Variável $Name não encontrada no .env"
    }

    $value = $line.Substring($line.IndexOf('=') + 1).Trim()
    if ($value.StartsWith('"') -and $value.EndsWith('"')) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    return $value
}

function Wait-ForUrl {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 90
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }

    throw "Timeout aguardando $Url"
}

$apiToken = Get-EnvValue 'API_TOKEN'
$adminPassword = Get-EnvValue 'ADMIN_UI_PASSWORD'
$fixturePath = Join-Path $root 'tests/fixtures/ofx/itau_statement_sample.ofx'
$baseUrl = 'http://localhost:8000'

if (-not (Test-Path $fixturePath)) {
    throw "Fixture OFX não encontrado em $fixturePath"
}

Write-Step 'Derrubando stack e zerando o banco local'
Invoke-Checked -Command 'docker compose down -v' -FailureMessage 'Falha ao derrubar a stack local.'

Write-Step 'Subindo stack do zero'
Invoke-Checked -Command 'docker compose up --build -d' -FailureMessage 'Falha ao subir a stack local.'

Write-Step 'Aguardando API responder'
Wait-ForUrl -Url "$baseUrl/health"

Write-Step 'Rodando suíte completa de testes'
Invoke-Checked -Command 'docker compose exec app pytest -q' -FailureMessage 'A suíte completa de testes falhou.'

Write-Step 'Validando health endpoint'
$health = Invoke-RestMethod -Uri "$baseUrl/health" -Method Get
if (-not $health.status) {
    throw 'Health endpoint respondeu sem campo status.'
}

Write-Step 'Validando login e acesso às telas admin'
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -Uri "$baseUrl/admin/login" -Method Get -WebSession $session -UseBasicParsing | Out-Null
Invoke-WebRequest -Uri "$baseUrl/admin/login" -Method Post -Body @{ password = $adminPassword; next = '/admin' } -WebSession $session -UseBasicParsing | Out-Null
$adminHome = Invoke-WebRequest -Uri "$baseUrl/admin" -Method Get -WebSession $session -UseBasicParsing
if ($adminHome.Content -notmatch 'Finance Control Admin') {
    throw 'Falha ao acessar a home admin após login.'
}
Invoke-WebRequest -Uri "$baseUrl/admin/transactions" -Method Get -WebSession $session -UseBasicParsing | Out-Null
Invoke-WebRequest -Uri "$baseUrl/admin/reapply" -Method Get -WebSession $session -UseBasicParsing | Out-Null
Invoke-WebRequest -Uri "$baseUrl/admin/rules" -Method Get -WebSession $session -UseBasicParsing | Out-Null

Write-Step 'Importando OFX real pelo endpoint de ingestão'
$referenceId = "validate-local-$(Get-Date -Format 'yyyyMMddHHmmss')"
$ingestRaw = & curl.exe -sS -X POST "$baseUrl/ingest/bank-statement" -H "Authorization: Bearer $apiToken" -F "file=@$fixturePath;type=application/octet-stream" -F "reference_id=$referenceId"
if ($LASTEXITCODE -ne 0) {
    throw 'Falha ao chamar o endpoint de ingestão.'
}
if (-not $ingestRaw) {
    throw 'Ingestão não retornou corpo.'
}
$ingest = $ingestRaw | ConvertFrom-Json
if ($ingest.status -ne 'processed') {
    throw "Ingestão não retornou status=processed. Resposta: $ingestRaw"
}
if (-not $ingest.period_start -or -not $ingest.period_end) {
    throw 'Ingestão não retornou period_start/period_end.'
}
if (-not $ingest.source_file_id) {
    throw 'Ingestão não retornou source_file_id.'
}

Write-Step 'Validando integração do endpoint /analysis/llm-email'
$analysisPayload = @{
    period_start = $ingest.period_start
    period_end = $ingest.period_end
    trigger_source_file_id = $ingest.source_file_id
} | ConvertTo-Json
$analysis = Invoke-RestMethod -Uri "$baseUrl/analysis/llm-email" -Method Post -Headers @{ Authorization = "Bearer $apiToken" } -ContentType 'application/json' -Body $analysisPayload
if (-not $analysis.summary_html) {
    throw 'analysis/llm-email não retornou summary_html.'
}
if (-not $analysis.llm_payload) {
    throw 'analysis/llm-email não retornou llm_payload.'
}

Write-Step 'Validando acesso admin após importação'
$transactionsPage = Invoke-WebRequest -Uri "$baseUrl/admin/transactions" -Method Get -WebSession $session -UseBasicParsing
if ($transactionsPage.StatusCode -ne 200) {
    throw 'Falha ao acessar a listagem de lançamentos após importação.'
}

Write-Host "`nValidação completa concluída com sucesso." -ForegroundColor Green
Write-Host "- Stack reiniciada com banco zerado" -ForegroundColor Green
Write-Host "- Pytest completo executado" -ForegroundColor Green
Write-Host "- Login admin validado" -ForegroundColor Green
Write-Host "- Ingestão OFX validada" -ForegroundColor Green
Write-Host "- analysis/llm-email validado" -ForegroundColor Green

# B2B Lead Qualifier - End-to-End Demonstration Script (PowerShell)
# Simulates a multi-turn conversation and queries the leads endpoint.

param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$ApiKey = $(if ($env:API_KEY) { $env:API_KEY } else { "b2b_live_demo_acme_111111111111111111111111" })
)

$ErrorActionPreference = "Stop"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " B2B Lead Qualifier - End-to-End Interactive Demonstration" -ForegroundColor Cyan
Write-Host " Target API: $ApiBaseUrl" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Healthcheck
Write-Host "[1/4] Checking API Health..." -ForegroundColor Yellow
try {
    $health = Invoke-RestMethod -Uri "$ApiBaseUrl/health" -Method Get
    Write-Host "   Status:   $($health.status)" -ForegroundColor Green
    Write-Host "   Database: $($health.database)" -ForegroundColor Green
} catch {
    Write-Host "   ERROR: API is unreachable at $ApiBaseUrl. Make sure the server is running." -ForegroundColor Red
    exit 1
}
Write-Host ""

$headers = @{
    "Authorization" = "Bearer $ApiKey"
    "Content-Type"  = "application/json"
}

# 2. Turn 1: Lead introduces job role (CEO)
$msgId1 = "demo_msg_001_" + [guid]::NewGuid().ToString("N").Substring(0, 8)
Write-Host "[2/4] Sending Turn 1 (Lead introduces role: CEO)..." -ForegroundColor Yellow
$bodyTurn1 = @{
    message_id   = $msgId1
    phone_number = "+5511999998888"
    user_message = "Ola! Sou CEO de uma empresa de tecnologia."
} | ConvertTo-Json

Write-Host "   Inbound Message: 'Ola! Sou CEO de uma empresa de tecnologia.'" -ForegroundColor Gray
$resTurn1 = Invoke-RestMethod -Uri "$ApiBaseUrl/v1/conversations/turns" -Method Post -Headers $headers -Body $bodyTurn1
Write-Host "   State Machine:   $($resTurn1.current_state)" -ForegroundColor Green
Write-Host "   Is Finished:     $($resTurn1.is_finished)" -ForegroundColor Green
Write-Host "   Assistant Reply: '$($resTurn1.reply_message)'" -ForegroundColor White
Write-Host "   Response Payload (JSON):" -ForegroundColor Gray
Write-Host ($resTurn1 | ConvertTo-Json -Depth 5) -ForegroundColor DarkGray
Write-Host ""

# 3. Turn 2: Lead provides revenue bracket (5M/year -> tier 2m_to_10m)
$msgId2 = "demo_msg_002_" + [guid]::NewGuid().ToString("N").Substring(0, 8)
Write-Host "[3/4] Sending Turn 2 (Lead provides revenue: 5M/year)..." -ForegroundColor Yellow
$bodyTurn2 = @{
    message_id   = $msgId2
    phone_number = "+5511999998888"
    user_message = "Nosso faturamento anual fica em torno de 5 milhoes ao ano."
} | ConvertTo-Json

Write-Host "   Inbound Message: 'Nosso faturamento anual fica em torno de 5 milhoes ao ano.'" -ForegroundColor Gray
$resTurn2 = Invoke-RestMethod -Uri "$ApiBaseUrl/v1/conversations/turns" -Method Post -Headers $headers -Body $bodyTurn2
Write-Host "   State Machine:   $($resTurn2.current_state)" -ForegroundColor Green
Write-Host "   Is Finished:     $($resTurn2.is_finished)" -ForegroundColor Green
Write-Host "   Assistant Reply: '$($resTurn2.reply_message)'" -ForegroundColor White
Write-Host "   Response Payload (JSON):" -ForegroundColor Gray
Write-Host ($resTurn2 | ConvertTo-Json -Depth 5) -ForegroundColor DarkGray
Write-Host ""

# 4. Fetch evaluated leads from API
Write-Host "[4/4] Fetching Evaluated Leads from GET /v1/leads..." -ForegroundColor Yellow
$leadsRes = Invoke-RestMethod -Uri "$ApiBaseUrl/v1/leads" -Method Get -Headers $headers

if ($leadsRes.leads.Count -gt 0) {
    $latest = $leadsRes.leads[0]
    Write-Host "   Lead Phone:    $($latest.phone_number)" -ForegroundColor White
    Write-Host "   Verdict:       $(if ($latest.is_qualified) { 'QUALIFIED' } else { 'DISQUALIFIED' })" -ForegroundColor $(if ($latest.is_qualified) { 'Green' } else { 'Red' })
    Write-Host "   Final Score:   $($latest.final_score) pts" -ForegroundColor White
    Write-Host "   Reasons:" -ForegroundColor Cyan
    foreach ($reason in $latest.reasons) {
        Write-Host "     - $reason" -ForegroundColor Gray
    }
    Write-Host ""
    Write-Host "   Formatted Leads Payload (JSON):" -ForegroundColor Gray
    Write-Host ($leadsRes | ConvertTo-Json -Depth 5) -ForegroundColor DarkGray
} else {
    Write-Host "   No leads found." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " Demonstration complete. View in dashboard: $ApiBaseUrl/dashboard" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

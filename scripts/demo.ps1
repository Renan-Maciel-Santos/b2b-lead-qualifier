# B2B Lead Qualifier - End-to-End Demonstration Script (PowerShell)
# Simulates 3 real business scenarios according to active scoring rules:
#   1. Qualified Lead: CEO + 5M revenue (85 pts >= 50 cutoff)
#   2. Not Qualified Lead: Gerente + 1M revenue (25 pts < 50 cutoff)
#   3. Disqualified Lead (Knockout): Estudante (Immediate disqualification)

param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$ApiKey = $(if ($env:API_KEY) { $env:API_KEY } else { "b2b_live_demo_acme_111111111111111111111111" })
)

$ErrorActionPreference = "Stop"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " B2B Lead Qualifier - End-to-End Interactive Demonstration (3 Scenarios)" -ForegroundColor Cyan
Write-Host " Target API: $ApiBaseUrl" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Healthcheck
Write-Host "[1/5] Checking API Health..." -ForegroundColor Yellow
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

# 2. Scenario 1: Qualified Lead (+5511999991111) - CEO + 5M/year
Write-Host "[2/5] Simulating Lead 1 (Expected: QUALIFIED - 85 pts)..." -ForegroundColor Yellow
$lead1Phone = "+5511999991111"
$msg1a = "demo_msg_1a_" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$body1a = @{
    message_id   = $msg1a
    phone_number = $lead1Phone
    user_message = "Ola! Sou CEO de uma empresa de tecnologia."
} | ConvertTo-Json
$res1a = Invoke-RestMethod -Uri "$ApiBaseUrl/v1/conversations/turns" -Method Post -Headers $headers -Body $body1a
Write-Host "   Turn 1 (Role: CEO): State=$($res1a.current_state), Finished=$($res1a.is_finished)" -ForegroundColor Gray

$msg1b = "demo_msg_1b_" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$body1b = @{
    message_id   = $msg1b
    phone_number = $lead1Phone
    user_message = "Nosso faturamento anual fica em torno de 5 milhoes ao ano."
} | ConvertTo-Json
$res1b = Invoke-RestMethod -Uri "$ApiBaseUrl/v1/conversations/turns" -Method Post -Headers $headers -Body $body1b
Write-Host "   Turn 2 (Revenue: 5M): State=$($res1b.current_state), Finished=$($res1b.is_finished)" -ForegroundColor Green
Write-Host ""

# 3. Scenario 2: Insufficient Score (+5511999992222) - Gerente + 1M/year
Write-Host "[3/5] Simulating Lead 2 (Expected: NOT_QUALIFIED - 25 pts)..." -ForegroundColor Yellow
$lead2Phone = "+5511999992222"
$msg2a = "demo_msg_2a_" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$body2a = @{
    message_id   = $msg2a
    phone_number = $lead2Phone
    user_message = "Ola, sou Gerente de projetos."
} | ConvertTo-Json
$res2a = Invoke-RestMethod -Uri "$ApiBaseUrl/v1/conversations/turns" -Method Post -Headers $headers -Body $body2a
Write-Host "   Turn 1 (Role: Gerente): State=$($res2a.current_state), Finished=$($res2a.is_finished)" -ForegroundColor Gray

$msg2b = "demo_msg_2b_" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$body2b = @{
    message_id   = $msg2b
    phone_number = $lead2Phone
    user_message = "Nosso faturamento atual e de 1 milhao por ano."
} | ConvertTo-Json
$res2b = Invoke-RestMethod -Uri "$ApiBaseUrl/v1/conversations/turns" -Method Post -Headers $headers -Body $body2b
Write-Host "   Turn 2 (Revenue: 1M): State=$($res2b.current_state), Finished=$($res2b.is_finished)" -ForegroundColor Yellow
Write-Host ""

# 4. Scenario 3: Knockout Disqualification (+5511999993333) - Estudante
Write-Host "[4/5] Simulating Lead 3 (Expected: DISQUALIFIED by Knockout)..." -ForegroundColor Yellow
$lead3Phone = "+5511999993333"
$msg3a = "demo_msg_3a_" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$body3a = @{
    message_id   = $msg3a
    phone_number = $lead3Phone
    user_message = "Ola, sou estudante universitario e gostaria de conhecer."
} | ConvertTo-Json
$res3a = Invoke-RestMethod -Uri "$ApiBaseUrl/v1/conversations/turns" -Method Post -Headers $headers -Body $body3a
Write-Host "   Turn 1 (Role: Estudante): State=$($res3a.current_state), Finished=$($res3a.is_finished)" -ForegroundColor Red
Write-Host ""

# 5. Fetch evaluated leads from API
Write-Host "[5/5] Fetching Evaluated Leads from GET /v1/leads..." -ForegroundColor Yellow
$leadsRes = Invoke-RestMethod -Uri "$ApiBaseUrl/v1/leads" -Method Get -Headers $headers

if ($leadsRes.leads.Count -gt 0) {
    Write-Host "   Total Leads Evaluated: $($leadsRes.leads.Count)" -ForegroundColor Green
    foreach ($lead in $leadsRes.leads) {
        $statusLabel = if ($lead.is_qualified) { "QUALIFIED" } else { "NOT_QUALIFIED" }
        Write-Host "   ------------------------------------------------------------" -ForegroundColor Gray
        Write-Host "   Phone:       $($lead.phone_number)" -ForegroundColor White
        Write-Host "   Verdict:     $statusLabel" -ForegroundColor $(if ($lead.is_qualified) { "Green" } else { "Red" })
        Write-Host "   Score:       $($lead.final_score) / $($lead.max_possible_score) pts (Cutoff: $($lead.qualification_threshold) pts)" -ForegroundColor White
        Write-Host "   Audit Trail:" -ForegroundColor Cyan
        foreach ($r in $lead.reasons) {
            if ($r.rule_type -eq "knockout") {
                Write-Host "     - [KNOCKOUT] $($r.field) matches restricted value '$($r.value)'" -ForegroundColor Red
            } else {
                Write-Host "     - [+$($r.points) pts] $($r.field) = $($r.value)" -ForegroundColor Gray
            }
        }
    }
} else {
    Write-Host "   No leads found." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " Demonstration complete. View in dashboard: $ApiBaseUrl/dashboard" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

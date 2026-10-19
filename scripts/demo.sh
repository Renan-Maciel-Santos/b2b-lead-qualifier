#!/usr/bin/env bash
# B2B Lead Qualifier - End-to-End Demonstration Script (Bash)
# Simulates 3 real business scenarios according to active scoring rules:
#   1. Qualified Lead: CEO + 5M revenue (85 pts >= 50 cutoff)
#   2. Not Qualified Lead: Gerente + 1M revenue (25 pts < 50 cutoff)
#   3. Disqualified Lead (Knockout): Estudante (Immediate disqualification)

set -euo pipefail

API_BASE_URL="${1:-http://127.0.0.1:8000}"
API_KEY="${2:-${API_KEY:-b2b_live_demo_acme_111111111111111111111111}}"

echo "================================================================================"
echo " B2B Lead Qualifier - End-to-End Interactive Demonstration (3 Scenarios)"
echo " Target API: $API_BASE_URL"
echo "================================================================================"
echo ""

# Helper to format JSON payload if python or jq is available
format_json() {
    if command -v python3 >/dev/null 2>&1; then
        python3 -m json.tool 2>/dev/null || cat
    elif command -v jq >/dev/null 2>&1; then
        jq . 2>/dev/null || cat
    else
        cat
    fi
}

# 1. Healthcheck
echo "[1/5] Checking API Health..."
if ! curl -s -f "$API_BASE_URL/health" > /dev/null; then
    echo "   ERROR: API is unreachable at $API_BASE_URL. Make sure the server is running."
    exit 1
fi
HEALTH=$(curl -s "$API_BASE_URL/health")
echo "   Response:"
echo "$HEALTH" | format_json
echo ""

# 2. Scenario 1: Qualified Lead (+5511999991111) - CEO + 5M/year
echo "[2/5] Simulating Lead 1 (Expected: QUALIFIED - 85 pts)..."
MSG_1A="demo_msg_1a_$(date +%s)_$RANDOM"
curl -s -X POST "$API_BASE_URL/v1/conversations/turns" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"message_id\": \"$MSG_1A\", \"phone_number\": \"+5511999991111\", \"user_message\": \"Ola! Sou CEO de uma empresa de tecnologia.\"}" > /dev/null

MSG_1B="demo_msg_1b_$(date +%s)_$RANDOM"
RES_1B=$(curl -s -X POST "$API_BASE_URL/v1/conversations/turns" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"message_id\": \"$MSG_1B\", \"phone_number\": \"+5511999991111\", \"user_message\": \"Nosso faturamento anual fica em torno de 5 milhoes ao ano.\"}")
echo "   Turn 2 Output:"
echo "$RES_1B" | format_json
echo ""

# 3. Scenario 2: Insufficient Score (+5511999992222) - Gerente + 1M/year
echo "[3/5] Simulating Lead 2 (Expected: NOT_QUALIFIED - 25 pts)..."
MSG_2A="demo_msg_2a_$(date +%s)_$RANDOM"
curl -s -X POST "$API_BASE_URL/v1/conversations/turns" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"message_id\": \"$MSG_2A\", \"phone_number\": \"+5511999992222\", \"user_message\": \"Ola, sou Gerente de projetos.\"}" > /dev/null

MSG_2B="demo_msg_2b_$(date +%s)_$RANDOM"
RES_2B=$(curl -s -X POST "$API_BASE_URL/v1/conversations/turns" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"message_id\": \"$MSG_2B\", \"phone_number\": \"+5511999992222\", \"user_message\": \"Nosso faturamento atual e de 1 milhao por ano.\"}")
echo "   Turn 2 Output:"
echo "$RES_2B" | format_json
echo ""

# 4. Scenario 3: Knockout Disqualification (+5511999993333) - Estudante
echo "[4/5] Simulating Lead 3 (Expected: DISQUALIFIED by Knockout)..."
MSG_3A="demo_msg_3a_$(date +%s)_$RANDOM"
RES_3A=$(curl -s -X POST "$API_BASE_URL/v1/conversations/turns" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"message_id\": \"$MSG_3A\", \"phone_number\": \"+5511999993333\", \"user_message\": \"Ola, sou estudante universitario e gostaria de conhecer.\"}")
echo "   Turn 1 Output (Terminal Knockout):"
echo "$RES_3A" | format_json
echo ""

# 5. Fetch evaluated leads from API
echo "[5/5] Fetching Evaluated Leads from GET /v1/leads..."
LEADS_RES=$(curl -s -X GET "$API_BASE_URL/v1/leads" \
    -H "Authorization: Bearer $API_KEY")
echo "   Formatted Leads Payload (JSON):"
echo "$LEADS_RES" | format_json
echo ""

echo "================================================================================"
echo " Demonstration complete. View in dashboard: $API_BASE_URL/dashboard"
echo "================================================================================"

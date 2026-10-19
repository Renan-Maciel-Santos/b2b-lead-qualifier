#!/usr/bin/env bash
# B2B Lead Qualifier - End-to-End Demonstration Script (Bash)
# Simulates a multi-turn conversation and queries the leads endpoint.

set -euo pipefail

API_BASE_URL="${1:-http://127.0.0.1:8000}"
API_KEY="${2:-${API_KEY:-b2b_live_demo_acme_111111111111111111111111}}"

echo "================================================================================"
echo " B2B Lead Qualifier - End-to-End Interactive Demonstration"
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
echo "[1/4] Checking API Health..."
if ! curl -s -f "$API_BASE_URL/health" > /dev/null; then
    echo "   ERROR: API is unreachable at $API_BASE_URL. Make sure the server is running."
    exit 1
fi
HEALTH=$(curl -s "$API_BASE_URL/health")
echo "   Response:"
echo "$HEALTH" | format_json
echo ""

# 2. Turn 1: Lead introduces role
MSG_ID_1="demo_msg_001_$(date +%s)_$RANDOM"
echo "[2/4] Sending Turn 1 (Lead introduces role: CEO)..."
echo "   Inbound Message: 'Ola! Sou CEO de uma empresa de tecnologia.'"
RES_TURN_1=$(curl -s -X POST "$API_BASE_URL/v1/conversations/turns" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{
        \"message_id\": \"$MSG_ID_1\",
        \"phone_number\": \"+5511999998888\",
        \"user_message\": \"Ola! Sou CEO de uma empresa de tecnologia.\"
    }")
echo "   Response Payload (JSON):"
echo "$RES_TURN_1" | format_json
echo ""

# 3. Turn 2: Lead provides revenue bracket
MSG_ID_2="demo_msg_002_$(date +%s)_$RANDOM"
echo "[3/4] Sending Turn 2 (Lead provides revenue: 5M/year)..."
echo "   Inbound Message: 'Nosso faturamento anual fica em torno de 5 milhoes ao ano.'"
RES_TURN_2=$(curl -s -X POST "$API_BASE_URL/v1/conversations/turns" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{
        \"message_id\": \"$MSG_ID_2\",
        \"phone_number\": \"+5511999998888\",
        \"user_message\": \"Nosso faturamento anual fica em torno de 5 milhoes ao ano.\"
    }")
echo "   Response Payload (JSON):"
echo "$RES_TURN_2" | format_json
echo ""

# 4. Fetch evaluated leads from API
echo "[4/4] Fetching Evaluated Leads from GET /v1/leads..."
LEADS_RES=$(curl -s -X GET "$API_BASE_URL/v1/leads" \
    -H "Authorization: Bearer $API_KEY")
echo "   Formatted Leads Payload (JSON):"
echo "$LEADS_RES" | format_json
echo ""

echo "================================================================================"
echo " Demonstration complete. View in dashboard: $API_BASE_URL/dashboard"
echo "================================================================================"

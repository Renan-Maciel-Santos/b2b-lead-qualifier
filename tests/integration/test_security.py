"""Integration tests verifying API key authentication, cross-tenant isolation, and XSS prevention."""

import os
import uuid
from uuid import UUID

import pytest
from httpx import AsyncClient
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.core.database import tenant_transaction
from lead_qualifier.core.security import hash_api_key
from lead_qualifier.core.tenant import TenantContext
from lead_qualifier.repositories.conversation_repo import ConversationRepository
from tests.conftest import (
    API_KEY_INVASOR,
    API_KEY_READONLY,
    API_KEY_TEST,
    API_KEY_WEBHOOK_ONLY,
    TENANT_TEST,
    set_test_tenant_context,
)

pytestmark = pytest.mark.asyncio


async def test_unauthenticated_request_returns_401(api_client: AsyncClient) -> None:
    """Verify that requests without an Authorization header return HTTP 401."""
    response = await api_client.get("/v1/leads")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing API key."

    turn_payload = {
        "message_id": "msg_unauth_001",
        "phone_number": "+5511999991111",
        "user_message": "Ola",
    }
    response = await api_client.post("/v1/conversations/turns", json=turn_payload)
    assert response.status_code == 401


async def test_invalid_and_malformed_api_key_returns_401(api_client: AsyncClient) -> None:
    """Verify that forged, malformed, or invalid Bearer tokens return HTTP 401."""
    # Invalid token string
    headers = {"Authorization": "Bearer b2b_live_non_existent_key_999999999"}
    response = await api_client.get("/v1/leads", headers=headers)
    assert response.status_code == 401

    # Malformed header scheme (Basic instead of Bearer)
    headers = {"Authorization": "Basic dXNlcjpwYXNz"}
    response = await api_client.get("/v1/leads", headers=headers)
    assert response.status_code == 401

    # Empty token
    headers = {"Authorization": "Bearer "}
    response = await api_client.get("/v1/leads", headers=headers)
    assert response.status_code == 401


async def test_revoked_api_key_returns_401(
    api_client: AsyncClient,
    db_admin: AsyncConnection,
) -> None:
    """Verify that an API key with a non-null revoked_at timestamp is rejected with HTTP 401."""
    test_key_hash = hash_api_key(API_KEY_TEST)

    # Revoke the test key
    async with db_admin.cursor() as cur:
        await cur.execute(
            "UPDATE core.api_keys SET revoked_at = now() WHERE key_hash = %s",
            (test_key_hash,),
        )
        await db_admin.commit()

    headers = {"Authorization": f"Bearer {API_KEY_TEST}"}
    response = await api_client.get("/v1/leads", headers=headers)
    assert response.status_code == 401

    # Restore key for subsequent tests
    async with db_admin.cursor() as cur:
        await cur.execute(
            "UPDATE core.api_keys SET revoked_at = NULL WHERE key_hash = %s",
            (test_key_hash,),
        )
        await db_admin.commit()


async def test_cross_tenant_isolation_via_api_key(
    api_client: AsyncClient,
    db_admin: AsyncConnection,
) -> None:
    """Verify that an API key belonging to Tenant B cannot access Tenant A's lead data."""
    # Seed a lead directly in Tenant A (Test)
    await set_test_tenant_context(db_admin, TENANT_TEST, "tenant_test")
    async with db_admin.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO scoring_results (phone_number, rule_set_id, final_score, is_qualified, audit_trail)
            VALUES (
                '+5511988887777',
                (SELECT id FROM tenant_test.scoring_rule_sets WHERE is_active = true LIMIT 1),
                100,
                true,
                '["Test qualification"]'::jsonb
            )
            """
        )
        await db_admin.commit()

    # Request leads using Tenant A's key -> must see the lead
    headers_a = {"Authorization": f"Bearer {API_KEY_TEST}"}
    response_a = await api_client.get("/v1/leads", headers=headers_a)
    assert response_a.status_code == 200
    leads_a = response_a.json()["leads"]
    assert any(lead["phone_number"] == "+5511988887777" for lead in leads_a)

    # Request leads using Tenant B's (Attacker) key -> must NOT see Tenant A's lead
    headers_b = {"Authorization": f"Bearer {API_KEY_INVASOR}"}
    response_b = await api_client.get("/v1/leads", headers=headers_b)
    assert response_b.status_code == 200
    leads_b = response_b.json()["leads"]
    assert not any(lead["phone_number"] == "+5511988887777" for lead in leads_b)


async def test_dashboard_template_contains_no_innerhtml_with_lead_data(
    api_client: AsyncClient,
) -> None:
    """Verify that the dashboard template renders safely without innerHTML for user data."""
    response = await api_client.get("/dashboard")
    assert response.status_code == 200
    html = response.text

    # Anti-XSS validation: table body must not contain dynamic innerHTML interpolation
    assert "tbody.innerHTML = ` " not in html
    assert "document.createElement" in html
    assert "textContent" in html


async def test_get_dashboard_returns_200(api_client: AsyncClient) -> None:
    """Verify that GET /dashboard renders the dashboard template publicly without lead data,

    while data endpoint GET /v1/leads strictly requires authentication (HTTP 401).
    """
    # 1. GET /dashboard without Authorization header returns HTTP 200
    response = await api_client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    html = response.text

    # The rendered HTML page must be a public skeleton and contain zero lead records in the markup
    assert "+55" not in html
    assert "<tr><td>" not in html
    assert '<tbody id="leadsTableBody">\n                    </tbody>' in html

    # 2. GET /v1/leads without Authorization header returns HTTP 401
    leads_response = await api_client.get("/v1/leads")
    assert leads_response.status_code == 401
    assert leads_response.json()["detail"] == "Invalid or missing API key."


async def test_app_user_denied_direct_select_on_core_api_keys(
    db_app: AsyncConnection,
) -> None:
    """Verify that app_user cannot execute direct SELECT on core.api_keys (least privilege),

    while resolution via core.resolve_tenant_by_api_key continues functioning.
    """
    import hashlib

    from psycopg.errors import InsufficientPrivilege

    # 1. Direct SELECT on core.api_keys must fail with InsufficientPrivilege (permission denied)
    with pytest.raises(InsufficientPrivilege):
        async with db_app.cursor() as cur:
            await cur.execute("SELECT * FROM core.api_keys")

    # Rollback transaction poisoned by the permission error
    await db_app.rollback()

    # 2. Key resolution via the SECURITY DEFINER function must succeed for app_user
    key_hash = hashlib.sha256(API_KEY_TEST.encode("utf-8")).hexdigest()
    async with db_app.cursor() as cur:
        await cur.execute(
            "SELECT tenant_id, schema_name, scopes FROM core.resolve_tenant_by_api_key(%s)",
            (key_hash,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[1] == "tenant_test"
        assert set(row[2]) == {"webhook:write", "leads:read"}


async def test_no_tenant_context_leakage_across_pool_checkouts(
    _setup_test_tenants: None,
) -> None:
    """Prove that tenant context does not leak between pool checkouts (fail-closed RLS).

    Uses a pool with max_size=1. First executes a unit of work for Tenant A that
    persists a conversation state. Then, checks out the exact same connection from the
    pool outside of any unit of work and executes a query.
    RLS must evaluate to closed (zero rows returned), never leaking Tenant A data.
    """
    tenant_a_ctx = TenantContext(UUID(TENANT_TEST), "tenant_test")
    phone = f"+55119{uuid.uuid4().int % 100000000:08d}"

    app_user = os.getenv("DB_USER", "app_user")
    app_pwd = os.getenv("DB_PASSWORD", "secret")
    db_name = os.getenv("DB_NAME", "b2b_lead_qualifier")
    conn_str = f"postgresql://{app_user}:{app_pwd}@127.0.0.1:5432/{db_name}?connect_timeout=3"

    pool_single = AsyncConnectionPool(conninfo=conn_str, min_size=1, max_size=1, open=False)
    await pool_single.open()

    try:
        # Step 1: Execute unit of work for Tenant A to write state
        async with tenant_transaction(pool_single, tenant_a_ctx) as conn_a:
            repo_a = ConversationRepository(conn_a)
            await repo_a.save_conversation_state(
                phone_number=phone,
                current_state="QUALIFIED",
                accumulated_slots={"role": "CEO", "revenue": "5M"},
            )

        # Step 2: Acquire the SAME connection from the pool outside of any unit of work
        async with (
            pool_single.connection() as raw_conn,
            raw_conn.cursor() as cur,
        ):
            # Query tenant_test's table directly without tenant transaction
            await cur.execute(
                "SELECT phone_number, current_state FROM tenant_test.conversation_states WHERE phone_number = %s",
                (phone,),
            )
            rows = await cur.fetchall()

            # RLS must fail-closed: exactly zero rows returned, never Tenant A data
            assert len(rows) == 0

            # Verify that app.current_tenant GUC is empty or reset
            await cur.execute("SELECT current_setting('app.current_tenant', true)")
            guc_val = await cur.fetchone()
            assert guc_val is None or guc_val[0] is None or guc_val[0] == ""
    finally:
        await pool_single.close()


async def test_scope_enforcement_webhook_requires_webhook_write(
    api_client: AsyncClient,
) -> None:
    """Verify that an API key with only leads:read receives HTTP 403 on conversation turn webhook."""
    headers = {"Authorization": f"Bearer {API_KEY_READONLY}"}
    payload = {
        "message_id": "msg_scope_001",
        "phone_number": "+5511999990001",
        "user_message": "Ola",
    }
    response = await api_client.post("/v1/conversations/turns", json=payload, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden"


async def test_scope_enforcement_leads_requires_leads_read(
    api_client: AsyncClient,
) -> None:
    """Verify that an API key with only webhook:write receives HTTP 403 on GET /v1/leads."""
    headers = {"Authorization": f"Bearer {API_KEY_WEBHOOK_ONLY}"}
    response = await api_client.get("/v1/leads", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden"

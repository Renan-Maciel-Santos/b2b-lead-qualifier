"""Integration tests verifying API key authentication, cross-tenant isolation, and XSS prevention."""

import pytest
from httpx import AsyncClient
from psycopg import AsyncConnection

from lead_qualifier.core.security import hash_api_key
from tests.conftest import (
    API_KEY_DEMO,
    API_KEY_INVASOR,
    TENANT_DEMO,
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
    demo_key_hash = hash_api_key(API_KEY_DEMO)

    # Revoke the demo key
    async with db_admin.cursor() as cur:
        await cur.execute(
            "UPDATE core.api_keys SET revoked_at = now() WHERE key_hash = %s",
            (demo_key_hash,),
        )
        await db_admin.commit()

    headers = {"Authorization": f"Bearer {API_KEY_DEMO}"}
    response = await api_client.get("/v1/leads", headers=headers)
    assert response.status_code == 401

    # Restore key for subsequent tests
    async with db_admin.cursor() as cur:
        await cur.execute(
            "UPDATE core.api_keys SET revoked_at = NULL WHERE key_hash = %s",
            (demo_key_hash,),
        )
        await db_admin.commit()


async def test_cross_tenant_isolation_via_api_key(
    api_client: AsyncClient,
    db_admin: AsyncConnection,
) -> None:
    """Verify that an API key belonging to Tenant B cannot access Tenant A's lead data."""
    # Seed a lead directly in Tenant A (Demo)
    await set_test_tenant_context(db_admin, TENANT_DEMO, "tenant_demo")
    async with db_admin.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO scoring_results (phone_number, rule_set_id, final_score, is_qualified, audit_trail)
            VALUES (
                '+5511988887777',
                (SELECT id FROM tenant_demo.scoring_rule_sets WHERE is_active = true LIMIT 1),
                100,
                true,
                '["Test qualification"]'::jsonb
            )
            """
        )
        await db_admin.commit()

    # Request leads using Tenant A's key -> must see the lead
    headers_a = {"Authorization": f"Bearer {API_KEY_DEMO}"}
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
    key_hash = hashlib.sha256(API_KEY_DEMO.encode("utf-8")).hexdigest()
    async with db_app.cursor() as cur:
        await cur.execute(
            "SELECT tenant_id, schema_name FROM core.resolve_tenant_by_api_key(%s)",
            (key_hash,),
        )
        row = await cur.fetchone()
        assert row is not None
        assert row[1] == "tenant_demo"

"""Dashboard router providing lead monitoring endpoints and HTML view rendering."""

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from lead_qualifier.core.tenant import get_tenant_connection

router = APIRouter(tags=["Dashboard"])


@router.get("/api/v1/{tenant}/leads")
async def get_leads(
    conn: Annotated[AsyncConnection, Depends(get_tenant_connection)],
) -> dict[str, Any]:
    """Retrieve the most recent lead qualification scores for the authenticated tenant.

    Args:
        conn: Injected database connection pre-configured with tenant RLS context.

    Returns:
        dict: List of evaluated lead records and metadata.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT id, phone_number, final_score, is_qualified, audit_trail, created_at
            FROM scoring_results
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
        leads = await cur.fetchall()
        return {"leads": leads}


@router.get("/dashboard/{tenant}", response_class=HTMLResponse)
def render_dashboard(tenant: str) -> str:
    """Render the dashboard HTML interface configured for the target tenant.

    Args:
        tenant: Unique tenant identifier from URL path.

    Returns:
        HTMLResponse: Rendered HTML page.

    Raises:
        HTTPException: If template file is missing.
    """
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "templates", "dashboard.html"
    )

    try:
        with open(template_path, encoding="utf-8") as file:
            html_content = file.read()
            return html_content.replace("{{TENANT_ID}}", tenant)
    except FileNotFoundError as err:
        raise HTTPException(
            status_code=404,
            detail="Dashboard template file not found.",
        ) from err

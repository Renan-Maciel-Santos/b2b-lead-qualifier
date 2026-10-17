"""Dashboard router providing lead monitoring endpoints and HTML view rendering."""

from pathlib import Path
from typing import Annotated, Any

import jinja2
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from lead_qualifier.core.security import get_tenant_connection

router = APIRouter(tags=["Dashboard"])

# Resolve template directory path using pathlib relative to this module
template_dir = Path(__file__).resolve().parent.parent.parent / "templates"
jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(template_dir)),
    autoescape=True,
)


@router.get("/v1/leads")
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


@router.get("/dashboard", response_class=HTMLResponse)
def render_dashboard() -> str:
    """Render the dashboard HTML interface with strict Jinja2 autoescape enabled.

    Returns:
        HTMLResponse: Rendered HTML page with client-side key authentication.

    Raises:
        HTTPException: If template file is missing.
    """
    try:
        template = jinja_env.get_template("dashboard.html")
        return template.render()
    except jinja2.TemplateNotFound as err:
        raise HTTPException(
            status_code=404,
            detail="Dashboard template file not found.",
        ) from err

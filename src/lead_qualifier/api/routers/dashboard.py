"""Dashboard router providing lead monitoring endpoints and HTML view rendering."""

from pathlib import Path
from typing import Annotated, Any

import jinja2
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.core.database import get_db_pool, tenant_transaction
from lead_qualifier.core.scoring.strategy import ScoringReasonModel, calculate_max_possible_score
from lead_qualifier.core.tenant import TenantContext, require_scope

router = APIRouter(tags=["Dashboard"])

# Resolve template directory path using pathlib relative to this module
template_dir = Path(__file__).resolve().parent.parent.parent / "templates"
jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(template_dir)),
    autoescape=True,
)


@router.get("/v1/leads")
async def get_leads(
    pool: Annotated[AsyncConnectionPool, Depends(get_db_pool)],
    tenant_ctx: Annotated[TenantContext, Depends(require_scope("leads:read"))],
) -> dict[str, Any]:
    """Retrieve the most recent lead qualification scores for the authenticated tenant.

    Args:
        pool: Injected shared application database pool.
        tenant_ctx: Injected immutable tenant security context.

    Returns:
        dict: List of evaluated lead records with structured reasons, score breakdown, and thresholds.
    """
    async with (
        tenant_transaction(pool, tenant_ctx) as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        await cur.execute(
            """
            SELECT
                sr.id,
                sr.phone_number,
                sr.final_score,
                sr.is_qualified,
                sr.audit_trail,
                sr.created_at,
                COALESCE(srs.qualification_threshold, 50) AS qualification_threshold,
                COALESCE(srs.rules, '[]'::jsonb) AS rules
            FROM scoring_results sr
            LEFT JOIN scoring_rule_sets srs
                ON srs.id = sr.rule_set_id AND srs.tenant_id = sr.tenant_id
            ORDER BY sr.created_at DESC
            LIMIT 100
            """
        )
        leads = await cur.fetchall()

        # Validate structured reasons and calculate max_possible_score from the applied rule set
        for lead in leads:
            rules = lead.pop("rules", [])
            lead["max_possible_score"] = calculate_max_possible_score(
                rules if isinstance(rules, list) else []
            )

            raw_reasons = lead.pop("audit_trail", [])
            validated_reasons: list[dict[str, Any]] = []

            if isinstance(raw_reasons, list):
                for item in raw_reasons:
                    if isinstance(item, dict):
                        try:
                            reason_obj = ScoringReasonModel.model_validate(item)
                            validated_reasons.append(reason_obj.model_dump())
                        except Exception:
                            continue
                    elif isinstance(item, str):
                        # Graceful handling for legacy test data
                        validated_reasons.append(
                            {
                                "rule_type": "exact_match",
                                "field": "legacy",
                                "value": item,
                                "points": 0,
                            }
                        )

            lead["reasons"] = validated_reasons
            lead["id"] = str(lead["id"])
            if hasattr(lead["created_at"], "isoformat"):
                lead["created_at"] = lead["created_at"].isoformat()

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
        return str(template.render())
    except jinja2.TemplateNotFound as err:
        raise HTTPException(
            status_code=404,
            detail="Dashboard template file not found.",
        ) from err

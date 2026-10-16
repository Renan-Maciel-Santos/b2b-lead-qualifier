"""Multi-tenant security context re-exports."""

from lead_qualifier.core.security import get_tenant_connection

__all__ = ["get_tenant_connection"]

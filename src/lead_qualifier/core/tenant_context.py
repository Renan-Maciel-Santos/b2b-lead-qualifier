"""Immutable tenant execution context."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TenantContext:
    """Immutable tenant execution context resolved via verified API key."""

    tenant_id: UUID
    schema_name: str

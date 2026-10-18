"""Application dependency injection and composition root."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, Request
from psycopg_pool import AsyncConnectionPool

from lead_qualifier.controllers.webhook_controller import WebhookController
from lead_qualifier.core.database import get_db_pool, tenant_transaction
from lead_qualifier.core.security import require_scope
from lead_qualifier.core.tenant import TenantContext
from lead_qualifier.domain.ports import LLMAdapterPort, UnitOfWorkFactory
from lead_qualifier.repositories.conversation_repo import ConversationRepository
from lead_qualifier.services.state_machine import StateMachineService


def get_llm_adapter(request: Request) -> LLMAdapterPort:
    """Retrieve the shared LLM adapter instance initialized during application lifespan."""
    adapter: LLMAdapterPort = request.app.state.llm_adapter
    return adapter


def create_tenant_uow_factory(
    pool: AsyncConnectionPool,
    tenant_ctx: TenantContext,
) -> UnitOfWorkFactory:
    """Create a UnitOfWorkFactory producing tenant-isolated repository contexts."""

    @asynccontextmanager
    async def _uow() -> AsyncIterator[ConversationRepository]:
        async with tenant_transaction(pool, tenant_ctx) as conn:
            yield ConversationRepository(conn)

    return _uow


def get_tenant_uow_factory(
    pool: Annotated[AsyncConnectionPool, Depends(get_db_pool)],
    tenant_ctx: Annotated[TenantContext, Depends(require_scope("webhook:write"))],
) -> UnitOfWorkFactory:
    """Provide a UnitOfWorkFactory bound to the authenticated tenant and database pool."""
    return create_tenant_uow_factory(pool, tenant_ctx)


def get_state_machine_service(
    uow_factory: Annotated[UnitOfWorkFactory, Depends(get_tenant_uow_factory)],
    llm_adapter: Annotated[LLMAdapterPort, Depends(get_llm_adapter)],
) -> StateMachineService:
    """Compose the StateMachineService for the current tenant turn."""
    return StateMachineService(
        uow_factory=uow_factory,
        llm_adapter=llm_adapter,
        idempotency_timeout=60,
    )


def get_webhook_controller(
    service: Annotated[StateMachineService, Depends(get_state_machine_service)],
) -> WebhookController:
    """Provide WebhookController initialized with the fully composed StateMachineService."""
    return WebhookController(service=service)

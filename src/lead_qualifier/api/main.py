"""FastAPI application entrypoint and lifespan management."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from lead_qualifier.api.health import router as health_router
from lead_qualifier.api.routers.conversation import router as conversation_router
from lead_qualifier.api.routers.dashboard import router as dashboard_router
from lead_qualifier.core.database import create_connection_pool
from lead_qualifier.core.exceptions import (
    LLMExtractionError,
    global_exception_handler,
    llm_extraction_exception_handler,
)
from lead_qualifier.core.logger import logger
from lead_qualifier.core.settings import Settings
from lead_qualifier.integrations.llm.fake_adapter import FakeDeterministicLLMAdapter
from lead_qualifier.integrations.llm.openai_adapter import OpenAIAdapter


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle.

    Initializes the database connection pool in app.state, validates connectivity,
    initializes the configured LLM adapter, and cleanly releases resources upon shutdown.
    """
    settings = Settings()
    pool = create_connection_pool(settings)
    await pool.open()
    logger.info("Database connection pool successfully initialized.")

    app.state.settings = settings
    app.state.db_pool = pool

    if settings.llm_provider == "openai":
        if not settings.openai_api_key or not settings.openai_api_key.get_secret_value():
            raise RuntimeError(
                "OPENAI_API_KEY is required when LLM_PROVIDER is 'openai'. "
                "Configure OPENAI_API_KEY in .env or set LLM_PROVIDER=fake for local demonstration."
            )
        app.state.llm_adapter = OpenAIAdapter(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
    elif settings.llm_provider == "fake":
        logger.warning(
            "LLM_PROVIDER=fake is active. Using deterministic rule-based fake LLM adapter for local demonstration."
        )
        app.state.llm_adapter = FakeDeterministicLLMAdapter()

    yield

    await pool.close()
    logger.info("Database connection pool closed.")


app = FastAPI(
    title="B2B Lead Qualifier",
    description="Conversational B2B lead qualification platform with strict multi-tenancy and deterministic scoring.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_exception_handler(LLMExtractionError, llm_extraction_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(health_router)
app.include_router(conversation_router)
app.include_router(dashboard_router)

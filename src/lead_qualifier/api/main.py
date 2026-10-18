"""FastAPI application entrypoint and lifespan management."""

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from lead_qualifier.api.health import router as health_router
from lead_qualifier.api.routers.conversation import router as conversation_router
from lead_qualifier.api.routers.dashboard import router as dashboard_router
from lead_qualifier.core.database import create_connection_pool
from lead_qualifier.core.exceptions import global_exception_handler
from lead_qualifier.core.logger import logger
from lead_qualifier.core.settings import Settings
from lead_qualifier.integrations.llm.openai_adapter import OpenAIAdapter

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle.

    Initializes the database connection pool in app.state, validates connectivity,
    initializes the LLM adapter, and cleanly releases resources upon shutdown.
    """
    settings = Settings()
    pool = create_connection_pool(settings)
    await pool.open()
    logger.info("Database connection pool successfully initialized.")

    app.state.settings = settings
    app.state.db_pool = pool
    app.state.llm_adapter = OpenAIAdapter(
        api_key=settings.openai_api_key.get_secret_value(),
    )

    yield

    await pool.close()
    logger.info("Database connection pool closed.")


app = FastAPI(
    title="B2B Lead Qualifier",
    description="Conversational B2B lead qualification platform with strict multi-tenancy and deterministic scoring.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_exception_handler(Exception, global_exception_handler)

app.include_router(health_router)
app.include_router(conversation_router)
app.include_router(dashboard_router)

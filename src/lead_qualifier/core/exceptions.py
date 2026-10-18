"""Global exception handling and error response formatting."""

from fastapi import Request
from fastapi.responses import JSONResponse

from lead_qualifier.core.logger import logger


class ActiveRuleSetNotFoundError(Exception):
    """Raised when no active scoring rule set is configured for the tenant."""


class LLMExtractionError(Exception):
    """Raised when structured entity extraction fails in the LLM provider."""


async def llm_extraction_exception_handler(
    request: Request, exc: LLMExtractionError
) -> JSONResponse:
    """Handle LLM provider extraction failures.

    Returns a 503 Service Unavailable response with a generic message
    to instruct upstream clients to retry the webhook delivery.
    """
    logger.error(
        "LLM extraction failure on %s: %s",
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "LLM extraction service unavailable. Please retry later."},
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle uncaught exceptions across all application routes.

    Logs the error with traceback for debugging while masking internal error
    details from the client response.

    Args:
        request: The incoming FastAPI request that encountered an unhandled exception.
        exc: The raised exception instance.

    Returns:
        JSONResponse: A generic 500 Internal Server Error response.
    """
    logger.error(
        "Unhandled error processing request to %s: %s",
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"message": "An internal server error occurred."},
    )

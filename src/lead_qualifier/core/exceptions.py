"""Global exception handling and error response formatting."""

from fastapi import Request
from fastapi.responses import JSONResponse

from lead_qualifier.core.logger import logger


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
        f"Unhandled error processing request to {request.url.path}: {exc!s}", exc_info=True
    )
    return JSONResponse(
        status_code=500,
        content={"message": "An internal server error occurred."},
    )

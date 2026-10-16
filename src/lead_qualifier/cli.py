"""Command-line interface entry point for b2b-lead-qualifier."""

import uvicorn

from lead_qualifier.core.settings import Settings


def main() -> None:
    """Run the FastAPI application using uvicorn."""
    settings = Settings()
    uvicorn.run(
        "lead_qualifier.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_env == "development",
    )


if __name__ == "__main__":
    main()

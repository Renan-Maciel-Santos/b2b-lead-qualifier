"""Command-line interface entry point for b2b-lead-qualifier."""

import uvicorn


def main() -> None:
    """Run the FastAPI application using uvicorn."""
    uvicorn.run(
        "lead_qualifier.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()

"""Command-line interface entry point for b2b-lead-qualifier."""

import argparse
import secrets
import sys
from uuid import UUID

import psycopg
import uvicorn

from lead_qualifier.core.security import hash_api_key
from lead_qualifier.core.settings import Settings


def generate_api_key(tenant_id: str, name: str, db_url: str | None = None) -> str:
    """Generate a cryptographically secure tenant API key and store its SHA-256 hash.

    Args:
        tenant_id: UUID string of the target tenant.
        name: Descriptive label for the API key.
        db_url: Optional database connection string override.

    Returns:
        str: Raw plaintext API key (displayed once).
    """
    tenant_uuid = UUID(tenant_id)
    raw_key = f"b2b_live_{secrets.token_urlsafe(32)}"
    key_hash = hash_api_key(raw_key)

    settings = Settings()
    conninfo = db_url or settings.database_url

    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        cur.execute(
            """
                INSERT INTO core.api_keys (tenant_id, key_hash, name)
                VALUES (%s, %s, %s)
                """,
            (str(tenant_uuid), key_hash, name),
        )
        conn.commit()

    return raw_key


def run_server() -> None:
    """Run the FastAPI application server using uvicorn."""
    settings = Settings()
    uvicorn.run(
        "lead_qualifier.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_env == "development",
    )


def main() -> None:
    """Parse CLI arguments and dispatch to appropriate commands."""
    parser = argparse.ArgumentParser(
        prog="b2b-lead-qualifier",
        description="B2B Lead Qualifier Management CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: run server
    subparsers.add_parser("run", help="Start the FastAPI web server")

    # Command: create API key
    key_parser = subparsers.add_parser("create-key", help="Generate a new tenant API key")
    key_parser.add_argument(
        "--tenant",
        required=True,
        help="Target tenant UUID",
    )
    key_parser.add_argument(
        "--name",
        required=True,
        help="Descriptive name for the API key",
    )
    key_parser.add_argument(
        "--db-url",
        required=False,
        default=None,
        help="Optional database connection URL override",
    )

    args = parser.parse_args()

    if args.command == "create-key":
        try:
            raw_key = generate_api_key(
                tenant_id=args.tenant,
                name=args.name,
                db_url=args.db_url,
            )
            print("=" * 80)
            print("API KEY SUCCESSFULLY CREATED")
            print(f"Tenant ID: {args.tenant}")
            print(f"Name:      {args.name}")
            print(f"Raw Key:   {raw_key}")
            print("=" * 80)
            print("WARNING: Store this key securely. It will NEVER be shown again.")
            print("Only the SHA-256 hash has been stored in the database.")
            print("=" * 80)
        except Exception as e:
            print(f"Error generating API key: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Default behavior: run server
        run_server()


if __name__ == "__main__":
    main()

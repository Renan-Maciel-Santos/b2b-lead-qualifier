"""Command-line interface entry point for b2b-lead-qualifier."""

import argparse
import secrets
import sys
from uuid import UUID

import psycopg
import uvicorn

from lead_qualifier.core.security import hash_api_key
from lead_qualifier.core.settings import Settings


def generate_api_key(
    tenant_id: str,
    name: str,
    scopes: list[str],
) -> str:
    """Generate a cryptographically secure tenant API key and store its SHA-256 hash.

    Args:
        tenant_id: UUID string of the target tenant.
        name: Descriptive label for the API key.
        scopes: Granted permission scopes for the API key.

    Returns:
        str: Raw plaintext API key (displayed once).

    Raises:
        ValueError: If ADMIN_DATABASE_URL is not configured.
    """
    settings = Settings()
    if not settings.admin_database_url or not settings.admin_database_url.get_secret_value():
        raise ValueError(
            "Emissão de API keys é uma operação administrativa restrita. "
            "Configure a variável de ambiente ADMIN_DATABASE_URL com credenciais de superuser ou role administrativo."
        )

    tenant_uuid = UUID(tenant_id)
    raw_key = f"b2b_live_{secrets.token_urlsafe(32)}"
    key_hash = hash_api_key(raw_key)

    with (
        psycopg.connect(settings.admin_database_url.get_secret_value()) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            INSERT INTO core.api_keys (tenant_id, key_hash, name, scopes)
            VALUES (%s, %s, %s, %s)
            """,
            (str(tenant_uuid), key_hash, name, scopes),
        )
        conn.commit()

    return raw_key


def run_server() -> None:
    """Run the FastAPI application server using uvicorn."""
    # Incompatibilidade do psycopg async com o ProactorEventLoop padrao no Windows requer SelectorEventLoop
    if sys.platform == "win32":
        import asyncio

        # Define a politica SelectorEventLoop para permitir operacoes assincronas com psycopg
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    settings = Settings()
    # No Windows, instrui o uvicorn a nao sobrescrever a politica de loop configurada acima
    loop_arg = "none" if sys.platform == "win32" else "auto"
    # No Windows, o reloader do uvicorn spawna subprocesso que reverte o event loop para Proactor
    reload_flag = settings.api_env == "development" and sys.platform != "win32"
    uvicorn.run(
        "lead_qualifier.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=reload_flag,
        loop=loop_arg,
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
        "--scope",
        dest="scopes",
        action="append",
        required=True,
        help="Permission scope granted to the API key (repeatable, e.g. --scope webhook:write)",
    )

    args = parser.parse_args()

    if args.command == "create-key":
        try:
            raw_key = generate_api_key(
                tenant_id=args.tenant,
                name=args.name,
                scopes=args.scopes,
            )
            print("=" * 80)
            print("API KEY SUCCESSFULLY CREATED")
            print(f"Tenant ID: {args.tenant}")
            print(f"Name:      {args.name}")
            print(f"Scopes:    {', '.join(args.scopes)}")
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

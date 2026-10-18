"""Application settings managed via pydantic-settings v2."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for b2b-lead-qualifier.

    Attributes:
        api_env: Current execution environment (development, staging, production).
        api_host: Bind host for Uvicorn HTTP server.
        api_port: Bind port for Uvicorn HTTP server.
        db_host: PostgreSQL host address.
        db_port: PostgreSQL port number.
        db_name: PostgreSQL database name.
        db_user: Application unprivileged user (no BYPASSRLS).
        db_password: Application user password.
        db_admin_user: Superuser for migrations and test provisioning.
        db_admin_password: Superuser password.
        db_pool_min: Minimum open connections in the pool.
        db_pool_max: Maximum open connections in the pool.
        openai_api_key: OpenAI API secret key for LLM adapter.
        domain: Domain name for reverse proxy TLS certificate.
        admin_database_url: Dedicated administrative database URL for CLI operations.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "b2b_lead_qualifier"
    db_user: str = "app_user"
    db_password: SecretStr = SecretStr("change-this-app-password")
    db_admin_user: str = "postgres"
    db_admin_password: SecretStr | None = None
    # Dedicated admin connection for CLI API key provisioning (never used by the web app)
    admin_database_url: SecretStr | None = None

    db_pool_min: int = 1
    db_pool_max: int = 10

    openai_api_key: SecretStr = SecretStr("sk-dummy-key-for-test")

    domain: str = ""

    @property
    def database_url(self) -> str:
        """Construct PostgreSQL connection URL for the unprivileged application role."""
        return (
            f"postgresql://{self.db_user}:{self.db_password.get_secret_value()}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

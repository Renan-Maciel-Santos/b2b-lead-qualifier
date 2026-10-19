"""Unit tests for destructive test database setup safety checks."""

import pytest

from tests.conftest import assert_safe_test_database


def test_safe_test_database_allows_local_loopback_hosts() -> None:
    """Verify that loopback hosts (localhost, 127.0.0.1, ::1) pass validation without CI flag."""
    # Loopback targets are always permitted for local development
    assert_safe_test_database(db_host="localhost", ci_env="")
    assert_safe_test_database(db_host="127.0.0.1", ci_env="")
    assert_safe_test_database(db_host="::1", ci_env="")
    assert_safe_test_database(db_host=" LOCALHOST ", ci_env="")


def test_safe_test_database_blocks_remote_host_without_ci() -> None:
    """Verify that any non-loopback host fails immediately with an explicit error when CI is unset."""
    with pytest.raises(RuntimeError) as exc_info:
        assert_safe_test_database(db_host="prod-db.example.com", ci_env="")

    msg = str(exc_info.value)
    assert "Destructive test setup aborted" in msg
    assert "prod-db.example.com" in msg
    assert "127.0.0.1" in msg


def test_safe_test_database_blocks_remote_host_when_ci_is_false() -> None:
    """Verify that non-loopback hosts still fail if CI is explicitly set to false or 0."""
    with pytest.raises(RuntimeError) as exc_info:
        assert_safe_test_database(db_host="192.168.1.50", ci_env="false")

    assert "Destructive test setup aborted" in str(exc_info.value)


def test_safe_test_database_allows_remote_host_when_ci_is_true() -> None:
    """Verify that CI container service hostnames (e.g. postgres) are allowed when CI is true."""
    # GitHub Actions container network hostnames
    assert_safe_test_database(db_host="postgres", ci_env="true")
    assert_safe_test_database(db_host="postgres", ci_env="1")
    assert_safe_test_database(db_host="remote-runner-db", ci_env="TRUE")


def test_safe_test_database_reads_environment_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that the safety guard reads os.environ if arguments are omitted."""
    monkeypatch.setenv("DB_HOST", "database.production.internal")
    monkeypatch.delenv("CI", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        assert_safe_test_database()

    assert "database.production.internal" in str(exc_info.value)

    # Setting CI=true allows the environment
    monkeypatch.setenv("CI", "true")
    assert_safe_test_database()

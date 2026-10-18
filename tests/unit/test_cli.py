"""Unit tests for CLI commands and argument parsing."""

from unittest.mock import patch

import pytest

from lead_qualifier.cli import main


def test_cli_create_key_missing_scope_raises_system_exit() -> None:
    """Verify that omitting --scope causes CLI argument parsing to fail with SystemExit."""
    test_args = [
        "b2b-lead-qualifier",
        "create-key",
        "--tenant",
        "11111111-1111-1111-1111-111111111111",
        "--name",
        "Test Key",
    ]
    with patch("sys.argv", test_args), pytest.raises(SystemExit) as exc_info:
        main()
    # Argparse exits with code 2 on missing required arguments
    assert exc_info.value.code == 2


def test_cli_create_key_accepts_repeatable_scopes() -> None:
    """Verify that multiple --scope flags are properly collected into a list."""
    test_args = [
        "b2b-lead-qualifier",
        "create-key",
        "--tenant",
        "11111111-1111-1111-1111-111111111111",
        "--name",
        "Test Key",
        "--scope",
        "webhook:write",
        "--scope",
        "leads:read",
    ]
    with (
        patch("sys.argv", test_args),
        patch("lead_qualifier.cli.generate_api_key") as mock_generate,
    ):
        mock_generate.return_value = "b2b_live_dummy"
        main()

        mock_generate.assert_called_once_with(
            tenant_id="11111111-1111-1111-1111-111111111111",
            name="Test Key",
            scopes=["webhook:write", "leads:read"],
            db_url=None,
        )

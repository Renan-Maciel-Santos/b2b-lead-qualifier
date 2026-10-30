"""Unit tests verifying application version synchronization with package metadata."""

import importlib.metadata
import tomllib
from pathlib import Path

import lead_qualifier
from lead_qualifier.api.main import app


def test_app_version_matches_package_metadata_and_pyproject() -> None:
    """The FastAPI app version matches __version__, importlib metadata and pyproject.toml."""
    pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject_data = tomllib.load(f)

    expected_version = pyproject_data["project"]["version"]
    metadata_version = importlib.metadata.version("b2b-lead-qualifier")

    assert lead_qualifier.__version__ == metadata_version
    assert app.version == metadata_version
    assert app.version == expected_version

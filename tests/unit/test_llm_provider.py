"""Unit tests verifying LLM provider selection, fail-fast configuration, and fake adapter extraction."""

import logging
from unittest.mock import AsyncMock, patch

import pytest

from lead_qualifier.api.main import app, lifespan
from lead_qualifier.core.enums import RevenueTier
from lead_qualifier.core.settings import Settings
from lead_qualifier.integrations.llm.fake_adapter import FakeDeterministicLLMAdapter


@pytest.mark.asyncio
async def test_lifespan_openai_provider_without_key_raises_runtime_error() -> None:
    """Verify that starting the application with LLM_PROVIDER=openai and missing API key raises RuntimeError."""
    mock_settings = Settings(
        llm_provider="openai",
        openai_api_key=None,
    )
    with (
        patch("lead_qualifier.api.main.Settings", return_value=mock_settings),
        patch("lead_qualifier.api.main.create_connection_pool") as mock_pool_factory,
        pytest.raises(
            RuntimeError, match="OPENAI_API_KEY is required when LLM_PROVIDER is 'openai'"
        ),
    ):
        mock_pool = AsyncMock()
        mock_pool_factory.return_value = mock_pool

        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_lifespan_fake_provider_initializes_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify that starting with LLM_PROVIDER=fake initializes FakeDeterministicLLMAdapter and logs a warning."""
    mock_settings = Settings(
        llm_provider="fake",
        openai_api_key=None,
    )
    with (
        patch("lead_qualifier.api.main.Settings", return_value=mock_settings),
        patch("lead_qualifier.api.main.create_connection_pool") as mock_pool_factory,
        caplog.at_level(logging.WARNING),
    ):
        mock_pool = AsyncMock()
        mock_pool_factory.return_value = mock_pool

        async with lifespan(app):
            assert isinstance(app.state.llm_adapter, FakeDeterministicLLMAdapter)
            assert any(
                "LLM_PROVIDER=fake is active" in record.message
                for record in caplog.records
                if record.levelno == logging.WARNING
            )


@pytest.mark.asyncio
async def test_fake_deterministic_llm_adapter_extracts_known_slots() -> None:
    """Verify that FakeDeterministicLLMAdapter extracts roles and normalized revenue tiers correctly."""
    adapter = FakeDeterministicLLMAdapter()

    # Turn 1: CEO extraction
    slots_ceo = await adapter.extract_slots("Olá, sou CEO da empresa Acme.")
    assert slots_ceo.role == "CEO"
    assert slots_ceo.revenue_tier is None

    # Turn 2: Revenue extraction (2m to 10m)
    slots_rev = await adapter.extract_slots("Nosso faturamento atual é de 5 milhões por ano.")
    assert slots_rev.revenue_tier == RevenueTier.FROM_2M_TO_10M

    # Knockout roles
    slots_intern = await adapter.extract_slots("Sou estagiário no momento.")
    assert slots_intern.role == "estagiario"

    slots_student = await adapter.extract_slots("Sou estudante de engenharia.")
    assert slots_student.role == "estudante"

    # Knockout revenue
    slots_below = await adapter.extract_slots("Faturamos abaixo de 500k anuais.")
    assert slots_below.revenue_tier == RevenueTier.BELOW_500K

    # High revenue tier
    slots_above = await adapter.extract_slots("Faturamento acima de 10 milhões.")
    assert slots_above.revenue_tier == RevenueTier.ABOVE_10M


@pytest.mark.asyncio
async def test_openai_adapter_propagates_llm_extraction_error_on_openai_error() -> None:
    """Verify that OpenAIAdapter catches OpenAIError and raises LLMExtractionError preserving cause."""
    from openai import OpenAIError

    from lead_qualifier.core.exceptions import LLMExtractionError
    from lead_qualifier.integrations.llm.openai_adapter import OpenAIAdapter

    adapter = OpenAIAdapter(api_key="dummy_key")
    openai_error = OpenAIError("Connection refused")
    adapter.client.beta.chat.completions.parse = AsyncMock(side_effect=openai_error)  # type: ignore[method-assign]

    with pytest.raises(LLMExtractionError) as exc_info:
        await adapter.extract_slots("Olá, sou CEO")

    assert exc_info.value.__cause__ is openai_error

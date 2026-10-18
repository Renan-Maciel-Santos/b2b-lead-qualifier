"""OpenAI LLM adapter for structured entity and slot extraction."""

from openai import AsyncOpenAI, OpenAIError

from lead_qualifier.core.logger import logger
from lead_qualifier.core.schemas.slots import LeadSlots
from lead_qualifier.core.settings import Settings


class OpenAIAdapter:
    """Adapter wrapping OpenAI Structured Outputs API for deterministic entity parsing."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o-mini") -> None:
        """Initialize the asynchronous OpenAI client.

        Args:
            api_key: Optional API key override. If not provided, loaded from Settings.
            model: OpenAI model identifier (defaults to gpt-4o-mini).
        """
        key = api_key or Settings().openai_api_key.get_secret_value()
        self.client = AsyncOpenAI(api_key=key)
        self.model = model

    async def extract_slots(self, conversation_history: str) -> LeadSlots:
        """Extract structured qualification slots from conversation text using Pydantic schema parsing.

        Args:
            conversation_history: Complete transcript or text payload from the user.

        Returns:
            LeadSlots: Populated Pydantic model with extracted entities, or empty model on failure.
        """
        try:
            logger.info("Requesting structured slot extraction from OpenAI.")
            response = await self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional B2B lead qualification assistant. "
                            "Analyze the conversation rigorously and extract factual qualification slots. "
                            "Map user revenue mentions (e.g., 'faturamos 5 milhões por ano', 'abaixo de 500k', '10M+') "
                            "strictly to the normalized revenue_tier enum values: "
                            "'below_500k', '500k_to_2m', '2m_to_10m', or 'above_10m'. "
                            "If a slot is not explicitly mentioned by the lead, leave it null."
                        ),
                    },
                    {
                        "role": "user",
                        "content": conversation_history,
                    },
                ],
                response_format=LeadSlots,
                temperature=0.0,
            )

            extracted_data = response.choices[0].message.parsed
            if extracted_data is None:
                return LeadSlots()

            logger.info("Slots extracted successfully: %s", extracted_data.model_dump())
            return extracted_data

        except OpenAIError as e:
            # Fall back gracefully to empty slots to avoid crashing the state machine on external API outage
            logger.error("Critical error during OpenAI slot extraction: %s", e, exc_info=True)
            return LeadSlots()

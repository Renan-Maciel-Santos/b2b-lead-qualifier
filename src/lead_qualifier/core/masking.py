"""Data masking utilities for sensitive Personally Identifiable Information (PII)."""


def mask_phone_number(phone: str | None) -> str:
    """Mask phone number to obscure sensitive subscriber digits while retaining area context.

    Args:
        phone: Raw phone number string (e.g., '+5511999998888').

    Returns:
        str: Masked string (e.g., '+5511*****8888'), or '[REDACTED]' if missing or too short.
    """
    if not phone or len(phone) < 6:
        return "[REDACTED]"
    prefix = phone[:5]
    suffix = phone[-4:]
    return f"{prefix}*****{suffix}"

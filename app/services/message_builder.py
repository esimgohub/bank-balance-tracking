from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


def format_amount(value: Any) -> str:
    """Format a numeric amount with comma thousand separators (e.g. 1,234,567)."""
    if value is None:
        raise ValueError("Amount is missing")
    try:
        # Normalize via Decimal to avoid float artifacts; balances are expected to be integer-like VND amounts.
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Amount is not numeric: {value!r}") from exc

    # Round to nearest integer for display consistency.
    rounded = dec.to_integral_value(rounding=ROUND_HALF_UP)
    sign = "-" if rounded < 0 else ""
    digits = f"{abs(int(rounded)):,}"
    return f"{sign}{digits}"


def build_balance_message(enterprise_text: Any, enterprise_total: Any, bidv_enabled: bool, bidv_skip_disclosure: str) -> str:
    text = "" if enterprise_text is None else str(enterprise_text)
    formatted_total = format_amount(enterprise_total)

    parts: list[str] = []
    if text.strip():
        parts.append(text.rstrip())

    if not bidv_enabled:
        # Mandatory disclosure in every notification while BIDV is skipped.
        parts.append(bidv_skip_disclosure.strip())
        parts.append(f"==> Tổng số dư hiện tại (KHÔNG bao gồm BIDV): {formatted_total} (VND)")
    else:
        # BIDV-enabled path is not implemented yet (endpoint access pending).
        # Kept explicit to avoid silently producing an incorrect/incomplete message.
        raise NotImplementedError("BIDV-enabled message composition is not implemented yet")

    return "\n\n".join(parts)

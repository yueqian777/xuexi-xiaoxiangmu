from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictInt


class SlideExplanationInput(BaseModel):
    """One page in an atomic explanation append request."""

    model_config = ConfigDict(extra="forbid")

    slide_id: StrictInt
    slide_number: StrictInt
    explanation: str
    source_context: str | None = None


def explanation_items_payload(
    items: list[SlideExplanationInput],
) -> list[dict[str, object]]:
    return [item.model_dump() for item in items]

"""Students on free models: with MODEL_NAME set, that model takes the place of every
model in the product, with no reasoning effort. This is the one place that reads
it."""

import os

from backend.models import NO_REASONING_EFFORT, ModelAllowed


def free_model() -> str | None:
    """Return the model in MODEL_NAME, for students on free models, or none."""
    return os.getenv("MODEL_NAME") or None


def model_or_free(model: str, reasoning_effort: str) -> tuple[str, str]:
    """Return the model and reasoning effort given, or the free model with no
    reasoning effort when there is one."""
    free = free_model()
    return (free, NO_REASONING_EFFORT) if free else (model, reasoning_effort)


def models_or_free(models: list[ModelAllowed]) -> list[ModelAllowed]:
    """Return the models listed, or the free model alone, at no reasoning effort
    and a price of 0, when there is one."""
    free = free_model()
    if not free:
        return models
    return [
        ModelAllowed(
            model=free,
            reasoning_efforts=[NO_REASONING_EFFORT],
            input_price=0,
            output_price=0,
        )
    ]

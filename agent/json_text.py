"""JSON as the agent hands it to a model and records it as a step: characters
such as § and ’ as themselves, rather than as \\u escapes, so the steps read as
they were written and the model reads fewer tokens."""

import json
from typing import Any


def as_json(value: Any, indent: int | None = None) -> str:
    return json.dumps(value, ensure_ascii=False, indent=indent)

"""The rules every operation of our APIs follows, checked against its OpenAPI schema:
an operation id, a one-line description, and no optional inputs, including inside the
models a request body holds."""

from typing import Any


def references(node: Any) -> list[str]:
    """Return the names of the models a part of the schema refers to."""
    if isinstance(node, dict):
        found = [node["$ref"].split("/")[-1]] if "$ref" in node else []
        return found + [name for value in node.values() for name in references(value)]
    if isinstance(node, list):
        return [name for value in node for name in references(value)]
    return []


def optional_fields(models: dict[str, Any], name: str) -> list[str]:
    """Return the optional fields of a model and of every model inside it."""
    properties = models[name].get("properties", {})
    optional = set(properties) - set(models[name].get("required", []))
    found = [f"{name}.{field} is optional" for field in sorted(optional)]
    for inner in dict.fromkeys(references(properties)):
        found += optional_fields(models, inner)
    return found


def rule_breaks(schema: dict[str, Any]) -> list[str]:
    """Return every place an API breaks the rules, or nothing when it keeps them."""
    models = schema.get("components", {}).get("schemas", {})
    breaks = []
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            name = f"{method.upper()} {path}"
            description = operation.get("description", "")
            if not operation.get("operationId"):
                breaks.append(f"{name} has no operation id")
            if not description or "\n" in description:
                breaks.append(f"{name} needs a one-line description")
            breaks += [
                f"{name}: {parameter['name']} is optional"
                for parameter in operation.get("parameters", [])
                if not parameter["required"]
            ]
            if "requestBody" in operation:
                body = operation["requestBody"]
                if not body.get("required"):
                    breaks.append(f"{name}: the body is optional")
                for model in dict.fromkeys(references(body)):
                    breaks += [
                        f"{name}: {field}" for field in optional_fields(models, model)
                    ]
    return breaks

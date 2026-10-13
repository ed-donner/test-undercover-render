from fastapi import FastAPI
from pydantic import BaseModel

from api_rules import rule_breaks


def test_every_operation_follows_the_api_rules(client):
    assert rule_breaks(client.get("/openapi.json").json()) == []


def test_no_operation_takes_a_header_so_the_key_is_never_an_input(client):
    schema = client.get("/openapi.json").json()
    headers = [
        parameter["name"]
        for operations in schema["paths"].values()
        for operation in operations.values()
        for parameter in operation.get("parameters", [])
        if parameter["in"] == "header"
    ]
    assert headers == []


class Inner(BaseModel):
    name: str
    size: int = 1


class Outer(BaseModel):
    inners: list[Inner]


def test_an_optional_field_inside_a_body_breaks_the_rules():
    app = FastAPI()

    @app.post("/things", operation_id="add_things")
    def add_things(request: Outer) -> None:
        """Add some things."""

    assert rule_breaks(app.openapi()) == ["POST /things: Inner.size is optional"]

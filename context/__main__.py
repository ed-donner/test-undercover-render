"""Serve the context layer on the laptop, at http://127.0.0.1:8006/mcp:
uv run -m context"""

from context.server import build_server

if __name__ == "__main__":
    build_server().run(transport="streamable-http")

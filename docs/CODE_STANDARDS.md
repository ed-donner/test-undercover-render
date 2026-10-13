# Code standards

## General

1. Keep it simple, do not overcomplicate.
2. Comments only when necessary.
3. Be concise: a short README and no emojis.
4. IMPORTANT: avoid overly defensive code. Handle exceptions only when necessary.
5. Use uv: ALWAYS `uv run`, NEVER `python3`.
6. TypeScript: strict mode, never `any`.

## Structure

7. One way to do each thing. The agent reaches the backend only through `agent/api.py`, and the improver only through `agent/improver_api.py`, both on the one client in `agent/connection.py`, the one place with the backend's address. The dashboard reaches the backend only through `dashboard/src/api.ts`, and Supabase Auth only through `dashboard/src/auth.ts`. Each API module has one function per backend operation, named after it. The backend reaches the agent's service only through `backend/agent_service.py`, and the judge only through `backend/judge.py`. The base URL and each path are written once, there, and no other module builds a URL or sends a request.
8. Each module has one job, and its name says what it is. A module uses another through what that module is for, and never borrows its helpers. A helper two modules need goes in a module of its own. No circular imports. Tests follow the same rule: shared test helpers live in their own module, never in another test file.
9. Write a literal once. A URL, a path, a status or a message used in more than one place is named once, in the module that owns it.
10. Use the framework's own way before writing your own: FastAPI dependencies and models, LangChain's `context_schema` with `ToolRuntime` for what a tool needs to know, LangGraph's `StateGraph`, `ToolNode`, conditional edges, `RetryPolicy` and checkpointer for the claim agent, LangGraph's `Send`, `max_concurrency` and `RetryPolicy` for the dispatcher, LangChain's `create_agent` with `HumanInTheLoopMiddleware`, `ModelCallLimitMiddleware` and middleware hooks for the improver, SQLAlchemy Core for the database, React hooks and shared components. Check the documentation for the installed version.
11. A function does one job. Split one that mixes levels of detail, such as setting up a run, driving the agent and recording the result.
12. When you extend code, bring it up to these standards first. Never copy a pattern they rule out.

## The agent

13. The agent has six parts, kept apart. `connection.py`, `api.py` and `improver_api.py` are the backend's API. `tools.py` holds every tool of the claim agent and the context and state the tools read. `harness.py` builds and runs the claim agent, and the claim graph's nodes do what middleware would. `dispatcher.py` works a dispatch or an evaluation with no model, and reaches the claim agent only through the harness's one function, `work_in_run`. `improver.py` is the improver, with its tools, its middleware and the context they read; it never imports the harness or the dispatcher, and works a round's evaluations through a function the service hands it. `service.py` is the agent's service: it receives the backend's calls and hands them to the dispatcher, the harness or the improver. Rules about claims and payments are enforced by the backend, whatever the agent does.
14. Instructions give an agent its goal, what it has to work from and what done looks like. They don't script its steps: it plans those itself. Anything that must always happen, or happen in a fixed order, is done by the code.

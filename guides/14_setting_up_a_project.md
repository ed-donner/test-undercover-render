# Setting up a new project

This repo is a Python project and a Node project side by side, with checks that run on every commit. This guide shows how to set up the same scaffolding for a project of your own, and how to add packages as it grows. You need uv and Node installed, as in `setup/INSTRUCTIONS.md`.

## A folder and git

```bash
mkdir my-project
cd my-project
git init
```

## The Python project with uv

```bash
uv init --bare --python 3.12
uv python pin 3.12.12
```

`uv init --bare` writes just a `pyproject.toml`, the file that describes the project and lists its packages. Without `--bare`, uv also creates a README, some starter code and a git repo. `uv python pin` writes `.python-version`, so everyone on the project uses the same Python.

Add packages with `uv add`. Tools you only need while developing go in the dev group with `--dev`:

```bash
uv add fastapi uvicorn python-dotenv
uv add --dev ruff pytest pytest-cov
```

Each `uv add` updates `pyproject.toml`, records the exact versions in `uv.lock` and installs the package into `.venv`. As the project grows you do the same again: `uv add langchain` when you need LangChain, or `uv remove langchain` if you change your mind.

Run everything through uv so that it uses the project's `.venv`:

```bash
uv run pytest
uv run -m uvicorn backend.main:app --reload
```

When you clone a uv project, `uv sync` installs everything in `uv.lock`.

## The Node project with npm

```bash
npm init -y
npm pkg set type=module
npm pkg set private=true --json
```

`npm init -y` writes `package.json`, the Node equivalent of `pyproject.toml`. `type=module` lets you use modern `import` statements, and `private` stops the project being published to npm by accident.

Add packages with `npm install`. Tools you only need while developing are dev dependencies, added with `-D`:

```bash
npm install react react-dom
npm install -D vite typescript
```

Each install updates `package.json`, records the exact versions in `package-lock.json` and puts the package in `node_modules`. When one tool only works with certain versions of another, pin the exact version with `-E`. This repo pins TypeScript at 6.0.3, the newest version typescript-eslint supports:

```bash
npm install -D -E typescript@6.0.3
```

Run a package's command with `npx`, such as `npx vite`. When you clone a Node project, `npm install` installs everything in `package-lock.json`.

## Scripts

The `scripts` section of `package.json` gives names to the commands you run often, and `npm run <name>` runs one. Three from this repo:

```json
"scripts": {
  "prepare": "lefthook install && playwright install chromium",
  "dev:backend": "uv run -m uvicorn backend.main:app --reload --reload-dir backend",
  "check:python": "uv run ruff format --check && uv run ruff check && pyright && uv run pytest -q"
}
```

npm runs `prepare` by itself after every plain `npm install`, so anyone who clones the project gets the git hook and Playwright's browser with no extra step. On Windows, scripts run in the Command Prompt, so keep to commands that work everywhere: `uv run`, the tools installed with npm, or a small `.mjs` file for anything more.

## The checks

Each check is a dev dependency with a script that runs it:

| Check | Python | TypeScript |
| --- | --- | --- |
| Formatting | `ruff format` | Prettier |
| Linting | `ruff check` | ESLint |
| Types | pyright | `tsc` |
| Unit tests and coverage | pytest with pytest-cov | vitest |
| End to end | Playwright | Playwright |

This repo installs pyright with npm (`npm install -D pyright`), since pyright is a Node program. The settings for the checks are in the `[tool.*]` sections of `pyproject.toml`, and in `eslint.config.js`, `tsconfig.json`, `dashboard/vite.config.ts` and `playwright.config.ts`. Prettier works with no settings at all.

## The pre-commit hook

A git hook runs the checks every time you commit. This repo uses lefthook:

```bash
npm install -D lefthook
```

The hook's settings go in a file called `lefthook.yml`. In this repo, the hook formats the files you're committing, then runs `npm run check:python` or `npm run check:ts`, depending on which part changed. The `prepare` script runs `lefthook install`, which sets up the hook when you run `npm install`.

## Two more files

- `.gitignore` keeps `.venv/`, `node_modules/` and your `.env` out of git.
- `.gitattributes` with the line `* text=auto eol=lf` gives every file the same line endings on Windows as on a Mac. Without it, Git for Windows changes them and Prettier fails.

## Quick reference

| | Python | Node |
| --- | --- | --- |
| Start a project | `uv init --bare` | `npm init -y` |
| Add a package | `uv add <package>` | `npm install <package>` |
| Add a dev tool | `uv add --dev <package>` | `npm install -D <package>` |
| Remove a package | `uv remove <package>` | `npm uninstall <package>` |
| Install after cloning | `uv sync` | `npm install` |
| Run a tool | `uv run <command>` | `npx <command>` |
| The list of packages | `pyproject.toml` | `package.json` |
| The exact versions (commit it) | `uv.lock` | `package-lock.json` |
| The installed packages (never commit) | `.venv/` | `node_modules/` |

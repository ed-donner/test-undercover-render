# undercoverlab

The small agent of the Week 3 Day 4 Lab 1, which `labs/week3day4_lab1.ipynb` walks through. It started as `agentcore create --name undercoverlab --template agent-python-langchain`, and the lab explains what changed.

- `main.py`: the agent's jobs, with a claim graph that pauses for a handler
- `model/load.py`: the model through OpenRouter, and the project's credentials
- `pyproject.toml`: the agent's packages, which `agentcore dev` and `agentcore deploy` install

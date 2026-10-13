"""The UnderCover Copilot on AgentCore Runtime: the file Runtime starts for the
copilot runtime.

The Copilot is the AgentCore app in agent/copilot/entrypoint.py, which npm run dev
serves on the laptop. The deployment packages this folder with the agent package
beside it, so this file can import the app and run it.
"""

from agent.copilot.entrypoint import app

if __name__ == "__main__":
    app.run()

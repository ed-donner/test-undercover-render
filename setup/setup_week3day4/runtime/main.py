"""The UnderCover Agent on AgentCore Runtime: the file Runtime starts.

The agent is the AgentCore app in agent/entrypoint.py, which npm run dev serves on the
laptop. The deployment packages this folder with the agent package beside it, so this
file can import the app and run it.
"""

from agent.entrypoint import app

if __name__ == "__main__":
    app.run()

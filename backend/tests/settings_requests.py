"""Requests the backend's tests send to change the settings."""

from backend.database import load
from backend.tests.sign_in import DANA, signed_in

# The settings as seeded, from data/company.json and data/improvement.json.
STARTING = {
    "approval_limit": load("company.json")["payout_approval_limit"],
    **load("improvement.json"),
}


def change_settings(client, email=DANA, **values):
    """Change some settings from where they started, as the handler with this
    email."""
    return client.put("/api/settings", json=STARTING | values, headers=signed_in(email))

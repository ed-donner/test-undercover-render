"""The reads only the dashboard makes, sent as Dana Whitfield, signed in, sends them."""

from backend.tests.sign_in import signed_in


def read(client, path):
    """Read a path as Dana Whitfield, and return the response."""
    return client.get(path, headers=signed_in())


def steps_of(client, claim_id):
    return read(client, f"/api/claims/{claim_id}/steps").json()


def configuration(client):
    return read(client, "/api/configuration").json()


def version_details(client, number):
    return read(client, f"/api/configuration/versions/{number}").json()


def settings_page(client):
    return read(client, "/api/settings").json()


def evaluations(client):
    return read(client, "/api/evaluations").json()


def recipe(client, number):
    return read(client, f"/api/improvement/recipes/{number}").json()

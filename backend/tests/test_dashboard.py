"""The backend serves the dashboard's build beside the API, and without a build it
answers as it always has."""

import pytest

from backend.tests.dashboard_build import APP, INDEX

# How the API answers what no operation does, with a build or without one.
AS_BEFORE = [
    ("GET", "/api/nothing", 404),
    ("POST", "/api/nothing", 404),
    ("POST", "/api/health", 405),
    ("DELETE", "/api/claims", 405),
    ("GET", "/api/claims/", 307),
]


@pytest.mark.usefixtures("build")
@pytest.mark.parametrize("path", ["/", "/claims/CLM-1001", "/improvement/recipes/2"])
def test_every_page_gets_the_builds_index(dashboard, path):
    page = dashboard.get(path)
    assert (page.status_code, page.text) == (200, INDEX)
    assert page.headers["content-type"].startswith("text/html")


@pytest.mark.usefixtures("build")
def test_the_builds_files_are_served_at_their_own_paths(dashboard):
    script = dashboard.get("/assets/app.js")
    assert (script.status_code, script.text) == (200, APP)


def assert_as_before(dashboard, method, path, status):
    answer = dashboard.request(method, path, follow_redirects=False)
    assert answer.status_code == status
    if status != 307:
        assert answer.headers["content-type"] == "application/json"


@pytest.mark.usefixtures("build")
@pytest.mark.parametrize(("method", "path", "status"), AS_BEFORE)
def test_the_api_answers_as_before_beside_the_build(dashboard, method, path, status):
    assert_as_before(dashboard, method, path, status)


@pytest.mark.usefixtures("no_build")
@pytest.mark.parametrize(("method", "path", "status"), AS_BEFORE)
def test_the_api_answers_as_before_without_a_build(dashboard, method, path, status):
    assert_as_before(dashboard, method, path, status)


@pytest.mark.usefixtures("build")
def test_the_api_and_its_docs_work_beside_the_build(dashboard):
    assert dashboard.get("/api/health").json() == {"status": "ok"}
    assert dashboard.get("/openapi.json").status_code == 200
    assert dashboard.get("/docs").status_code == 200


@pytest.mark.usefixtures("no_build")
@pytest.mark.parametrize("path", ["/", "/claims/CLM-1001"])
def test_without_a_build_every_other_path_is_a_404_in_json(dashboard, path):
    page = dashboard.get(path)
    assert (page.status_code, page.json()) == (404, {"detail": "Not Found"})

"""The dashboard's build, served beside the API: its files at their own paths, and
index.html for any other path outside /api/, so each page loads on a refresh."""

from http import HTTPStatus
from pathlib import Path
from typing import cast

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.routing import Match, Mount
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

DIST = Path(__file__).resolve().parent.parent / "dashboard" / "dist"
INDEX_HTML = "index.html"
API = "api"


class DashboardFiles(StaticFiles):
    """The files of the dashboard's build, with index.html for a page it has no
    file for, since the dashboard routes its pages itself."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != HTTPStatus.NOT_FOUND:
                raise
            return await super().get_response(INDEX_HTML, scope)


class DashboardMount(Mount):
    """The dashboard's build at /, mounted after every route. It takes no path
    under /api/, which the API answers as it always has, and none while the
    dashboard isn't built, so the backend then answers as it does without it."""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        files = cast(DashboardFiles, self.app)
        under_api = scope["path"].split("/")[1] == API
        if under_api or not Path(str(files.directory)).is_dir():
            return Match.NONE, {}
        return super().matches(scope)


mount = DashboardMount("/", app=DashboardFiles(directory=DIST, check_dir=False))

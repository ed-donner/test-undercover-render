"""A stand-in for the dashboard's build, which the tests serve in its place."""

from pathlib import Path

INDEX = "<!doctype html><title>UnderCover</title>"
APP = "console.log('UnderCover');"


def stand_in_build(folder: Path) -> Path:
    """Write a build with an index.html and one script into a folder."""
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text(INDEX)
    (folder / "assets" / "app.js").write_text(APP)
    return folder

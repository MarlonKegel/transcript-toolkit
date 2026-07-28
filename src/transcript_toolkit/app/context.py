"""What the running app knows: which workspace is open, and what is running in it.

One server, one open workspace, one job — all server-side, which is why closing the browser
tab does not interrupt anything and reopening it picks the run back up mid-flight.
"""
from __future__ import annotations

from ..errors import ToolkitError
from ..project import Project
from . import DEFAULT_PORT
from .jobs import JobManager


class AppContext:
    def __init__(self) -> None:
        self.project: Project | None = None
        self.jobs = JobManager()
        self.port = DEFAULT_PORT

    def require_project(self) -> Project:
        if self.project is None:
            raise ToolkitError("No workspace is open.")
        return self.project

    def open(self, project: Project) -> None:
        self.project = project

    def status(self) -> dict:
        """The same picture `toolkit status` prints, as data."""
        from ..steps.status import gather_status
        return gather_status(self.require_project())

    def topic_sets(self) -> list[str]:
        """Topic sets available in the workspace: every spreadsheet in topics/, plus anything
        already named in config.yaml."""
        from ..core.config import load_root_config
        from ..steps.topics.taxonomy import available_sets
        project = self.require_project()
        return available_sets(project, load_root_config(project))


CONTEXT = AppContext()

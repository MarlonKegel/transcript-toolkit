"""Entry point for NiceGUI's test harness.

Its `user` fixture runs a NiceGUI "main file" to build the app under test. This is that file:
the real app, assembled the same way `toolkit app` assembles it, with no server started.
"""
from nicegui import ui

from transcript_toolkit.app.server import build

# The harness talks to the app in-process as host "test", so the real allow-list
# (which a real server enforces — see test_app_pages.py) would reject every request.
build(allowed_hosts=["*"])
ui.run(reload=False)

"""Start the app and ask it to restart, the way an update does. Used by test_app_restart.py."""
import asyncio
import sys
from pathlib import Path

from nicegui import app as nicegui_app

from transcript_toolkit.app import server


@nicegui_app.on_startup
async def _ask() -> None:
    marker = Path(sys.argv[1])
    if marker.exists():          # this is the process that came back; leave it alone
        print("PROBE: came back, not asking again", flush=True)
        return
    marker.write_text("asked")

    async def later() -> None:
        await asyncio.sleep(1.0)
        print("PROBE: asking for a restart", flush=True)
        server.ask_restart()

    asyncio.create_task(later())


server.serve(port=int(sys.argv[2]), open_browser=False)

"""The desktop app: a local web interface over the same CLI, for people who would rather not
use a terminal.

Nothing here reimplements a pipeline step. The app resolves a workspace, shows what state it
is in, and runs `toolkit` commands in child processes — so the CLI stays the only thing that
does the work, and the two cannot drift apart.
"""

# The app's port. Here, in a module that imports nothing, so the CLI can name it in
# `--help` without paying for the app's imports on every `toolkit` command.
DEFAULT_PORT = 8377

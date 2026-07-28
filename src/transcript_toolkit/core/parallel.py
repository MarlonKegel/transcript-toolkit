"""The worker pool every LLM step runs its calls through."""
from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager


@contextmanager
def worker_pool(max_workers: int) -> Iterator[ThreadPoolExecutor]:
    """Threads that stop being handed work the moment you interrupt the run.

    `with ThreadPoolExecutor(...)` on its own waits for every queued task before it lets a
    Ctrl-C through, because its exit calls `shutdown(wait=True)`. A step queues the whole
    corpus up front, so that is minutes — sometimes much longer — of calls still being paid
    for after the user asked it to stop, and the app's Stop button inherits the same delay.

    Cancelling what has not started yet fixes that. Calls already in flight still finish and
    are still written to the cache, so re-running the step afterwards picks up from there.
    """
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        yield pool
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)

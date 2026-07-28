"""Ctrl-C has to mean stop, not finish everything first."""
import signal
import subprocess
import sys
import time

CODE = """
import os, signal, sys, time
from transcript_toolkit.core.parallel import worker_pool
from concurrent.futures import as_completed

done = []
def work(i):
    time.sleep(0.3)
    done.append(i)
    return i

try:
    with worker_pool(2) as pool:
        futures = [pool.submit(work, i) for i in range(40)]
        os.kill(os.getpid(), signal.SIGINT)
        for f in as_completed(futures):
            f.result()
except KeyboardInterrupt:
    print(f"INTERRUPTED after {len(done)} of 40")
    sys.exit(130)
"""


def test_an_interrupt_does_not_wait_for_the_whole_queue():
    """A step queues the whole corpus up front. Waiting for that queue to drain would mean
    minutes of further paid calls after someone clicks Stop."""
    started = time.time()
    result = subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True,
                            timeout=30)
    elapsed = time.time() - started

    assert result.returncode == 130, result.stderr
    finished = int(result.stdout.split("after ")[1].split(" of")[0])
    assert finished < 10, f"drained {finished}/40 tasks before stopping"
    assert elapsed < 5, f"took {elapsed:.1f}s; the whole queue is 6s of work"

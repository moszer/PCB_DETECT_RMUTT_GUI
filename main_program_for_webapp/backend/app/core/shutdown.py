"""Know that the server is stopping, the moment the stop signal arrives.

uvicorn stops in two steps: on SIGTERM/SIGINT it stops accepting and waits for open
connections to finish, and only then runs the app's shutdown. A live camera view (an endless
MJPEG response) never finishes on its own, so with a browser on the camera page the station
waited forever and ./aoi-stop had to kill it after 15 s. Long-lived responses check
`shutting_down` and end at once instead.

`install()` wraps the signal handlers uvicorn has set (it calls them after ours), so it must
run after uvicorn has installed them: from the app's lifespan startup.
"""
from __future__ import annotations

import logging
import signal
import threading

logger = logging.getLogger(__name__)

shutting_down = threading.Event()
_installed = False


def install() -> None:
    global _installed
    if _installed or threading.current_thread() is not threading.main_thread():
        return
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous = signal.getsignal(sig)

        def handler(signum, frame, previous=previous):
            if not shutting_down.is_set():
                logger.info("Stop signal received: ending live streams")
            shutting_down.set()
            if callable(previous):
                previous(signum, frame)
            elif previous != signal.SIG_IGN:
                # No server handler (not under uvicorn): behave as if we were not here.
                signal.signal(signum, signal.SIG_DFL)
                signal.raise_signal(signum)

        signal.signal(sig, handler)
    _installed = True

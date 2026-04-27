"""
A singleton background-thread event loop for safely running agentscope's
async agents from Streamlit's synchronous context.

Why a dedicated thread?
  - Streamlit may or may not have its own event loop running.
  - httpx.AsyncClient (used internally by the OpenAI SDK) must be created and
    used within the SAME event loop.
  - A single persistent loop in a daemon thread satisfies both constraints.
"""
import asyncio
import threading
from typing import Any, Coroutine


class _AsyncRunner:
    """Singleton: one background thread, one persistent event loop."""

    _instance: "_AsyncRunner | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "_AsyncRunner":
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._loop = asyncio.new_event_loop()
                inst._thread = threading.Thread(
                    target=inst._run_forever,
                    daemon=True,
                    name="AsyncRunner",
                )
                inst._thread.start()
                cls._instance = inst
        return cls._instance

    def _run_forever(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Coroutine, timeout: float = 300) -> Any:
        """Submit *coro* to the background loop and block until done."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)


_runner = _AsyncRunner()


def run_async(coro: Coroutine, timeout: float = 300) -> Any:
    """
    Public helper: run an async coroutine synchronously from any thread.

    Usage::

        result = run_async(some_agent(msg))
    """
    return _runner.run(coro, timeout=timeout)

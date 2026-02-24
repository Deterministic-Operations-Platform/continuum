from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

_alive: set[int] = set()
_pid = itertools.count(20000)


@dataclass
class FakeProc:
    pid: int
    _alive: bool = True

    def poll(self) -> int | None:
        return None if self._alive else 0

    def terminate(self) -> None:
        self._alive = False
        _alive.discard(self.pid)

    def kill(self) -> None:
        self.terminate()

    def wait(self, timeout: float | None = None) -> int:
        self.terminate()
        return 0


def fake_popen(*args: Any, **kwargs: Any) -> FakeProc:
    pid = next(_pid)
    _alive.add(pid)
    return FakeProc(pid=pid)


def fake_pid_alive(pid: int) -> bool:
    return pid in _alive


def fake_kill_tree(pid: int, *args: Any, **kwargs: Any) -> None:
    _alive.discard(pid)

"""Small terminal progress helpers for load tests."""

from __future__ import annotations

import sys


class ProgressBar:
    def __init__(self, total: int, label: str, width: int = 28):
        self.total = max(total, 1)
        self.label = label
        self.width = width
        self.current = 0
        self._draw()

    def advance(self, step: int = 1, detail: str = "") -> None:
        self.current = min(self.total, self.current + step)
        self._draw(detail=detail)

    def finish(self, detail: str = "") -> None:
        self.current = self.total
        self._draw(detail=detail, done=True)

    def _draw(self, detail: str = "", done: bool = False) -> None:
        filled = int(self.width * self.current / self.total)
        bar = "#" * filled + "-" * (self.width - filled)
        percent = int(100 * self.current / self.total)
        msg = f"\r  {self.label:<24} [{bar}] {self.current:>3}/{self.total:<3} {percent:>3}%"
        if detail:
            msg += f"  {detail}"
        if done:
            msg += "\n"
        sys.stdout.write(msg)
        sys.stdout.flush()


def print_phase_progress(index: int, total: int, label: str) -> None:
    print(f"\n  [{index}/{total}] {label}")

"""Remembers what has already been alerted, so a run only reports what is new."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


class State:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._data: dict = {"seen": {}, "history": []}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                print(f"[state] {self.path} is unreadable; starting fresh")
        self._data.setdefault("seen", {})
        self._data.setdefault("history", [])

    def is_new(self, key: str) -> bool:
        return key not in self._data["seen"]

    def mark(self, key: str) -> None:
        self._data["seen"][key] = dt.datetime.now(dt.timezone.utc).isoformat()

    def record(self, program: str, cabin: str, miles: int) -> int | None:
        """Log today's best price and return the previous one, if any."""
        stamp = dt.datetime.now(dt.timezone.utc).isoformat()
        slot = f"{program}|{cabin}"
        previous = None
        for entry in reversed(self._data["history"]):
            if entry.get("slot") == slot:
                previous = entry.get("miles")
                break
        self._data["history"].append({"slot": slot, "miles": miles, "at": stamp})
        self._data["history"] = self._data["history"][-2000:]
        return previous

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True))

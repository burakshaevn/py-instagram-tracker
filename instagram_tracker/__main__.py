"""Запуск `python -m instagram_tracker ...` — то же самое, что main.py."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Точка запуска: `python main.py [analyze|snapshots|session] ...`

Вся логика живёт в пакете `instagram_tracker`, здесь только вызов CLI: так пакет
остаётся импортируемым (тесты, чужие скрипты), а main.py не нужно нигде копировать.
"""

from __future__ import annotations

from instagram_tracker.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

"""Точка входа командной строки.

Идея интерфейса: `python main.py analyze` без аргументов должен работать в 90%
случаев — найти выгрузку рядом, разобрать её, показать результат и, если есть
прежний снимок, сразу сказать, кто отписался.

Пароль в `.env` больше не нужен: он требуется только для живого режима, и там
предпочтительнее `sessionid` из браузера (или сохранённый файл сессии).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .analyzer import DiffReport, FollowBackReport, analyze_followbacks, diff_snapshots
from .data_manager import SnapshotStore
from .errors import TrackerError
from .model import Snapshot, UserRef
from .observers import ConsoleProgressObserver, QuietObserver
from .settings import Settings, load_settings
from .sources import build_source

__all__ = ["main", "build_parser"]

CSV_HEADER = ("section", "username", "full_name", "user_id", "since", "profile_url")


# --- разбор аргументов ---------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="instagram-tracker",
        description="Анализ подписчиков и подписок в Instagram (по выгрузке или живой сессии)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python main.py analyze                      # найти выгрузку и разобрать\n"
            "  python main.py analyze --export ig-export.zip --save\n"
            "  python main.py analyze --compare data/snapshots/foo__....json\n"
            "  python main.py analyze --format csv --out report.csv\n"
            "  python main.py snapshots list                 # история снимков\n"
            "  python main.py snapshots diff old.json new.json\n"
            "  python main.py session login --sessionid <cookie>\n"
            "  python main.py session status\n\n"
            "Выгрузку взять здесь: Instagram → Настройки → Центр аккаунтов →\n"
            "«Ваши данные и разрешения» → «Скачать или перенести информацию» →\n"
            "только «Подписчики и подписки», формат JSON, «Всё время».\n"
        ),
    )
    parser.add_argument("--version", action="version", version=_version_string())
    parser.add_argument("--verbose", action="store_true", help="показывать трейсбек при ошибке")
    subparsers = parser.add_subparsers(dest="command")

    analyze = subparsers.add_parser(
        "analyze", help="разобрать снимок подписок и (опционально) сравнить с прошлым"
    )
    analyze.add_argument("username", nargs="?", help="ник аккаунта (по умолчанию — ваш)")
    _add_source_flags(analyze)
    _add_common_flags(analyze)
    analyze.add_argument(
        "--compare",
        metavar="PATH",
        nargs="?",
        const="__latest__",
        default=None,
        help="сравнить с прошлым снимком: без значения — последний снимок в истории, "
        "или путь к файлу/выгрузке",
    )
    analyze.add_argument(
        "--no-compare", action="store_true", help="не сравнивать, даже есть история"
    )
    analyze.add_argument("--save", action="store_true", help="сохранить снимок в историю")
    analyze.add_argument("--save-report", action="store_true", help="сохранить отчёт(ы) в JSON")
    analyze.add_argument("--show-mutual", action="store_true", help="печатать и взаимные подписки")
    analyze.set_defaults(handler=cmd_analyze)

    snapshots = subparsers.add_parser("snapshots", help="история сохранённых снимков")
    snap_sub = snapshots.add_subparsers(dest="snapshots_command")
    listing = snap_sub.add_parser("list", help="список снимков")
    listing.add_argument("username", nargs="?")
    listing.add_argument("--data-dir", default=None)
    listing.set_defaults(handler=cmd_snapshots_list)

    show = snap_sub.add_parser("show", help="показать сохранённый снимок")
    show.add_argument("path")
    show.add_argument("--limit", type=int, default=50)
    show.add_argument("--format", choices=("text", "json"), default="text")
    show.set_defaults(handler=cmd_snapshots_show)

    diff = snap_sub.add_parser("diff", help="сравнить два файла/выгрузки напрямую")
    diff.add_argument("old")
    diff.add_argument("new")
    diff.add_argument("--format", choices=("text", "json", "csv"), default="text")
    diff.add_argument("--out", default=None)
    diff.add_argument("--limit", type=int, default=0)
    diff.add_argument("--data-dir", default=None)
    diff.add_argument("--save-report", action="store_true")
    diff.set_defaults(handler=cmd_snapshots_diff)

    session = subparsers.add_parser("session", help="сессия для живого режима (без пароля)")
    sess_sub = session.add_subparsers(dest="session_command")
    status = sess_sub.add_parser("status", help="жива ли сохранённая сессия")
    status.add_argument("--data-dir", default=None)
    status.set_defaults(handler=cmd_session_status)

    login = sess_sub.add_parser("login", help="сохранить сессию: по sessionid или логином")
    login.add_argument("--sessionid", help="значение cookie sessionid из браузера")
    login.add_argument(
        "--cookie",
        metavar="TEXT|FILE",
        help="заголовок Cookie целиком или файл cookies.txt/JSON — sessionid достанем сами",
    )
    login.add_argument("--username")
    login.add_argument("--password")
    login.add_argument("--session-file", help="куда сохранить сессию (по умолчанию data/…)")
    login.add_argument("--proxy")
    login.set_defaults(handler=cmd_session_login)

    return parser


def _add_source_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export",
        metavar="PATH",
        help="выгрузка Instagram: .zip, каталог или файл followers_1.json/following.html",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="читать живьём через instagrapi (нужна сохранённая сессия или sessionid)",
    )
    parser.add_argument("--snapshot", metavar="PATH", help="уже сохранённый снимок (JSON)")
    parser.add_argument("--data-dir", default=None, help="каталог истории (по умолчанию data/)")


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("text", "json", "csv"), default="text")
    parser.add_argument("--out", metavar="FILE", help="куда писать результат (csv/json)")
    parser.add_argument("--limit", type=int, default=50, help="сколько имён печатать (0 = все)")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="разрешить неполные (усечённые Instagram'ом) списки",
    )
    parser.add_argument("--quiet", action="store_true", help="не печатать прогресс")


# --- команды -------------------------------------------------------------


def cmd_analyze(args: argparse.Namespace, ctx: _Context) -> int:
    settings = ctx.settings
    store = ctx.store

    if args.snapshot:
        snapshot = store.load_snapshot(args.snapshot)
    else:
        source = build_source(
            settings,
            export=Path(args.export) if args.export else None,
            force_session=bool(args.live),
            username=args.username,
        )
        verbose = not args.quiet and args.format == "text"
        observer = ctx.progress if verbose else QuietObserver()
        if hasattr(source, "attach"):
            source.attach(observer)
        snapshot = source.fetch_snapshot(args.username)

    if not (snapshot.count("followers") or snapshot.count("following")):
        raise TrackerError(
            "Источник вернул пустые списки. Для чужих аккаунтов Instagram списки "
            "подписчиков не отдаёт — анализируйте свой аккаунт через выгрузку."
        )

    report = analyze_followbacks(snapshot, staleness_days=settings.staleness_days)
    diff: Optional[DiffReport] = None
    compare_note = ""

    wants_compare = args.compare is not None and not args.no_compare
    if wants_compare:
        if args.compare == "__latest__":
            try:
                old_snapshot = store.latest_snapshot(snapshot.username)
            except TrackerError as exc:
                old_snapshot, compare_note = None, str(exc)
        else:
            old_snapshot = store.read_any(args.compare)
        if old_snapshot is not None:
            diff = diff_snapshots(old_snapshot, snapshot, staleness_days=settings.staleness_days)

    saved_path = None
    if args.save:
        saved_path = store.save_snapshot(snapshot)

    if args.format == "json":
        payload: Dict[str, Any] = {"snapshot": _snapshot_summary(snapshot), "followback": report.to_dict()}
        if diff:
            payload["diff"] = diff.to_dict()
        _emit(json.dumps(payload, ensure_ascii=False, indent=2), args.out)
    elif args.format == "csv":
        _emit_csv(report, diff, args.out)
    else:
        _print_snapshot_header(snapshot, ctx)
        _print_followback(report, args, ctx)
        if diff:
            _print_diff(diff, args, ctx)
        elif wants_compare:
            ctx.warn(
                compare_note
                or "Сравнивать не с чем: сохраните первый снимок (--save), "
                "следующий прогон уже покажет динамику."
            )

    if args.save_report:
        for item in filter(None, (report, diff)):
            ctx.info(f"Отчёт сохранён: {store.save_report(item)}")
    if saved_path:
        ctx.info(f"Снимок сохранён: {saved_path}")
    return 0


def cmd_snapshots_list(args: argparse.Namespace, ctx: _Context) -> int:
    store = SnapshotStore(Path(args.data_dir)) if args.data_dir else ctx.store
    infos = store.list_snapshots(args.username)
    if not infos:
        ctx.info(
            "История пуста: "
            f"{store.snapshots_dir}. Сохраните первый снимок: python main.py analyze --save"
        )
        return 1
    print(
        f"{'ДАТА (UTC)':<20} {'АККАУНТ':<22} {'ПОДПИСЧИКОВ':>12} {'ПОДПИСОК':>9}  "
        f"{'ИСТОЧНИК':<14} ФАЙЛ"
    )
    for info in infos:
        stamp = info.captured_at.strftime("%Y-%m-%d %H:%M:%S") if info.captured_at else "?"
        print(
            f"{stamp:<20} {info.username:<22} {info.followers:>12} {info.following:>9}  "
            f"{info.source:<14} {info.path.name}"
        )
    ctx.info(f"\nВсего снимков: {len(infos)}. Сравнение последнего с предпоследним: "
             "python main.py analyze --compare")
    return 0


def cmd_snapshots_show(args: argparse.Namespace, ctx: _Context) -> int:
    snapshot = ctx.store.load_snapshot(args.path)
    if args.format == "json":
        _emit(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), None)
        return 0
    _print_snapshot_header(snapshot, ctx)
    for kind, label in (("followers", "Подписчики"), ("following", "Подписки")):
        users = snapshot.users(kind)
        shown = users[: args.limit] if args.limit else users
        print(f"\n{label} ({len(users)}):")
        for ref in shown:
            print(f"  {ref.display}")
        if args.limit and len(users) > args.limit:
            print(f"  … ещё {len(users) - args.limit}")
    return 0


def cmd_snapshots_diff(args: argparse.Namespace, ctx: _Context) -> int:
    store = SnapshotStore(Path(args.data_dir)) if args.data_dir else ctx.store
    old = store.read_any(args.old)
    new = store.read_any(args.new)
    report = diff_snapshots(old, new, staleness_days=ctx.settings.staleness_days)
    if args.format == "json":
        _emit(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), args.out)
    elif args.format == "csv":
        _emit_csv(None, report, args.out)
    else:
        _print_diff(report, args, ctx)
    if args.save_report:
        ctx.info(f"Отчёт сохранён: {store.save_report(report)}")
    return 0


def cmd_session_status(args: argparse.Namespace, ctx: _Context) -> int:
    from .sources.session import SessionSource

    source = SessionSource(
        session_file=ctx.settings.session_file,
        sessionid=ctx.settings.instagram_sessionid,
        username=ctx.settings.instagram_username,
        password=ctx.settings.instagram_password,
        persist_session=False,
    )
    info = source.session_status()
    if info.get("connected"):
        ctx.info(f"Сессия жива: @{info['username']} (через {info['method']}).")
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    ctx.info(json.dumps(info, ensure_ascii=False, indent=2))
    ctx.warn(
        "Сессия не готова. Сохраните её: python main.py session login --sessionid <cookie>"
    )
    return 1


def cmd_session_login(args: argparse.Namespace, ctx: _Context) -> int:
    from .sources.session import SessionSource

    session_file = (
        Path(args.session_file) if args.session_file else ctx.settings.session_file
    )
    sessionid = args.sessionid or ctx.settings.instagram_sessionid
    if args.cookie:
        from .session_import import extract_sessionid

        sessionid = extract_sessionid(args.cookie)
        ctx.info(f"sessionid найден (пользователь {sessionid.split(':')[0] if ':' in sessionid else '?'}).")
    if sessionid:
        source = SessionSource(
            session_file=session_file,
            sessionid=sessionid,
            proxy=args.proxy or ctx.settings.proxy,
            persist_session=True,
        )
    elif args.username and args.password:
        source = SessionSource(
            session_file=session_file,
            username=args.username,
            password=args.password,
            proxy=args.proxy or ctx.settings.proxy,
            allow_partial=True,
            persist_session=True,
            interactive=True,
        )
    else:
        raise TrackerError(
            "Нужно либо --sessionid/--cookie <cookie> (рекомендуется), либо --username/--password "
            "для первичного входа. Парольный вход сохранит сессию, и дальше он не понадобится."
        )
    source.connect()
    ctx.info(f"Готово: аккаунт @{source.own_username}, сессия в {session_file}.")
    ctx.info("Теперь можно: python main.py analyze --live")
    return 0


# --- печать --------------------------------------------------------------


def _print_snapshot_header(snapshot: Snapshot, ctx: "_Context") -> None:
    counts = f"подписчиков {snapshot.count('followers')}, подписок {snapshot.count('following')}"
    stamp = snapshot.captured_at.strftime("%Y-%m-%d %H:%M UTC") if snapshot.captured_at else "?"
    print(f"\n@{snapshot.username or '?'} · {counts} · {stamp} · источник: {snapshot.source}")
    if snapshot.meta.get("recently_unfollowed"):
        print(
            f"В выгрузке есть «недавно отписанные» ({len(snapshot.meta['recently_unfollowed'])}) — "
            "это те, от кого отписались вы."
        )
    warnings = snapshot.truncations
    if warnings:
        for kind, (got, expected) in warnings.items():
            ctx.warn(f"{kind}: получено {got} из {expected} — Instagram обрезал список.")


def _print_followback(report: FollowBackReport, args: argparse.Namespace, ctx: "_Context") -> None:
    print("\n=== Взаимные подписки ===")
    _print_section(
        "Вы подписаны, они — нет (не подписаны в ответ)", report.not_following_back, args.limit
    )
    _print_section(
        "Они подписаны на вас, вы — нет", report.followers_not_followed, args.limit
    )
    if args.show_mutual:
        _print_section("Взаимные подписки", report.mutual, args.limit)
    else:
        print(f"\nВзаимных подписок: {len(report.mutual)} (показать: --show-mutual)")
    _print_warnings(report.warnings, ctx)


def _print_diff(report: DiffReport, args: argparse.Namespace, ctx: "_Context") -> None:
    period = (
        f", период {report.period_days:.1f} дн."
        if report.period_days is not None
        else ""
    )
    print(f"\n=== Изменения{period} ===")
    if report.old_captured_at:
        print(
            f"было: {report.old_captured_at.strftime('%Y-%m-%d %H:%M')} ({report.old_source}) → "
            f"стало: {report.new_captured_at.strftime('%Y-%m-%d %H:%M') if report.new_captured_at else '?'} "
            f"({report.new_source})"
        )
    _print_section("Новые подписчики", report.new_followers, args.limit)
    _print_section("Отписались от вас", report.unfollowers, args.limit)
    _print_section("Вы подписались", report.new_following, args.limit)
    _print_section("Вы отписались", report.unfollowed, args.limit)
    if report.renames:
        print(f"\nСменили ник (не считаются отпиской): {len(report.renames)}")
        for event in report.renames[: (args.limit or len(report.renames))]:
            print(f"  ~ {event.old_username} → {event.new_username}")
    if report.is_empty:
        print("Изменений нет.")
    _print_warnings(report.warnings, ctx)


def _print_section(title: str, users: Sequence[UserRef], limit: int) -> None:
    print(f"\n{title} ({len(users)}):")
    if not users:
        print("  —")
        return
    shown = users[:limit] if limit else users
    for ref in shown:
        extra = ""
        if ref.since:
            extra = f"  [{ref.since:%Y-%m-%d}]"
        print(f"  - {ref.display}{extra}")
    if limit and len(users) > limit:
        print(f"  … ещё {len(users) - limit} (все — в --format csv/json)")


def _print_warnings(warnings: Sequence[str], ctx: "_Context") -> None:
    if not warnings:
        return
    print("\n⚠ Достоверность:")
    for warning in warnings:
        print(f"  • {warning}")


def _snapshot_summary(snapshot: Snapshot) -> Dict[str, Any]:
    return {
        "username": snapshot.username,
        "captured_at": snapshot.captured_at.isoformat() if snapshot.captured_at else None,
        "source": snapshot.source,
        "counts": snapshot.to_dict()["counts"],
        "expected_counts": snapshot.expected_counts,
        "complete": snapshot.complete,
    }


def _emit_csv(report: Optional[FollowBackReport], diff: Optional[DiffReport], out: Optional[str]) -> None:
    rows: List[Tuple[str, ...]] = [CSV_HEADER]
    if report:
        for section, users in (
            ("not_following_back", report.not_following_back),
            ("followers_not_followed", report.followers_not_followed),
            ("mutual", report.mutual),
        ):
            rows.extend(_rows(section, users))
    if diff:
        for section, users in (
            ("new_followers", diff.new_followers),
            ("unfollowers", diff.unfollowers),
            ("new_following", diff.new_following),
            ("unfollowed", diff.unfollowed),
        ):
            rows.extend(_rows(section, users))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    _emit(buffer.getvalue().rstrip("\n"), out)


def _rows(section: str, users: Sequence[UserRef]):
    for ref in users:
        yield (
            section,
            ref.username,
            ref.full_name,
            ref.user_id,
            ref.since.isoformat() if ref.since else "",
            ref.profile_url,
        )


def _emit(text: str, out: Optional[str]) -> None:
    if not out:
        print(text)
        return
    path = Path(out).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    print(f"Результат записан в {path}")


# --- запуск --------------------------------------------------------------


class _Context:
    """Мелочи, общие для всех команд: настройки, хранилище, наблюдатель, вывод."""

    def __init__(self, settings: Settings, store: SnapshotStore) -> None:
        self.settings = settings
        self.store = store
        self.progress = ConsoleProgressObserver(quiet=settings.quiet)

    def info(self, message: str) -> None:
        print(message)

    def warn(self, message: str) -> None:
        print(message, file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    raw_args = list(sys.argv[1:] if argv is None else argv)
    # Старый запуск «python main.py USERNAME [--save]» без подкоманды.
    if raw_args and not raw_args[0].startswith("-") and raw_args[0] not in {
        "analyze",
        "snapshots",
        "session",
    }:
        raw_args.insert(0, "analyze")
    args = parser.parse_args(raw_args)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 1

    settings = load_settings()
    if getattr(args, "data_dir", None):
        settings.data_dir = Path(args.data_dir)
    if getattr(args, "allow_partial", False):
        settings.allow_partial = True
    if getattr(args, "quiet", False):
        settings.quiet = True
    if getattr(args, "limit", None) is not None and args.limit < 0:
        parser.error("--limit не может быть отрицательным")

    context = _Context(settings, SnapshotStore(settings.data_dir))
    try:
        return int(args.handler(args, context) or 0)
    except TrackerError as exc:
        print(f"\nОшибка: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nПрервано пользователем.", file=sys.stderr)
        return 130
    except Exception as exc:  # неожиданное — показываем тип, а не голый трейсбек
        if getattr(args, "verbose", False):
            raise
        print(
            f"\nНеожиданная ошибка {type(exc).__name__}: {exc}\n"
            "(повторите с --verbose, чтобы увидеть трейсбек)",
            file=sys.stderr,
        )
        return 3


def _version_string() -> str:
    from . import __version__

    return f"instagram-tracker {__version__} · Python {sys.version.split()[0]}"

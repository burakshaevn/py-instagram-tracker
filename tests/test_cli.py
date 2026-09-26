"""Сквозные проверки CLI: запуск без аргументов должен давать полезный результат."""

from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from conftest import write_export, zip_export  # noqa: E402


@pytest.fixture
def export_dir(tmp_path):
    return write_export(
        tmp_path / "export1",
        followers=["anna", "boris", "vera"],
        following=["anna", "elena", "kirill"],
        username="tester",
    )


def test_analyze_export_reports_non_followers(run_cli, capsys, export_dir, tmp_path):
    code = run_cli("analyze", "--export", str(export_dir), "--quiet", "--data-dir", str(tmp_path / "d"))
    out = capsys.readouterr().out
    assert code == 0
    assert "Вы подписаны, они — нет" in out
    assert "elena" in out and "kirill" in out
    assert "anna" not in out.split("не подписаны в ответ")[-1].split("Они подписаны")[0]


def test_autodiscovery_of_export_next_to_script(run_cli, capsys, export_dir, monkeypatch, tmp_path):
    """Каталог с files followers_1.json/following.json подхватывается без --export."""
    for name in ("followers_1.json", "following.json"):
        shutil.copy(export_dir / "connections" / "followers_and_following" / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    code = run_cli("analyze", "--quiet", "--data-dir", str(tmp_path / "d"))
    assert code == 0
    assert "подписчиков 3" in capsys.readouterr().out


def test_save_then_compare_detects_unfollowers(run_cli, capsys, tmp_path, export_dir):
    data_dir = tmp_path / "data"
    assert run_cli("analyze", "--export", str(export_dir), "--save", "--data-dir", str(data_dir), "--quiet") == 0

    second = write_export(
        tmp_path / "export2",
        followers=["anna", "gosha"],          # boris и vera отписались
        following=["anna", "elena", "kirill", "masha"],
        username="tester",
    )
    code = run_cli("analyze", "--export", str(second), "--compare", "--save", "--data-dir", str(data_dir), "--quiet")
    out = capsys.readouterr().out
    assert code == 0
    assert "Отписались от вас (2)" in out
    assert "boris" in out and "vera" in out
    assert "Новые подписки" not in out or "masha" in out
    assert sorted(p.name for p in (data_dir / "snapshots").glob("*.json"))[0].startswith("tester__")


def test_compare_against_explicit_export_file(run_cli, capsys, tmp_path, export_dir):
    archive = zip_export(
        write_export(
            tmp_path / "old",
            followers=["anna", "boris", "vera", "dima"],
            following=["anna"],
            username="tester",
        ),
        tmp_path / "old.zip",
    )
    code = run_cli("analyze", "--export", str(export_dir), "--compare", str(archive), "--quiet")
    assert code == 0
    out = capsys.readouterr().out
    assert "dima" in out  # был подписчиком, стал отписавшимся


def test_json_output_is_machine_readable(run_cli, capsys, export_dir, tmp_path):
    code = run_cli(
        "analyze", "--export", str(export_dir), "--format", "json", "--data-dir", str(tmp_path / "d"), "--quiet"
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["snapshot"]["username"] == "tester"
    assert payload["followback"]["counts"]["not_following_back"] == 2


def test_csv_output_written_to_file(run_cli, capsys, export_dir, tmp_path):
    out_file = tmp_path / "report.csv"
    code = run_cli(
        "analyze", "--export", str(export_dir), "--format", "csv", "--out", str(out_file),
        "--data-dir", str(tmp_path / "d"), "--quiet",
    )
    assert code == 0
    rows = list(csv.DictReader(out_file.read_text(encoding="utf-8").splitlines()))
    sections = {row["section"] for row in rows}
    assert {"not_following_back", "followers_not_followed"} <= sections
    assert {row["username"] for row in rows if row["section"] == "not_following_back"} == {"elena", "kirill"}


def test_snapshots_list_and_show(run_cli, capsys, export_dir, tmp_path):
    data_dir = tmp_path / "data"
    assert run_cli("analyze", "--export", str(export_dir), "--save", "--data-dir", str(data_dir), "--quiet") == 0
    capsys.readouterr()
    snap_path = sorted((data_dir / "snapshots").glob("*.json"))[0]

    assert run_cli("snapshots", "show", str(snap_path)) == 0
    assert "Подписчики (3)" in capsys.readouterr().out

    assert run_cli("snapshots", "list", "--data-dir", str(data_dir)) == 0
    assert "tester" in capsys.readouterr().out

    assert run_cli("snapshots", "list", "--data-dir", str(tmp_path / "empty")) == 1


def test_snapshots_diff_between_two_exports(run_cli, capsys, tmp_path):
    old = write_export(tmp_path / "e1", followers=["a", "b"], following=["c"], username="tester")
    new = write_export(tmp_path / "e2", followers=["a"], following=["c", "d"], username="tester")
    code = run_cli("snapshots", "diff", str(old), str(new), "--format", "json")
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"] == {"new_followers": 0, "unfollowers": 1, "new_following": 1, "unfollowed": 0}


def test_missing_data_source_explains_how_to_get_export(run_cli, capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = run_cli("analyze", "--data-dir", str(tmp_path / "d"))
    assert code == 2
    err = capsys.readouterr().err
    assert "Выгрузка Instagram" in err
    assert "sessionid" in err


def test_legacy_positional_invocation_still_works(run_cli, capsys, monkeypatch, tmp_path):
    """Старый вызов `python main.py USERNAME` по-прежнему разбирается, а не падает."""
    empty = tmp_path / "nowhere"
    empty.mkdir()
    monkeypatch.chdir(empty)
    code = run_cli("tester", "--data-dir", str(empty / "d"))
    assert code == 2
    assert "Нечем читать данные" in capsys.readouterr().err


def test_limit_truncates_console_but_not_counts(run_cli, capsys, export_dir, tmp_path):
    code = run_cli(
        "analyze", "--export", str(export_dir), "--limit", "1", "--data-dir", str(tmp_path / "d"), "--quiet"
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "ещё 1" in out


def shutil_copy(src: Path, dst: Path) -> None:
    dst.write_bytes(src.read_bytes())

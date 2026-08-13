"""增量同步判断、一键目标选择和 Zotero/Obsidian 跳转。"""
from types import SimpleNamespace

from gui import app as app_module
from gui.app import App, _generation_targets, _needs_sync, _obsidian_uri, _zotero_uri
from obsidian_writer import NoteState


def _note(source="old", path="C:/Vault/Paper.md"):
    return NoteState("K1", "ok", 1.0, path, source)


def test_needs_sync_only_for_existing_note_with_changed_source():
    paper = {"key": "K1", "source_modified": "new"}
    assert _needs_sync(paper, _note("new")) is False
    assert _needs_sync(paper, _note("old")) is True
    assert _needs_sync(paper, _note("")) is True  # 历史笔记首轮建立基线
    assert _needs_sync(paper, None) is False
    assert _needs_sync({"key": "K1"}, _note()) is False


def test_paper_state_preserves_quality_until_source_changes():
    paper = {"key": "K1", "source_modified": "new"}
    app = SimpleNamespace(notes={"K1": _note("new")}, failed_keys=set())
    assert App._paper_state(app, paper) == ("ok", 1.0)
    app.notes["K1"] = _note("old")
    assert App._paper_state(app, paper) == ("stale", 1.0)
    app.failed_keys.add("K1")
    assert App._paper_state(app, paper) == ("stale", 1.0)  # 更新失败后仍留在待同步


def test_pending_sync_uses_visible_rows_only_when_nothing_selected():
    selected = SimpleNamespace(selected=lambda: True)
    other = SimpleNamespace(selected=lambda: False)
    rows = {"A": selected, "B": other}
    assert _generation_targets(rows, "待同步") == [selected]
    rows = {"B": other}
    assert _generation_targets(rows, "待同步") == [other]
    assert _generation_targets(rows, "全部") == []


def test_uri_builders_percent_encode_paths(tmp_path):
    note = tmp_path / "中文 笔记.md"
    assert _zotero_uri("AB C") == "zotero://select/library/items/AB%20C"
    uri = _obsidian_uri(str(note))
    assert uri.startswith("obsidian://open?path=")
    assert "%20" in uri and "%E4%B8%AD%E6%96%87" in uri


def test_open_targets_use_startfile_and_actual_note_path(tmp_path, monkeypatch):
    note = tmp_path / "renamed note.md"
    note.write_text("# note", encoding="utf-8")
    opened = []
    monkeypatch.setattr(app_module.os, "startfile", opened.append, raising=False)
    app = SimpleNamespace(
        papers=[{"key": "K1", "pdf_path": None}],
        writer=SimpleNamespace(find_note=lambda key: str(note)),
        _set_status=lambda message: None,
    )

    App.open_target(app, "zotero", "K1")
    App.open_target(app, "obsidian", "K1")

    assert opened == [_zotero_uri("K1"), _obsidian_uri(str(note))]


def test_generation_commit_receives_source_baseline(monkeypatch):
    captured = {}
    writer = SimpleNamespace(
        commit_generation=lambda *args, **kwargs: captured.update(kwargs) or []
    )
    row = SimpleNamespace(
        paper={"key": "K1", "title": "Paper", "source_modified": "source-v2"},
        note_key="cite",
    )
    monkeypatch.setattr(
        app_module, "generate_note",
        lambda paper, cfg, note_key: {"figures": [], "content": "note", "status": "ok"},
    )

    assert App._run_generate(SimpleNamespace(), row, writer, {}) == (True, "ok", "OK")
    assert captured["zotero_source"] == "source-v2"

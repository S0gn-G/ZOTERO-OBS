"""按需自动接入的 provider、聚合器与应用编排。"""
from __future__ import annotations

import json
import os
import queue

import pytest
import requests

from discovery.core import (
    DiscoveryCandidate,
    DiscoveryError,
    DiscoveryFailure,
    DiscoveryKind,
    DiscoveryReport,
    DiscoveryService,
    notes_path_for_vault,
)
from discovery import default_discovery_service
from discovery.obsidian import ObsidianVaultProvider
from discovery.zotero import ZoteroLocalApiProvider
import gui.app as app_module
from gui import design as ui
from gui.app import App


def _candidate(kind, identity="one", value="C:/target"):
    return DiscoveryCandidate("test", kind, identity, identity, value, value)


class _Provider:
    def __init__(self, kind, result=None, error=None):
        self.provider_id = f"test.{kind.value}"
        self.kind = kind
        self.result = result or []
        self.error = error
        self.calls = 0

    def discover(self):
        self.calls += 1
        if self.error:
            raise DiscoveryError(self.error)
        return self.result


def test_service_does_not_run_providers_until_explicit_discover():
    provider = _Provider(DiscoveryKind.OBSIDIAN_VAULT)
    service = DiscoveryService([provider])

    assert provider.calls == 0
    service.discover()
    assert provider.calls == 1


def test_default_discovery_service_is_inert_until_discover(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ZoteroLocalApiProvider, "discover", lambda _self: calls.append("zotero")
    )
    monkeypatch.setattr(
        ObsidianVaultProvider, "discover", lambda _self: calls.append("obsidian")
    )

    assert default_discovery_service() is not None
    assert calls == []


def test_service_filters_kinds_and_isolates_expected_provider_failure():
    zotero = _Provider(
        DiscoveryKind.ZOTERO_API,
        result=[_candidate(DiscoveryKind.ZOTERO_API)],
    )
    obsidian = _Provider(DiscoveryKind.OBSIDIAN_VAULT, error="broken registry")
    service = DiscoveryService([obsidian, zotero])

    zotero_only = service.discover([DiscoveryKind.ZOTERO_API])
    assert len(zotero_only.candidates) == 1
    assert not zotero_only.failures
    assert obsidian.calls == 0

    report = service.discover()
    assert len(report.candidates_for(DiscoveryKind.ZOTERO_API)) == 1
    assert report.failures[0].message == "broken registry"


def _write_obsidian_config(path, vaults):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"vaults": vaults}), encoding="utf-8")


def test_obsidian_provider_uses_appdata_registry(tmp_path, monkeypatch):
    appdata = tmp_path / "Roaming"
    vault = tmp_path / "Vault"
    vault.mkdir()
    _write_obsidian_config(
        appdata / "obsidian" / "obsidian.json",
        {"default": {"path": str(vault)}},
    )
    monkeypatch.setenv("APPDATA", str(appdata))

    candidates = ObsidianVaultProvider().discover()

    assert [candidate.value for candidate in candidates] == [str(vault)]


def test_obsidian_provider_returns_single_unicode_vault(tmp_path):
    vault = tmp_path / "论文 Vault"
    vault.mkdir()
    config_path = tmp_path / "obsidian.json"
    _write_obsidian_config(config_path, {
        "abc123": {"path": str(vault), "ts": 8, "open": True},
    })

    candidates = ObsidianVaultProvider(config_path).discover()

    assert len(candidates) == 1
    assert candidates[0].label == "论文 Vault"
    assert candidates[0].value == os.path.abspath(vault)
    assert notes_path_for_vault(candidates[0]) == os.path.join(vault, "LiteratureNotes")
    assert not (vault / "LiteratureNotes").exists()


def test_obsidian_provider_returns_all_valid_vaults_in_stable_order(tmp_path):
    recent = tmp_path / "Recent"
    open_vault = tmp_path / "Open"
    older = tmp_path / "Older"
    for vault in (recent, open_vault, older):
        vault.mkdir()
    config_path = tmp_path / "obsidian.json"
    _write_obsidian_config(config_path, {
        "recent": {"path": str(recent), "ts": 30, "open": False},
        "open": {"path": str(open_vault), "ts": 10, "open": True},
        "older": {"path": str(older), "ts": 5, "open": False},
        "missing": {"path": str(tmp_path / "Missing"), "ts": 99, "open": True},
    })

    candidates = ObsidianVaultProvider(config_path).discover()

    assert [candidate.identity for candidate in candidates] == ["open", "recent", "older"]


def test_obsidian_provider_rejects_blank_and_relative_paths(tmp_path, monkeypatch):
    relative = tmp_path / "relative" / "Vault"
    relative.mkdir(parents=True)
    config_path = tmp_path / "obsidian.json"
    _write_obsidian_config(config_path, {
        "empty": {"path": ""},
        "dot": {"path": "."},
        "relative": {"path": os.path.join("relative", "Vault")},
        "absolute": {"path": str(relative)},
    })
    monkeypatch.chdir(tmp_path)

    candidates = ObsidianVaultProvider(config_path).discover()

    assert [candidate.identity for candidate in candidates] == ["absolute"]


def test_obsidian_provider_deduplicates_paths_after_ranking(tmp_path):
    vault = tmp_path / "Vault"
    vault.mkdir()
    config_path = tmp_path / "obsidian.json"
    _write_obsidian_config(config_path, {
        "closed-new": {"path": str(vault), "open": False, "ts": 100},
        "open-old": {"path": str(vault) + os.sep, "open": True, "ts": 1},
    })

    candidates = ObsidianVaultProvider(config_path).discover()

    assert [candidate.identity for candidate in candidates] == ["open-old"]


def test_obsidian_provider_only_accepts_literal_true_as_open(tmp_path):
    real_open = tmp_path / "Real Open"
    false_text = tmp_path / "False Text"
    real_open.mkdir()
    false_text.mkdir()
    config_path = tmp_path / "obsidian.json"
    _write_obsidian_config(config_path, {
        "false-text": {"path": str(false_text), "open": "false", "ts": 999},
        "real-open": {"path": str(real_open), "open": True, "ts": 1},
    })

    candidates = ObsidianVaultProvider(config_path).discover()

    assert [candidate.identity for candidate in candidates] == ["real-open", "false-text"]


def test_obsidian_provider_missing_or_empty_registry_returns_no_candidates(tmp_path):
    missing = tmp_path / "missing.json"
    assert ObsidianVaultProvider(missing).discover() == []

    empty = tmp_path / "empty.json"
    _write_obsidian_config(empty, {})
    assert ObsidianVaultProvider(empty).discover() == []


def test_obsidian_provider_reports_corrupt_registry(tmp_path):
    config_path = tmp_path / "obsidian.json"
    config_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(DiscoveryError, match="无法读取"):
        ObsidianVaultProvider(config_path).discover()


def test_obsidian_provider_reports_invalid_text_encoding(tmp_path):
    config_path = tmp_path / "obsidian.json"
    config_path.write_bytes(b"\xff")

    with pytest.raises(DiscoveryError, match="无法读取"):
        ObsidianVaultProvider(config_path).discover()


def test_obsidian_provider_reports_invalid_root(tmp_path):
    config_path = tmp_path / "obsidian.json"
    config_path.write_text("[]", encoding="utf-8")

    with pytest.raises(DiscoveryError, match="格式无效"):
        ObsidianVaultProvider(config_path).discover()


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self.payload = [] if payload is None else payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_zotero_provider_probes_small_request_with_bounded_timeout():
    calls = []

    def get(url, timeout):
        calls.append((url, timeout))
        return _Response(200)

    candidates = ZoteroLocalApiProvider(timeout=1.25, http_get=get).discover()

    assert len(candidates) == 1
    assert calls == [("http://127.0.0.1:23119/api/users/0/items?start=0&limit=1", 1.25)]


@pytest.mark.parametrize("outcome", [requests.ConnectionError(), requests.Timeout(), _Response(503)])
def test_zotero_provider_reports_offline_or_non_200(outcome):
    def get(_url, _timeout=None, timeout=None):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    with pytest.raises(DiscoveryError):
        ZoteroLocalApiProvider(http_get=get).discover()


@pytest.mark.parametrize("payload", [{}, ValueError("invalid JSON")])
def test_zotero_provider_rejects_invalid_200_response(payload):
    with pytest.raises(DiscoveryError, match="响应格式无效"):
        ZoteroLocalApiProvider(http_get=lambda *_args, **_kwargs: _Response(200, payload)).discover()


def test_discovery_worker_invokes_service_only_when_called():
    report = DiscoveryReport(())

    class Service:
        calls = 0

        def discover(self):
            self.calls += 1
            return report

    class Dummy:
        discovery_service = Service()
        applied = []

        def _post(self, function):
            function()

        def _apply_auto_discovery(self, value):
            self.applied.append(value)

        def _show_discovery_error(self, _message):
            raise AssertionError("unexpected error")

    dummy = Dummy()
    assert dummy.discovery_service.calls == 0
    App._discovery_worker(dummy)
    assert dummy.discovery_service.calls == 1
    assert dummy.applied == [report]


def test_ui_queue_reschedules_after_callback_error():
    class Dummy:
        _destroyed = False
        _ui_queue = queue.Queue()
        scheduled = []

        def after(self, delay, callback):
            self.scheduled.append((delay, callback))

        def _poll_ui_queue(self):
            App._poll_ui_queue(self)

    dummy = Dummy()
    dummy._ui_queue.put(lambda: (_ for _ in ()).throw(RuntimeError("broken callback")))

    with pytest.raises(RuntimeError, match="broken callback"):
        App._poll_ui_queue(dummy)

    assert dummy.scheduled == [(50, dummy._poll_ui_queue)]


def test_fit_window_uses_logical_screen_size():
    class Window:
        def _reverse_window_scaling(self, value):
            return value / 1.25

        def winfo_screenwidth(self):
            return 1366

        def winfo_screenheight(self):
            return 768

        def geometry(self, value):
            self.size = value

        def minsize(self, width, height):
            self.minimum = (width, height)

    window = Window()
    ui.fit_window(window, (1220, 820), (900, 560), (64, 80))

    assert window.size == "1028x534"
    assert window.minimum == (900, 534)


def test_multiple_vaults_open_dedicated_selector_without_mutating_config(monkeypatch):
    vaults = (
        _candidate(DiscoveryKind.OBSIDIAN_VAULT, "one", "C:/One"),
        _candidate(DiscoveryKind.OBSIDIAN_VAULT, "two", "C:/Two"),
    )
    report = DiscoveryReport(vaults)
    opened = []

    def dialog(master, candidates, on_selected, on_cancel):
        opened.append((master, tuple(candidates), on_selected, on_cancel))

    monkeypatch.setattr(app_module, "VaultSelectionDialog", dialog)
    busy_changes = []

    class Dummy:
        cfg = {"notes_path": "unchanged"}

        def _set_busy(self, busy):
            busy_changes.append(busy)

        def _set_status(self, _text):
            pass

        def _cancel_auto_connect(self):
            App._cancel_auto_connect(self)

    dummy = Dummy()
    App._apply_auto_discovery(dummy, report)

    assert len(opened) == 1
    assert opened[0][1] == vaults
    assert dummy.cfg["notes_path"] == "unchanged"
    assert busy_changes == []
    opened[0][3]()
    assert busy_changes == [False]


def test_explicit_vault_selection_persists_target_and_refreshes_zotero(monkeypatch):
    vault = _candidate(DiscoveryKind.OBSIDIAN_VAULT, "papers", "D:/Vault")
    zotero = _candidate(
        DiscoveryKind.ZOTERO_API,
        "zotero",
        "http://127.0.0.1:23119/api/",
    )
    saved = []
    monkeypatch.setattr(app_module, "save_config", lambda cfg: saved.append(dict(cfg)))

    class Dummy:
        cfg = {"notes_path": "D:/Old"}
        writer = None
        statuses = []
        refreshes = 0
        refresh_status = None

        def _set_busy(self, _busy):
            pass

        def _set_status(self, text):
            self.statuses.append(text)

        def refresh(self, success_status=None):
            self.refreshes += 1
            self.refresh_status = success_status

    dummy = Dummy()
    App._complete_auto_connect(dummy, vault, zotero, DiscoveryReport((vault, zotero)))

    expected = os.path.join("D:/Vault", "LiteratureNotes")
    assert dummy.cfg["notes_path"] == expected
    assert dummy.writer.notes_dir == expected
    assert saved == [{"notes_path": expected}]
    assert dummy.refreshes == 1
    assert dummy.zotero_base_url == "http://127.0.0.1:23119/api/"
    assert dummy.refresh_status == "已自动接入 Zotero 与 papers"


def test_auto_connect_save_failure_preserves_previous_state(monkeypatch):
    vault = _candidate(DiscoveryKind.OBSIDIAN_VAULT, "papers", "D:/Vault")
    zotero = _candidate(
        DiscoveryKind.ZOTERO_API, "zotero", "http://127.0.0.1:9999/api/"
    )
    old_writer = object()
    monkeypatch.setattr(
        app_module, "save_config", lambda _cfg: (_ for _ in ()).throw(OSError("read-only"))
    )

    class Dummy:
        cfg = {"notes_path": "D:/Old"}
        writer = old_writer
        zotero_base_url = "http://127.0.0.1:23119/api/"
        statuses = []
        busy = True
        refreshes = 0

        def _set_busy(self, busy):
            self.busy = busy

        def _set_status(self, text):
            self.statuses.append(text)

        def _show_discovery_error(self, message):
            App._show_discovery_error(self, message)

        def refresh(self, _success_status=None):
            self.refreshes += 1

    dummy = Dummy()
    App._complete_auto_connect(dummy, vault, zotero, DiscoveryReport((vault, zotero)))

    assert dummy.cfg == {"notes_path": "D:/Old"}
    assert dummy.writer is old_writer
    assert dummy.zotero_base_url == "http://127.0.0.1:23119/api/"
    assert dummy.refreshes == 0
    assert not dummy.busy
    assert "无法保存设置" in dummy.statuses[-1]


def test_obsidian_failure_is_visible_when_zotero_connects():
    zotero = _candidate(
        DiscoveryKind.ZOTERO_API, "zotero", "http://127.0.0.1:23119/api/"
    )
    failure = DiscoveryFailure(
        "obsidian.vaults", DiscoveryKind.OBSIDIAN_VAULT, "无法读取 Obsidian Vault 注册信息"
    )

    class Dummy:
        zotero_base_url = None
        refresh_status = None

        def _set_busy(self, _busy):
            pass

        def refresh(self, success_status=None):
            self.refresh_status = success_status

    dummy = Dummy()
    App._complete_auto_connect(dummy, None, zotero, DiscoveryReport((zotero,), (failure,)))

    assert dummy.refresh_status == "已连接 Zotero；无法读取 Obsidian Vault 注册信息"


def test_refresh_worker_uses_discovered_zotero_url(monkeypatch):
    used_urls = []

    class Client:
        def __init__(self, base_url):
            used_urls.append(base_url)

        def fetch_papers(self):
            return []

    class Writer:
        def scan_states(self):
            return []

    class Dummy:
        applied = []

        def _post(self, function):
            function()

        def _apply_refresh(self, result):
            self.applied.append(result)

        def _show_error(self, message):
            raise AssertionError(message)

    monkeypatch.setattr(app_module, "ZoteroClient", Client)
    dummy = Dummy()
    App._refresh_worker(dummy, Writer(), "http://127.0.0.1:9999/api/", "已接入")

    assert used_urls == ["http://127.0.0.1:9999/api/"]
    assert dummy.applied == [([], [], "已接入")]

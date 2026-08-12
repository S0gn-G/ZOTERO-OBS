"""配置精简、旧版迁移与原子保存。"""
import json
import os

import pytest

import config


def test_load_config_migrates_old_vault_and_drops_removed_keys(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "vault_path": "D:/Vault",
        "notes_folder": "Papers",
        "overwrite": True,
        "llm_model": "model-x",
    }), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))

    cfg = config.load_config()

    assert cfg["notes_path"] == os.path.join("D:/Vault", "Papers")
    assert cfg["llm_model"] == "model-x"
    assert cfg["appearance_mode"] == "light"
    assert "overwrite" not in cfg
    assert "vault_path" not in cfg


def test_load_config_invalid_appearance_mode_falls_back_to_light(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"appearance_mode": "sepia"}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))

    cfg = config.load_config()

    assert cfg["appearance_mode"] == "light"


@pytest.mark.parametrize("content", ["[]", "null"])
def test_load_config_non_object_uses_defaults(tmp_path, monkeypatch, content):
    path = tmp_path / "config.json"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))

    assert config.load_config() == config.DEFAULT_CONFIG


def test_load_config_invalid_text_uses_defaults(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_bytes(b"\xff")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))

    assert config.load_config() == config.DEFAULT_CONFIG


def test_dark_appearance_mode_round_trips(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    cfg = dict(config.DEFAULT_CONFIG)
    cfg["appearance_mode"] = "dark"

    config.save_config(cfg)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["appearance_mode"] == "dark"
    assert config.load_config()["appearance_mode"] == "dark"


def test_save_config_persists_only_current_settings(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    cfg = dict(config.DEFAULT_CONFIG)
    cfg.update({"notes_path": "D:/Notes", "overwrite": True})

    config.save_config(cfg)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["notes_path"] == "D:/Notes"
    assert set(saved) == set(config.DEFAULT_CONFIG)
    assert not (tmp_path / "config.json.tmp").exists()


def test_save_config_replace_failure_keeps_original_and_cleans_tmp(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"notes_path": "old"}', encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    monkeypatch.setattr(
        config.os, "replace", lambda *_args: (_ for _ in ()).throw(PermissionError("locked"))
    )

    with pytest.raises(PermissionError, match="locked"):
        config.save_config({**config.DEFAULT_CONFIG, "notes_path": "new"})

    assert json.loads(path.read_text(encoding="utf-8"))["notes_path"] == "old"
    assert not (tmp_path / "config.json.tmp").exists()

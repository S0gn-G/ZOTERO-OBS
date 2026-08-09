"""配置精简、旧版迁移与原子保存。"""
import json
import os

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
    assert "overwrite" not in cfg
    assert "vault_path" not in cfg


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

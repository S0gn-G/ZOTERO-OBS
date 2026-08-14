"""从 Obsidian 的本地注册文件发现有效 Vault。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from discovery.core import DiscoveryCandidate, DiscoveryError, DiscoveryKind


class ObsidianVaultProvider:
    provider_id = "obsidian.vaults"
    kind = DiscoveryKind.OBSIDIAN_VAULT

    def __init__(self, config_path: str | os.PathLike | None = None):
        self._config_path = Path(config_path) if config_path is not None else None

    def _path(self) -> Path | None:
        if self._config_path is not None:
            return self._config_path
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "obsidian" / "obsidian.json" if appdata else None

    def discover(self) -> list[DiscoveryCandidate]:
        config_path = self._path()
        if config_path is None or not config_path.is_file():
            return []
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DiscoveryError("无法读取 Obsidian Vault 注册信息") from exc
        if not isinstance(payload, dict):
            raise DiscoveryError("Obsidian Vault 注册信息格式无效")

        vaults = payload.get("vaults", {})
        if not isinstance(vaults, dict):
            raise DiscoveryError("Obsidian Vault 注册信息格式无效")

        records = []
        for vault_id, entry in vaults.items():
            if not isinstance(entry, dict):
                continue
            raw_path = entry.get("path")
            if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
                continue
            vault_path = os.path.abspath(os.path.normpath(raw_path))
            if not os.path.isdir(vault_path):
                continue
            timestamp = entry.get("ts") if isinstance(entry.get("ts"), (int, float)) else 0
            candidate = DiscoveryCandidate(
                provider_id=self.provider_id,
                kind=self.kind,
                identity=str(vault_id),
                label=os.path.basename(vault_path) or vault_path,
                value=vault_path,
                detail=vault_path,
            )
            records.append((entry.get("open") is True, timestamp, candidate))

        records.sort(key=lambda item: (
            -int(item[0]), -item[1], item[2].label.casefold(), item[2].value.casefold()
        ))
        seen = set()
        candidates = []
        for _is_open, _timestamp, candidate in records:
            path_key = os.path.normcase(candidate.value)
            if path_key not in seen:
                seen.add(path_key)
                candidates.append(candidate)
        return candidates

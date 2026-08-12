"""自动发现的稳定契约与聚合器。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from typing import Iterable, Protocol


class DiscoveryKind(str, Enum):
    ZOTERO_API = "zotero_api"
    OBSIDIAN_VAULT = "obsidian_vault"


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    provider_id: str
    kind: DiscoveryKind
    identity: str
    label: str
    value: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class DiscoveryFailure:
    provider_id: str
    kind: DiscoveryKind
    message: str


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    candidates: tuple[DiscoveryCandidate, ...]
    failures: tuple[DiscoveryFailure, ...] = ()

    def candidates_for(self, kind: DiscoveryKind) -> tuple[DiscoveryCandidate, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.kind == kind)


class DiscoveryError(Exception):
    """Provider 可以预期的发现失败。"""


class DiscoveryProvider(Protocol):
    provider_id: str
    kind: DiscoveryKind

    def discover(self) -> list[DiscoveryCandidate]: ...


class DiscoveryService:
    """按注册顺序运行相互独立的 provider，并汇总候选项。"""

    def __init__(self, providers: Iterable[DiscoveryProvider]):
        self._providers = tuple(providers)

    def discover(self, kinds: Iterable[DiscoveryKind] | None = None) -> DiscoveryReport:
        requested = set(kinds) if kinds is not None else None
        candidates: list[DiscoveryCandidate] = []
        failures: list[DiscoveryFailure] = []
        for provider in self._providers:
            if requested is not None and provider.kind not in requested:
                continue
            try:
                candidates.extend(provider.discover())
            except DiscoveryError as exc:
                failures.append(DiscoveryFailure(
                    provider_id=provider.provider_id,
                    kind=provider.kind,
                    message=str(exc),
                ))
        return DiscoveryReport(tuple(candidates), tuple(failures))


def notes_path_for_vault(candidate: DiscoveryCandidate) -> str:
    """把 Vault 候选映射为 ZotNotes 的最终笔记目录。"""
    return os.path.join(candidate.value, "LiteratureNotes")

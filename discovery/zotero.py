"""探测 Zotero 本地 API，不读取完整文献库。"""
from __future__ import annotations

from collections.abc import Callable

import requests

from discovery.core import DiscoveryCandidate, DiscoveryError, DiscoveryKind
from zotero_client import DEFAULT_BASE_URL


class ZoteroLocalApiProvider:
    provider_id = "zotero.local_api"
    kind = DiscoveryKind.ZOTERO_API

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 2.0,
        http_get: Callable | None = None,
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self._http_get = http_get

    def discover(self) -> list[DiscoveryCandidate]:
        http_get = self._http_get or requests.get
        probe_url = self.base_url.rstrip("/") + "/users/0/items?start=0&limit=1"
        try:
            response = http_get(probe_url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise DiscoveryError("未检测到正在运行的 Zotero 本地 API") from exc
        if response.status_code != 200:
            raise DiscoveryError(f"Zotero 本地 API 返回 {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DiscoveryError("Zotero 本地 API 响应格式无效") from exc
        if not isinstance(payload, list):
            raise DiscoveryError("Zotero 本地 API 响应格式无效")
        return [DiscoveryCandidate(
            provider_id=self.provider_id,
            kind=self.kind,
            identity=self.base_url,
            label="Zotero 本地文献库",
            value=self.base_url,
            detail=self.base_url,
        )]

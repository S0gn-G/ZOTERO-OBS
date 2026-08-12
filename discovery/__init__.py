"""ZotNotes 内部发现插件的装配入口。"""
from discovery.core import DiscoveryService
from discovery.obsidian import ObsidianVaultProvider
from discovery.zotero import ZoteroLocalApiProvider


def default_discovery_service() -> DiscoveryService:
    """仅装配 provider；直到用户点击“自动接入”才执行任何探测。"""
    return DiscoveryService([
        ZoteroLocalApiProvider(),
        ObsidianVaultProvider(),
    ])


__all__ = ["default_discovery_service"]

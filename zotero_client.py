"""Zotero 本地 HTTP API 客户端：拉取文献列表、解析 PDF 路径、解析引文键。"""
import re
import urllib.parse
from datetime import datetime

import requests

PAGE_SIZE = 100   # Zotero API 单页上限
MAX_ITEMS = 20000  # 安全上限，防服务端异常时死循环


class ZoteroError(Exception):
    pass


def _parse_year(date_str: str | None) -> str:
    if not date_str:
        return ""
    m = re.search(r"\d{4}", date_str)
    return m.group(0) if m else ""


def _clean_author_name(s: str) -> str:
    return re.sub(r"[\s　]+", " ", s or "").strip()


class ZoteroClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def _get(self, path: str):
        return self._get_resp(path).json()

    def _get_resp(self, path: str) -> requests.Response:
        """发 GET 并校验状态码，返回 Response（分页需要读 Total-Results 头）。"""
        try:
            r = requests.get(self.base + path, timeout=15)
        except requests.RequestException as e:
            raise ZoteroError(f"无法连接 Zotero API（{self.base}）：{e}") from e
        if r.status_code != 200:
            raise ZoteroError(f"Zotero API 返回 {r.status_code}: {path}")
        return r

    def fetch_papers(self) -> list[dict]:
        """返回所有文献条目（不含附件/笔记/批注），每项含:
        key, itemType, title, authors, year, date, doi, url, abstract,
        tags, citationKey, pdf_path
        """
        # 翻页拉全：start 是 0 基偏移，limit 页大小。终止条件三重保险
        # （Total-Results 头 / 满页才翻 / 安全上限），空库立即结束。
        items = []
        start = 0
        while True:
            resp = self._get_resp(f"/users/0/items?start={start}&limit={PAGE_SIZE}")
            page = resp.json()
            items.extend(page)
            total = int(resp.headers.get("Total-Results", start + len(page)))
            start += PAGE_SIZE
            if start >= total or len(page) < PAGE_SIZE or start >= MAX_ITEMS:
                break
        by_key = {i["key"]: i for i in items}
        papers = []
        for it in items:
            d = it.get("data", {})
            if d.get("itemType") in ("attachment", "annotation", "note"):
                continue
            papers.append(self._to_paper(it, by_key))
        return papers

    @staticmethod
    def _find_pdf(it, by_key) -> dict | None:
        key = it["key"]
        for child in by_key.values():
            cd = child.get("data", {})
            if (
                cd.get("itemType") == "attachment"
                and cd.get("parentItem") == key
                and cd.get("contentType") == "application/pdf"
            ):
                return child
        return None

    @staticmethod
    def _pdf_path(att) -> str | None:
        if not att:
            return None
        href = att.get("links", {}).get("enclosure", {}).get("href", "")
        if href.startswith("file://"):
            from urllib.request import url2pathname

            parsed = urllib.parse.urlparse(href)
            return url2pathname(urllib.parse.unquote(parsed.path))
        return None

    def _to_paper(self, it, by_key) -> dict:
        d = it.get("data", {})
        creators = d.get("creators", []) or []
        authors = [
            _clean_author_name(
                f"{c.get('lastName', '')} {c.get('firstName', '')}".strip()
            )
            for c in creators
            if c.get("lastName") or c.get("firstName")
        ]
        att = self._find_pdf(it, by_key)
        return {
            "key": it["key"],
            "itemType": d.get("itemType", ""),
            "title": d.get("title") or d.get("name") or "Untitled",
            "authors": authors,
            "first_author": _clean_author_name(
                f"{creators[0].get('lastName','')} {creators[0].get('firstName','')}".strip()
                if creators else ""
            ),
            "year": _parse_year(d.get("date")),
            "date": d.get("date") or "",
            "doi": d.get("DOI") or "",
            "url": d.get("url") or "",
            "abstract": (d.get("abstractNote") or "").strip(),
            "tags": [t.get("tag", "") for t in (d.get("tags") or [])],
            "citationKey": d.get("citationKey") or d.get("citekey") or "",
            "pdf_path": self._pdf_path(att),
            "dateAdded": d.get("dateAdded") or "",
        }

    @staticmethod
    def fallback_citation_key(paper: dict) -> str:
        """没有 Better BibTeX 时，用 首作者+年份 生成键；冲突时追加 Zotero key。
        输出仅含 ASCII，保证可用作文件名。"""
        import unicodedata

        def ascii_only(s: str) -> str:
            s = unicodedata.normalize("NFKD", s or "")
            return "".join(c for c in s if c.isascii() and (c.isalnum() or c == "_"))

        base = ascii_only(paper["first_author"]) or "Unknown"
        year = paper["year"]
        key = f"{base}{year}"
        return f"{key}-{paper['key']}"

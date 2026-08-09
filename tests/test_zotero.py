"""zotero_client 单元测试：日期/作者/PDF 路径解析、引文键、附件索引、分页。"""
from zotero_client import ZoteroClient, _parse_year, _clean_author_name


def test_parse_year():
    assert _parse_year("2021-01-05") == "2021"
    assert _parse_year("n.d.") == ""
    assert _parse_year("") == ""


def test_clean_author_name():
    assert _clean_author_name("  张  三  ") == "张 三"
    assert _clean_author_name("") == ""
    assert _clean_author_name("Zhang San") == "Zhang San"


def test_pdf_path():
    att = {"links": {"enclosure": {"href": "file:///C:/Papers/a%20b.pdf"}}}
    path = ZoteroClient._pdf_path(att)
    assert path.endswith("a b.pdf")


def test_pdf_path_none():
    assert ZoteroClient._pdf_path(None) is None
    assert ZoteroClient._pdf_path({}) is None


def test_fallback_citation_key_ascii():
    p = {"first_author": "Wang", "year": "2021", "key": "ABC123"}
    assert ZoteroClient.fallback_citation_key(p) == "Wang2021-ABC123"


def test_fallback_citation_key_nonascii():
    p = {"first_author": "张三", "year": "2021", "key": "ABC123"}
    assert ZoteroClient.fallback_citation_key(p) == "Unknown2021-ABC123"


def test_fallback_citation_key_all_ascii():
    key = ZoteroClient.fallback_citation_key({"first_author": "Wang", "year": "2021", "key": "ABC"})
    assert all(c.isascii() for c in key)


def test_to_paper_with_attachment_index():
    att = {
        "key": "ATT1",
        "data": {"itemType": "attachment", "contentType": "application/pdf", "parentItem": "ITEM1"},
        "links": {"enclosure": {"href": "file:///C:/Papers/paper.pdf"}},
    }
    it = {
        "key": "ITEM1",
        "data": {
            "itemType": "journalArticle",
            "title": "My Paper",
            "date": "2022-03-01",
            "DOI": "10.1/x",
            "url": "http://x",
            "abstractNote": "abs",
            "tags": [{"tag": "sr"}],
            "citationKey": "wang2022",
            "creators": [{"lastName": "Wang", "firstName": "Li"}],
        },
    }
    p = ZoteroClient("http://x")._to_paper(it, {"ITEM1": att})
    assert p["key"] == "ITEM1"
    assert p["title"] == "My Paper"
    assert p["year"] == "2022"
    assert p["authors"] == ["Wang Li"]
    assert p["citationKey"] == "wang2022"
    assert p["tags"] == ["sr"]
    assert p["pdf_path"].endswith("paper.pdf")


def test_fetch_papers_pagination(monkeypatch):
    calls = []

    class FakeResp:
        def __init__(self, page, total):
            self._json = page
            self.headers = {"Total-Results": str(total)}

        def json(self):
            return self._json

    def fake_get_resp(self, path):
        calls.append(path)
        if "start=0" in path:
            return FakeResp([{"key": f"A{i}"} for i in range(100)], 150)
        return FakeResp([{"key": f"B{i}"} for i in range(50)], 150)

    monkeypatch.setattr(ZoteroClient, "_get_resp", fake_get_resp)
    papers = ZoteroClient("http://x").fetch_papers()
    assert len(calls) == 2
    assert len(papers) == 150

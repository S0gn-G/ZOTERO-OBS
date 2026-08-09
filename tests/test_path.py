"""路径与转义安全测试：safe_citekey 防目录穿越 / YAML 转义防非法 frontmatter。"""
from obsidian_writer import safe_citekey
from note_generator import _yaml_escape, _placeholder_vals


def test_yaml_escape_backslash():
    assert _yaml_escape(r"C:\Users\a\b") == r"C:\\Users\\a\\b"


def test_yaml_escape_quote():
    assert _yaml_escape('a"b') == 'a\\"b'


def _paper(**kw):
    base = {
        "key": "K1", "title": "T", "authors": [], "first_author": "A",
        "year": "2021", "date": "", "doi": "", "url": "", "abstract": "",
        "tags": [], "citationKey": "cite", "pdf_path": None,
        "itemType": "journalArticle", "dateAdded": "",
    }
    base.update(kw)
    return base


def test_placeholder_vals_pdf_doubles_backslash():
    paper = _paper(pdf_path=r"C:\Users\p\paper.pdf")
    vals = _placeholder_vals(paper, "cite.md")
    assert vals["pdf"] == r"C:\\Users\\p\\paper.pdf"


def test_placeholder_vals_tags_quoted():
    paper = _paper(tags=["sr", "reid"])
    vals = _placeholder_vals(paper, "cite.md")
    assert vals["tags"] == '"sr", "reid"'


def test_placeholder_vals_aliases_is_title():
    paper = _paper(title='Super "SR"')
    vals = _placeholder_vals(paper, "cite.md")
    assert vals["aliases"] == '"Super \\"SR\\""'

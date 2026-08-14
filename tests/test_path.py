"""路径与转义安全测试：citekey、论文标题、图片目录与 YAML 转义。"""
from core.obsidian_writer import default_note_filename, safe_citekey, safe_note_title, note_stem
from core.note_generator import _yaml_escape, _placeholder_vals


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


def test_safe_citekey_windows_reserved_names():
    assert safe_citekey("CON") == "_CON"
    assert safe_citekey("NUL") == "_NUL"
    assert safe_citekey("COM1") == "_COM1"
    assert safe_citekey("LPT3") == "_LPT3"
    assert safe_citekey("CON.md") == "_CON.md"  # 保留设备名即使带扩展名也非法
    assert safe_citekey("con") == "_con"  # 大小写不敏感
    assert safe_citekey("paper") == "paper"  # 正常名不受影响


def test_safe_note_title_keeps_unicode_and_replaces_windows_invalid_chars():
    assert safe_note_title("用大模型赋能 VI-ReID") == "用大模型赋能 VI-ReID"
    assert safe_note_title("S3-CLIP: video SR / person-ReID") == "S3-CLIP - video SR - person-ReID"
    assert default_note_filename("Auto-Encoding Variational Bayes") == "Auto-Encoding Variational Bayes.md"


def test_safe_note_title_handles_reserved_and_long_names():
    assert safe_note_title("CON") == "_CON"
    assert len(safe_note_title("A" * 200)) == 140


def test_note_stem_unique_across_sanitize_collision():
    assert note_stem("A&B", "K1") == "A_B-K1"
    assert note_stem("A B", "K2") == "A_B-K2"
    assert note_stem("A/B", "K3") == "A_B-K3"
    # 三个不同 citekey 各自独立，互不覆盖
    assert len({note_stem("A&B", "K1"), note_stem("A B", "K2"), note_stem("A/B", "K3")}) == 3


def test_note_stem_same_key_same_result():
    assert note_stem("Wang&Li,2022", "K1") == "Wang_Li_2022-K1"
    assert note_stem("Wang&Li,2022", "K1") == note_stem("Wang&Li,2022", "K1")

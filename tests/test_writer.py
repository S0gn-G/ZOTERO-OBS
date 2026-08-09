"""ObsidianWriter 单元测试：safe_citekey / 笔记读写 / 改名定位 / 图表拷贝 / 状态扫描。"""
import os

from obsidian_writer import ObsidianWriter, safe_citekey, merge_handwritten


def test_safe_citekey_rejects_traversal():
    k = safe_citekey("../../../etc/passwd")
    assert "/" not in k and "\\" not in k and ".." not in k
    assert k == safe_citekey(k)  # 幂等


def test_safe_citekey_sanitizes():
    assert safe_citekey("abc") == "abc"
    assert safe_citekey("a b") == "a_b"
    assert safe_citekey("") == "note"
    assert safe_citekey("Wang&Li,2022") == "Wang_Li_2022"


def test_note_path_stays_inside_notes_dir(tmp_path):
    w = ObsidianWriter(str(tmp_path), "Notes")
    p = w.note_path("../escape")
    assert os.path.commonpath([str(tmp_path), p]) == str(tmp_path)
    assert p.endswith(".md")


def test_merge_handwritten_preserves_sections():
    old = "---\nzotero_key: \"K1\"\n---\n\n# T\n\n## 我的笔记\n\n我写的东西\n\n## 疑问\n\nQ1?\n"
    new = "---\nzotero_key: \"K1\"\n---\n\n# T\n\n{{llm}}\n\n## 我的笔记\n\n\n## 疑问\n"
    merged = merge_handwritten(old, new)
    assert "我写的东西" in merged
    assert "Q1?" in merged


def test_write_note_preserving_finds_renamed_note(tmp_path):
    w = ObsidianWriter(str(tmp_path), "Notes")
    os.makedirs(w.notes_dir, exist_ok=True)
    # 用户在 Obsidian 里改过名的旧笔记（规范路径不存在）
    renamed = os.path.join(w.notes_dir, "custom-name.md")
    with open(renamed, "w", encoding="utf-8") as f:
        f.write("---\nzotero_key: \"K1\"\n---\n\n# Old\n\n## 我的笔记\n\n手写内容\n\n## 疑问\n")
    new_content = "---\nzotero_key: \"K1\"\n---\n\n# New\n\n## 我的笔记\n\n\n## 疑问\n"
    written = w.write_note_preserving("cite2022", new_content, zotero_key="K1")
    assert written == renamed  # 写入用户实际路径，不产生第二份
    assert os.path.exists(renamed)
    assert not os.path.exists(os.path.join(w.notes_dir, "cite2022.md"))
    with open(renamed, encoding="utf-8") as f:
        assert "手写内容" in f.read()


def test_write_note_preserving_creates_target_when_no_old(tmp_path):
    w = ObsidianWriter(str(tmp_path), "Notes")
    written = w.write_note_preserving("cite2022", "---\nzotero_key: \"K1\"\n---\n\n# X\n", zotero_key="K1")
    assert written == os.path.join(w.notes_dir, "cite2022.md")


def test_import_images_reports_missing(tmp_path):
    w = ObsidianWriter(str(tmp_path), "Notes")
    figs = [{"name": "fig_1.png", "staging_path": "N:/not/exist.png"}]
    assert w.import_images("cite", figs) == ["fig_1.png"]


def test_import_images_copies(tmp_path):
    w = ObsidianWriter(str(tmp_path), "Notes")
    src = tmp_path / "fig_1.png"
    src.write_bytes(b"PNGDATA")
    figs = [{"name": "fig_1.png", "staging_path": str(src)}]
    assert w.import_images("cite", figs) == []
    assert (tmp_path / "Notes" / "images" / "cite" / "fig_1.png").exists()


def test_scan_states_four_states(tmp_path):
    w = ObsidianWriter(str(tmp_path), "Notes")
    os.makedirs(w.notes_dir, exist_ok=True)

    def write(name, content):
        with open(os.path.join(w.notes_dir, name), "w", encoding="utf-8") as f:
            f.write(content)

    write("ok.md", "---\nzotero_key: \"OK1\"\n---\n\n# A\n\n正文\n")
    write("insuff.md", "---\nzotero_key: \"IS1\"\nevidence: insufficient\n---\n\n# B\n")
    write("abs.md", "---\nzotero_key: \"AB1\"\nevidence: abstract_only\n---\n\n# C\n")
    write("ph.md", "---\nzotero_key: \"PH1\"\n---\n\n# D\n\n待补充 待补充\n")
    states = {k: s for k, s, _m in w.scan_states()}
    assert states == {"OK1": "ok", "IS1": "insufficient", "AB1": "abstract_only", "PH1": "placeholder"}


def test_scan_states_ignores_placeholder_in_handwritten(tmp_path):
    w = ObsidianWriter(str(tmp_path), "Notes")
    os.makedirs(w.notes_dir, exist_ok=True)
    # TODO 只出现在「我的笔记」区（用户手写），不应误判为需修复
    content = "---\nzotero_key: \"K1\"\n---\n\n# A\n\n## 我的笔记\n\nTODO 待补充 占位符\n"
    with open(os.path.join(w.notes_dir, "note.md"), "w", encoding="utf-8") as f:
        f.write(content)
    states = {k: s for k, s, _m in w.scan_states()}
    assert states["K1"] == "ok"


def test_scan_states_placeholder_in_llm_body(tmp_path):
    w = ObsidianWriter(str(tmp_path), "Notes")
    os.makedirs(w.notes_dir, exist_ok=True)
    # 正文（LLM 区）含占位符 → 需修复
    content = "---\nzotero_key: \"K1\"\n---\n\n# A\n\n待补充 待补充\n\n## 我的笔记\n"
    with open(os.path.join(w.notes_dir, "note.md"), "w", encoding="utf-8") as f:
        f.write(content)
    states = {k: s for k, s, _m in w.scan_states()}
    assert states["K1"] == "placeholder"

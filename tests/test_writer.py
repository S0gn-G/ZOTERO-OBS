"""ObsidianWriter 单元测试：safe_citekey / 笔记读写 / 改名定位 / 归属冲突 / 整体事务 / 图表拷贝 / 状态扫描。"""
import os

import pytest

from obsidian_writer import ObsidianWriter, NotePathConflict, safe_citekey, merge_handwritten


def _fig(name, src):
    return {"name": name, "staging_path": str(src)}


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
    w = ObsidianWriter(str(tmp_path / "Notes"))
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
    w = ObsidianWriter(str(tmp_path / "Notes"))
    os.makedirs(w.notes_dir, exist_ok=True)
    # 用户在 Obsidian 里改过名的旧笔记（规范路径不存在）
    renamed = os.path.join(w.notes_dir, "custom-name.md")
    with open(renamed, "w", encoding="utf-8") as f:
        f.write("---\nzotero_key: \"K1\"\n---\n\n# Old\n\n## 我的笔记\n\n手写内容\n\n## 疑问\n")
    new_content = "---\nzotero_key: \"K1\"\n---\n\n# New\n\n## 我的笔记\n\n\n## 疑问\n"
    written = w.write_note_preserving("cite2022", new_content, zotero_key="K1")
    assert written == renamed  # 写入用户实际路径，不产生第二份
    assert os.path.exists(renamed)
    assert not os.path.exists(os.path.join(w.notes_dir, "cite2022-K1.md"))
    with open(renamed, encoding="utf-8") as f:
        assert "手写内容" in f.read()


def test_write_note_preserving_creates_target_when_no_old(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    written = w.write_note_preserving("cite2022", "---\nzotero_key: \"K1\"\n---\n\n# X\n", zotero_key="K1")
    assert written == os.path.join(w.notes_dir, "cite2022-K1.md")


def test_write_note_preserving_no_zotero_key_uses_safe_citekey(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    written = w.write_note_preserving("Wang&Li,2022", "---\nzotero_key: \"K1\"\n---\n\n# X\n")
    assert written == os.path.join(w.notes_dir, "Wang_Li_2022.md")


def test_colliding_citekeys_write_independent_files(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    k1 = "---\nzotero_key: \"K1\"\n---\n\n# P1\n\n## 我的笔记\n\nK1_PRIVATE\n"
    k2 = "---\nzotero_key: \"K2\"\n---\n\n# P2\n\n## 我的笔记\n\nK2_PRIVATE\n"
    w.write_note_preserving("A&B", k1, zotero_key="K1")
    w.write_note_preserving("A B", k2, zotero_key="K2")
    p1 = os.path.join(w.notes_dir, "A_B-K1.md")
    p2 = os.path.join(w.notes_dir, "A_B-K2.md")
    assert os.path.exists(p1) and os.path.exists(p2)
    with open(p1, encoding="utf-8") as f:
        c1 = f.read()
    with open(p2, encoding="utf-8") as f:
        c2 = f.read()
    # K2 不覆盖 K1，且不继承 K1 的手写区
    assert "K1_PRIVATE" in c1 and "K2_PRIVATE" not in c1
    assert "K2_PRIVATE" in c2 and "K1_PRIVATE" not in c2


def test_scan_states_four_states(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
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
    w = ObsidianWriter(str(tmp_path / "Notes"))
    os.makedirs(w.notes_dir, exist_ok=True)
    # TODO 只出现在「我的笔记」区（用户手写），不应误判为需修复
    content = "---\nzotero_key: \"K1\"\n---\n\n# A\n\n## 我的笔记\n\nTODO 待补充 占位符\n"
    with open(os.path.join(w.notes_dir, "note.md"), "w", encoding="utf-8") as f:
        f.write(content)
    states = {k: s for k, s, _m in w.scan_states()}
    assert states["K1"] == "ok"


def test_scan_states_placeholder_in_llm_body(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    os.makedirs(w.notes_dir, exist_ok=True)
    # 正文（LLM 区）含占位符 → 需修复
    content = "---\nzotero_key: \"K1\"\n---\n\n# A\n\n待补充 待补充\n\n## 我的笔记\n"
    with open(os.path.join(w.notes_dir, "note.md"), "w", encoding="utf-8") as f:
        f.write(content)
    states = {k: s for k, s, _m in w.scan_states()}
    assert states["K1"] == "placeholder"


# ---------- NotePathConflict：归属冲突 fail-closed ----------

def test_owner_mismatch_raises_conflict(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    target = tmp_path / "Notes" / "A_B-K1.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\nzotero_key: \"OTHER\"\n---\n\n# Other\n", encoding="utf-8")
    with pytest.raises(NotePathConflict):
        w.write_note_preserving("A B", "---\nzotero_key: \"K1\"\n---\n\n# New\n", zotero_key="K1")
    assert target.read_text(encoding="utf-8") == "---\nzotero_key: \"OTHER\"\n---\n\n# Other\n"


def test_no_frontmatter_raises_conflict(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    target = tmp_path / "Notes" / "A_B-K1.md"
    target.parent.mkdir(parents=True)
    target.write_text("# 人工笔记，无 frontmatter\n", encoding="utf-8")
    with pytest.raises(NotePathConflict):
        w.write_note_preserving("A B", "---\nzotero_key: \"K1\"\n---\n\n# New\n", zotero_key="K1")
    assert target.read_text(encoding="utf-8") == "# 人工笔记，无 frontmatter\n"


def test_owner_mismatch_but_renamed_exists_writes_renamed(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    os.makedirs(w.notes_dir, exist_ok=True)
    renamed = os.path.join(w.notes_dir, "custom-name.md")
    with open(renamed, "w", encoding="utf-8") as f:
        f.write("---\nzotero_key: \"K1\"\n---\n\n# Old\n")
    target = tmp_path / "Notes" / "A_B-K1.md"
    target.write_text("---\nzotero_key: \"OTHER\"\n---\n\n# Other\n", encoding="utf-8")
    written = w.write_note_preserving("A B", "---\nzotero_key: \"K1\"\n---\n\n# New\n", zotero_key="K1")
    assert written == renamed  # 写改名旧笔记，不碰他人占用文件
    assert target.read_text(encoding="utf-8") == "---\nzotero_key: \"OTHER\"\n---\n\n# Other\n"


def test_owner_match_preserves_handwritten(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    target = tmp_path / "Notes" / "A_B-K1.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\nzotero_key: \"K1\"\n---\n\n# Old\n\n## 我的笔记\n\n手写内容\n\n## 疑问\n", encoding="utf-8")
    new = "---\nzotero_key: \"K1\"\n---\n\n# New\n\n## 我的笔记\n\n\n## 疑问\n"
    w.write_note_preserving("A B", new, zotero_key="K1")
    assert "手写内容" in target.read_text(encoding="utf-8")


def test_note_file_synced_to_renamed_basename(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    os.makedirs(w.notes_dir, exist_ok=True)
    renamed = os.path.join(w.notes_dir, "custom-name.md")
    with open(renamed, "w", encoding="utf-8") as f:
        f.write("---\nzotero_key: \"K1\"\nnote_file: \"old.md\"\n---\n\n# Old\n")
    new_content = "---\nzotero_key: \"K1\"\nnote_file: \"cite2022-K1.md\"\n---\n\n# New\n"
    written = w.write_note_preserving("cite2022", new_content, zotero_key="K1")
    assert written == renamed
    with open(renamed, encoding="utf-8") as f:
        out = f.read()
    assert 'note_file: "custom-name.md"' in out
    assert 'note_file: "cite2022-K1.md"' not in out


# ---------- commit_generation：整体事务 ----------

def test_commit_generation_success_commits_both(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    src = tmp_path / "fig_1.png"
    src.write_bytes(b"NEW")
    figs = [_fig("fig_1.png", src)]
    assert w.commit_generation("cite", "---\nzotero_key: \"K1\"\n---\n\n# New\n", figs, zotero_key="K1") == []
    assert (tmp_path / "Notes" / "cite-K1.md").exists()
    assert (tmp_path / "Notes" / "images" / "cite-K1" / "fig_1.png").read_bytes() == b"NEW"
    assert not (tmp_path / "Notes" / "images" / "cite-K1.tmp").exists()
    assert not (tmp_path / "Notes" / "images" / "cite-K1.old").exists()


def test_commit_generation_no_figures_writes_note_only(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    assert w.commit_generation("cite", "---\nzotero_key: \"K1\"\n---\n\n# New\n", [], zotero_key="K1") == []
    assert (tmp_path / "Notes" / "cite-K1.md").exists()
    assert not (tmp_path / "Notes" / "images").exists()


def test_commit_generation_missing_fig_no_commit(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    figs = [_fig("fig_1.png", str(tmp_path / "missing.png"))]
    assert w.commit_generation("cite", "---\nzotero_key: \"K1\"\n---\n\n# New\n", figs, zotero_key="K1") == ["fig_1.png"]
    assert not (tmp_path / "Notes" / "cite-K1.md").exists()
    assert not (tmp_path / "Notes" / "images" / "cite-K1").exists()


def test_commit_generation_owner_conflict_raises(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    md = tmp_path / "Notes" / "cite-K1.md"
    md.parent.mkdir(parents=True)
    md.write_text("---\nzotero_key: \"OTHER\"\n---\n\n# Other\n", encoding="utf-8")
    src = tmp_path / "fig_1.png"
    src.write_bytes(b"NEW")
    with pytest.raises(NotePathConflict):
        w.commit_generation("cite", "---\nzotero_key: \"K1\"\n---\n\n# New\n", [_fig("fig_1.png", src)], zotero_key="K1")
    assert md.read_text(encoding="utf-8") == "---\nzotero_key: \"OTHER\"\n---\n\n# Other\n"
    assert not (tmp_path / "Notes" / "images" / "cite-K1.tmp").exists()


def test_commit_generation_markdown_write_failure_rolls_back(tmp_path, monkeypatch):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    dest = tmp_path / "Notes" / "images" / "cite-K1"
    dest.mkdir(parents=True)
    (dest / "fig_1.png").write_bytes(b"OLD")
    md = tmp_path / "Notes" / "cite-K1.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("---\nzotero_key: \"K1\"\n---\n\n# Old\n\n## 我的笔记\n\n手写内容\n\n## 疑问\n", encoding="utf-8")
    orig = ObsidianWriter._atomic_write  # staticmethod，类访问即底层函数
    calls = {"n": 0}

    def flaky(path, content):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return orig(path, content)

    monkeypatch.setattr(ObsidianWriter, "_atomic_write", staticmethod(flaky))
    src = tmp_path / "fig_1.png"
    src.write_bytes(b"NEW")
    with pytest.raises(OSError):
        w.commit_generation("cite", "---\nzotero_key: \"K1\"\n---\n\n# New\n\n新正文\n", [_fig("fig_1.png", src)], zotero_key="K1")
    content = md.read_text(encoding="utf-8")
    assert "手写内容" in content  # 回滚到旧笔记（含手写），不是「旧笔记 + 新图」
    assert "新正文" not in content
    assert (dest / "fig_1.png").read_bytes() == b"OLD"
    assert not (tmp_path / "Notes" / "images" / "cite-K1.tmp").exists()


def test_commit_generation_image_swap_failure_rolls_back(tmp_path, monkeypatch):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    dest = tmp_path / "Notes" / "images" / "cite-K1"
    dest.mkdir(parents=True)
    (dest / "fig_1.png").write_bytes(b"OLD")
    md = tmp_path / "Notes" / "cite-K1.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("---\nzotero_key: \"K1\"\n---\n\n# Old\n\n## 我的笔记\n\n手写内容\n\n## 疑问\n", encoding="utf-8")

    def boom(dest_dir, staging):
        raise RuntimeError("swap failed")

    monkeypatch.setattr(ObsidianWriter, "_swap_images", staticmethod(boom))
    src = tmp_path / "fig_1.png"
    src.write_bytes(b"NEW")
    with pytest.raises(RuntimeError):
        w.commit_generation("cite", "---\nzotero_key: \"K1\"\n---\n\n# New\n\n新正文\n", [_fig("fig_1.png", src)], zotero_key="K1")
    content = md.read_text(encoding="utf-8")
    assert "手写内容" in content  # markdown 回滚旧内容
    assert "新正文" not in content
    assert (dest / "fig_1.png").read_bytes() == b"OLD"  # 图片未切换
    assert not (tmp_path / "Notes" / "images" / "cite-K1.tmp").exists()


def test_write_note_preserving_finds_note_moved_to_subfolder(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    moved = tmp_path / "Notes" / "主题" / "custom-name.md"
    moved.parent.mkdir(parents=True)
    moved.write_text(
        '---\nzotero_key: "K1"\n---\n\n# Old\n\n## 我的笔记\n\n保留我写的内容\n\n## 疑问\n',
        encoding="utf-8",
    )

    written = w.write_note_preserving(
        "cite", '---\nzotero_key: "K1"\nnote_file: "cite-K1.md"\n---\n\n# New\n\n## 我的笔记\n\n## 疑问\n',
        zotero_key="K1",
    )

    assert written == str(moved)
    assert "保留我写的内容" in moved.read_text(encoding="utf-8")
    assert not (tmp_path / "Notes" / "cite-K1.md").exists()


def test_scan_states_rejects_duplicate_zotero_keys(tmp_path):
    w = ObsidianWriter(str(tmp_path / "Notes"))
    for folder, name in (("A", "one.md"), ("B", "two.md")):
        path = tmp_path / "Notes" / folder / name
        path.parent.mkdir(parents=True)
        path.write_text('---\nzotero_key: "K1"\n---\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="重复 Zotero 笔记"):
        w.scan_states()

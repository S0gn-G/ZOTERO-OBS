"""Obsidian vault 写入：笔记文件读写 + 已生成笔记状态检测。"""
import os
import re
import shutil

FRONTMATTER_KEY_RE = re.compile(r'^zotero_key:\s*["\']?([A-Za-z0-9]+)["\']?\s*$', re.M)
EVIDENCE_INSUFFICIENT_RE = re.compile(r'^evidence:\s*insufficient\s*$', re.M)
# 修复轮偷懒产物：整篇「待补充」骨架（与 evidence: insufficient 不同，它其实没走 fail-closed）
PLACEHOLDER_HITS_RE = re.compile(r"待补充|占位符|\[?TODO|TBD")
PLACEHOLDER_MIN_HITS = 2

MY_NOTES_HEADING = "## 我的笔记"
QUESTIONS_HEADING = "## 疑问"


def _section_body(content: str, heading: str, until: str | None) -> str | None:
    """返回 content 中 heading 之后、until（可选）之前的内容（不含标题）。heading 不存在返回 None。"""
    i = content.find(heading)
    if i == -1:
        return None
    body = content[i + len(heading):]
    if until:
        j = body.find(until)
        if j != -1:
            body = body[:j]
    return body


def merge_handwritten(old: str, new: str) -> str:
    """覆盖生成时把旧笔记的「我的笔记」「疑问」手写区拼进新笔记对应分区。

    新笔记或旧笔记缺少这些分区时原样返回 new；旧手写区为空时保留新的空分区。
    """
    if MY_NOTES_HEADING not in new or MY_NOTES_HEADING not in old:
        return new
    old_my = _section_body(old, MY_NOTES_HEADING, QUESTIONS_HEADING)
    old_qa = _section_body(old, QUESTIONS_HEADING, None)
    if not (old_my or "").strip() and not (old_qa or "").strip():
        return new  # 旧笔记手写区本来就是空的，无需合并
    head = new.split(MY_NOTES_HEADING, 1)[0].rstrip()
    parts = [head, "", MY_NOTES_HEADING]
    if (old_my or "").strip():
        parts += ["", (old_my or "").strip()]
    parts += ["", QUESTIONS_HEADING]
    if (old_qa or "").strip():
        parts += ["", (old_qa or "").strip()]
    return "\n".join(parts) + "\n"


class ObsidianWriter:
    def __init__(self, vault_path: str, notes_folder: str):
        self.notes_dir = os.path.join(vault_path, notes_folder) if vault_path else ""

    def note_path(self, citation_key: str) -> str:
        return os.path.join(self.notes_dir, f"{citation_key}.md")

    def scan_states(self) -> list[tuple[str, str, float]]:
        """单次扫描笔记目录，返回 [(zotero_key, state, mtime)]。state ∈ ok/insufficient/placeholder。

        占位符检测只对 LLM 生成的正文区（「## 我的笔记」之前）计数，避免用户手写的
        「我的笔记/疑问」区出现 TODO 等词时误判为需修复。"""
        out: list[tuple[str, str, float]] = []
        if not os.path.isdir(self.notes_dir):
            return out
        for name in os.listdir(self.notes_dir):
            if not name.endswith(".md"):
                continue
            path = os.path.join(self.notes_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            m = FRONTMATTER_KEY_RE.search(content)
            if not m:
                continue
            llm_body = content.split(MY_NOTES_HEADING, 1)[0]
            if len(PLACEHOLDER_HITS_RE.findall(llm_body)) >= PLACEHOLDER_MIN_HITS:
                state = "placeholder"
            elif EVIDENCE_INSUFFICIENT_RE.search(content):
                state = "insufficient"
            else:
                state = "ok"
            out.append((m.group(1), state, mtime))
        return out

    def existing_note_keys(self) -> set[str]:
        """读取各笔记 frontmatter 中的 zotero_key，得到已生成笔记的 Zotero key 集合。
        这样笔记文件即使被改名也能识别。"""
        return {key for key, _flag, _mtime in self.scan_states()}

    def insufficient_note_keys(self) -> set[str]:
        """已生成但标记为「证据不足」的笔记 key 集合（需原文补充）。"""
        return {key for key, flag, _mtime in self.scan_states() if flag == "insufficient"}

    def placeholder_note_keys(self) -> set[str]:
        """已生成但正文含占位符（修复轮产物）的笔记 key 集合，需重新生成。"""
        return {key for key, flag, _mtime in self.scan_states() if flag == "placeholder"}

    def note_mtimes(self) -> dict[str, float]:
        """各笔记文件的最后修改时间。Obsidian 里编辑即更新，从未编辑过时即生成时间。"""
        return {key: mtime for key, _flag, mtime in self.scan_states()}

    def write_note(self, citation_key: str, content: str) -> str:
        os.makedirs(self.notes_dir, exist_ok=True)
        path = self.note_path(citation_key)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        return path

    def write_note_preserving(self, citation_key: str, content: str) -> str:
        """写笔记；目标已存在时先把旧笔记的「我的笔记/疑问」手写区拼进新内容再写，
        避免重新生成覆盖掉用户在 Obsidian 里手写的内容。"""
        path = self.note_path(citation_key)
        old = ""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = f.read()
            except OSError:
                old = ""
        return self.write_note(citation_key, merge_handwritten(old, content))

    def import_images(self, citation_key: str, figures: list[dict]) -> list[str]:
        """把暂存目录里的图表拷贝到 notes_dir/images/<citekey>/，返回写入的相对路径列表。
        笔记正文中引用格式：![caption](images/<citekey>/<name>)。"""
        if not figures:
            return []
        dest_dir = os.path.join(self.notes_dir, "images", citation_key)
        os.makedirs(dest_dir, exist_ok=True)
        written: list[str] = []
        for f in figures:
            src = f.get("staging_path")
            if not src or not os.path.exists(src):
                continue
            dst = os.path.join(dest_dir, f["name"])
            try:
                shutil.copy2(src, dst)
                written.append(f"images/{citation_key}/{f['name']}")
            except OSError:
                continue
        return written

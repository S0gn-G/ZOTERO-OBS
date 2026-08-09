"""Obsidian vault 写入：笔记文件读写 + 已生成笔记状态检测。"""
import os
import re
import shutil

FRONTMATTER_KEY_RE = re.compile(r'^zotero_key:\s*["\']?([A-Za-z0-9]+)["\']?\s*$', re.M)
EVIDENCE_INSUFFICIENT_RE = re.compile(r'^evidence:\s*insufficient\s*$', re.M)
EVIDENCE_ABSTRACT_RE = re.compile(r'^evidence:\s*abstract_only\s*$', re.M)
# 修复轮偷懒产物：整篇「待补充」骨架（与 evidence: insufficient 不同，它其实没走 fail-closed）
PLACEHOLDER_HITS_RE = re.compile(r"待补充|占位符|\[?TODO|TBD")
PLACEHOLDER_MIN_HITS = 2

MY_NOTES_HEADING = "## 我的笔记"
QUESTIONS_HEADING = "## 疑问"


def safe_citekey(key: str, fallback: str = "note") -> str:
    """把 Zotero/Better BibTeX 的 citekey 规范化为安全文件名片段。

    过滤路径分隔符、..、Windows 保留字符，保证产出的笔记文件名与图片
    目录名不越出 notes 目录、不含非法字符。同 key 结果确定，可全链路复用。
    """
    s = (key or "").strip()
    s = re.sub(r"[^A-Za-z0-9_.\-]", "_", s)
    s = re.sub(r"\.{2,}", "_", s)
    s = s.strip("._-") or fallback
    return s[:80]


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
        return os.path.join(self.notes_dir, f"{safe_citekey(citation_key)}.md")

    def scan_states(self) -> list[tuple[str, str, float]]:
        """单次扫描笔记目录，返回 [(zotero_key, state, mtime)]。

        state ∈ ok / insufficient / abstract_only / placeholder。
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
            elif EVIDENCE_ABSTRACT_RE.search(content):
                state = "abstract_only"
            else:
                state = "ok"
            out.append((m.group(1), state, mtime))
        return out

    def _find_note_by_key(self, zotero_key: str) -> str | None:
        """按 frontmatter 里的 zotero_key 找已有笔记文件（支持用户在 Obsidian 里改名）。"""
        if not os.path.isdir(self.notes_dir):
            return None
        for name in os.listdir(self.notes_dir):
            if not name.endswith(".md"):
                continue
            path = os.path.join(self.notes_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    head = f.read(2000)
            except OSError:
                continue
            m = FRONTMATTER_KEY_RE.search(head)
            if m and m.group(1) == zotero_key:
                return path
        return None

    def existing_note_keys(self) -> set[str]:
        """读取各笔记 frontmatter 中的 zotero_key，得到已生成笔记的 Zotero key 集合。
        这样笔记文件即使被改名也能识别。"""
        return {key for key, _flag, _mtime in self.scan_states()}

    def insufficient_note_keys(self) -> set[str]:
        """已生成但标记为「证据不足」的笔记 key 集合（需原文补充）。"""
        return {key for key, flag, _mtime in self.scan_states() if flag == "insufficient"}

    def abstract_note_keys(self) -> set[str]:
        """仅依据摘要生成（evidence: abstract_only）的笔记 key 集合，与读全正文的笔记区分。"""
        return {key for key, flag, _mtime in self.scan_states() if flag == "abstract_only"}

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

    def write_note_preserving(self, citation_key: str, content: str, zotero_key: str | None = None) -> str:
        """写笔记，保留旧笔记的「我的笔记/疑问」手写区。

        目标文件（<citekey>.md）存在则直接合并旧手写区；若用户在 Obsidian 里改过名
        （规范路径不存在），则按 frontmatter zotero_key 定位实际文件并写入该路径，
        避免产生第二份、也不丢手写内容。返回实际写入的路径。"""
        target = self.note_path(citation_key)
        old_path = target if os.path.exists(target) else None
        if old_path is None and zotero_key:
            old_path = self._find_note_by_key(zotero_key)
        old = ""
        if old_path:
            try:
                with open(old_path, "r", encoding="utf-8") as f:
                    old = f.read()
            except OSError:
                old = ""
        merged = merge_handwritten(old, content)
        if old_path:
            os.makedirs(os.path.dirname(old_path), exist_ok=True)
            with open(old_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(merged)
            return old_path
        return self.write_note(citation_key, merged)

    def import_images(self, citation_key: str, figures: list[dict]) -> list[str]:
        """把暂存目录里的图表拷贝到 notes_dir/images/<citekey>/。

        返回未成功写入的文件名列表（源缺失 / 复制失败）。正文引用必须全部落盘，
        调用方据此判定是否将本次生成判为失败，避免「笔记在而图不在」。"""
        if not figures:
            return []
        dest_dir = os.path.join(self.notes_dir, "images", safe_citekey(citation_key))
        os.makedirs(dest_dir, exist_ok=True)
        missing: list[str] = []
        for f in figures:
            src = f.get("staging_path")
            if not src or not os.path.exists(src):
                missing.append(f["name"])
                continue
            dst = os.path.join(dest_dir, f["name"])
            try:
                shutil.copy2(src, dst)
            except OSError:
                missing.append(f["name"])
        return missing

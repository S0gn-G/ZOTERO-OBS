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

# frontmatter 的 note_file 字段：写回时按实际文件名同步（用户改名后不残留假值）
NOTE_FILE_RE = re.compile(r"^note_file:\s*.*$", re.M)


# Windows 保留设备名：即使带扩展名也非法（CON.md / NUL.txt / COM1.pdf…）
_WINDOWS_RESERVED = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def safe_citekey(key: str, fallback: str = "note") -> str:
    """把 Zotero/Better BibTeX 的 citekey 规范化为安全文件名片段。

    过滤路径分隔符、..、Windows 保留字符，保证产出的笔记文件名与图片
    目录名不越出 notes 目录、不含非法字符。同 key 结果确定，可全链路复用。
    """
    s = (key or "").strip()
    s = re.sub(r"[^A-Za-z0-9_.\-]", "_", s)
    s = re.sub(r"\.{2,}", "_", s)
    s = s.strip("._-") or fallback
    if s.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        s = "_" + s
    return s[:80]


def note_stem(citation_key: str, zotero_key: str) -> str:
    """唯一图片目录片段：<safe citekey>-<zotero key>。

    zotero key 全局稳定唯一，即使不同 citekey sanitize 后碰撞也不会互相覆盖。"""
    return f"{safe_citekey(citation_key)}-{zotero_key}"


def safe_note_title(title: str, fallback: str = "Untitled") -> str:
    """把论文标题转换为可读且可在 Windows/Obsidian 中使用的文件名。"""
    s = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', " - ", (title or "").strip())
    s = re.sub(r"\s+", " ", s).strip(" .")
    if s.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        s = "_" + s
    return (s[:140].rstrip(" .") or fallback)


def default_note_filename(title: str) -> str:
    return safe_note_title(title) + ".md"


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


def _sync_note_file(content: str, actual_basename: str) -> str:
    """把 frontmatter 里的 note_file 改为实际写入的文件名。

    生成时 note_file 是 canonical stem.md；若用户改过名、写入路径不同，这里修正，避免
    元数据与实际文件名不一致。与实际名一致时替换结果相同（无副作用）。"""
    if NOTE_FILE_RE.search(content):
        return NOTE_FILE_RE.sub(f'note_file: "{actual_basename}"', content, count=1)
    return content


class NotePathConflict(Exception):
    """目标笔记文件被其他文献（或无 frontmatter 的人工文件）占用，拒绝覆盖。"""

    def __init__(self, path: str, citation_key: str):
        super().__init__(
            f"笔记文件 {path} 被其他文献占用，拒绝覆盖（citekey {citation_key}）。"
            "请检查或删除该文件后重试。"
        )
        self.path = path
        self.citation_key = citation_key


class ObsidianWriter:
    def __init__(self, notes_path: str):
        self.notes_dir = notes_path

    def _stem(self, citation_key: str, zotero_key: str | None = None) -> str:
        if zotero_key:
            return note_stem(citation_key, zotero_key)
        return safe_citekey(citation_key)

    def note_path(self, citation_key: str, zotero_key: str | None = None,
                  note_title: str | None = None) -> str:
        stem = safe_note_title(note_title) if note_title else self._stem(citation_key, zotero_key)
        return os.path.join(self.notes_dir, f"{stem}.md")

    def scan_states(self) -> list[tuple[str, str, float]]:
        """单次扫描笔记目录，返回 [(zotero_key, state, mtime)]。

        state ∈ ok / insufficient / abstract_only / placeholder。
        占位符检测只对 LLM 生成的正文区（「## 我的笔记」之前）计数，避免用户手写的
        「我的笔记/疑问」区出现 TODO 等词时误判为需修复。"""
        out: list[tuple[str, str, float]] = []
        if not os.path.isdir(self.notes_dir):
            return out
        seen: dict[str, str] = {}
        for root, dirs, names in os.walk(self.notes_dir):
            dirs[:] = [d for d in dirs if d != "images"]
            for name in names:
                if not name.endswith(".md"):
                    continue
                path = os.path.join(root, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                m = FRONTMATTER_KEY_RE.search(content)
                if not m:
                    continue
                key = m.group(1)
                if key in seen:
                    raise RuntimeError(f"发现重复 Zotero 笔记：{seen[key]} 和 {path}")
                seen[key] = path
                llm_body = content.split(MY_NOTES_HEADING, 1)[0]
                if len(PLACEHOLDER_HITS_RE.findall(llm_body)) >= PLACEHOLDER_MIN_HITS:
                    state = "placeholder"
                elif EVIDENCE_INSUFFICIENT_RE.search(content):
                    state = "insufficient"
                elif EVIDENCE_ABSTRACT_RE.search(content):
                    state = "abstract_only"
                else:
                    state = "ok"
                out.append((key, state, mtime))
        return out

    def _find_note_by_key(self, zotero_key: str) -> str | None:
        """按 frontmatter 里的 zotero_key 找已有笔记文件（支持用户在 Obsidian 里改名）。"""
        if not os.path.isdir(self.notes_dir):
            return None
        found = None
        for root, dirs, names in os.walk(self.notes_dir):
            dirs[:] = [d for d in dirs if d != "images"]
            for name in names:
                if not name.endswith(".md"):
                    continue
                path = os.path.join(root, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        head = f.read(2000)
                except OSError:
                    continue
                m = FRONTMATTER_KEY_RE.search(head)
                if m and m.group(1) == zotero_key:
                    if found:
                        raise RuntimeError(f"发现重复 Zotero 笔记：{found} 和 {path}")
                    found = path
        return found

    @staticmethod
    def _atomic_write(path: str, content: str) -> None:
        """先写临时文件再 os.replace，避免写一半崩溃留下截断文件。写失败清理 tmp。"""
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        os.replace(tmp, path)

    @staticmethod
    def _zotero_key_of(path: str) -> str | None:
        """读取笔记 frontmatter 的 zotero_key；文件缺失/无该字段返回 None。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                m = FRONTMATTER_KEY_RE.search(f.read(2000))
                return m.group(1) if m else None
        except OSError:
            return None

    def _resolve_write_path(self, citation_key: str, zotero_key: str | None = None,
                            note_title: str | None = None) -> str:
        """确定写入路径，归属校验 fail-closed。

        优先按 zotero_key 定位已有笔记，因而允许用户自由改名。新笔记默认以论文标题命名；
        同名文件被其他内容占用时追加 Zotero key，绝不覆盖。"""
        existing = self._find_note_by_key(zotero_key) if zotero_key else None
        if existing:
            return existing

        target = self.note_path(citation_key, zotero_key, note_title)
        if not os.path.exists(target):
            return target

        if note_title and zotero_key:
            collision = os.path.join(
                self.notes_dir,
                f"{safe_note_title(note_title)} - {safe_citekey(zotero_key)}.md",
            )
            if not os.path.exists(collision):
                return collision
            if self._zotero_key_of(collision) == zotero_key:
                return collision
            raise NotePathConflict(collision, citation_key)

        if os.path.exists(target):
            owner = self._zotero_key_of(target)
            if owner == (zotero_key or citation_key):
                return target
            raise NotePathConflict(target, citation_key)

    def write_note_preserving(self, citation_key: str, content: str,
                              zotero_key: str | None = None,
                              note_title: str | None = None) -> str:
        """写笔记，保留手写区，并把 note_file 同步为用户当前使用的实际文件名。

        目标文件被其他文献/无 frontmatter 文件占用且无改名旧笔记时抛 NotePathConflict。"""
        path = self._resolve_write_path(citation_key, zotero_key, note_title)
        old = ""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = f.read()
            except OSError:
                old = ""
        merged = merge_handwritten(old, _sync_note_file(content, os.path.basename(path)))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._atomic_write(path, merged)
        return path

    def _stage_images(self, dest_dir: str, figures: list[dict]) -> list[str]:
        """把暂存图表全部拷入 <dest_dir>.tmp；任一缺失/失败清理 tmp 返回 missing（正式目录不动）。"""
        staging = dest_dir + ".tmp"
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)  # 清上次崩溃残留
        os.makedirs(staging, exist_ok=True)
        missing: list[str] = []
        for f in figures:
            src = f.get("staging_path")
            name = f["name"]
            if not src or not os.path.exists(src):
                missing.append(name)
                continue
            try:
                shutil.copy2(src, os.path.join(staging, name))
            except OSError:
                missing.append(name)
        if missing:
            shutil.rmtree(staging, ignore_errors=True)
        return missing

    @staticmethod
    def _swap_images(dest_dir: str, staging: str) -> None:
        """一次性切换图片目录：旧目录 → .old，tmp → 正式；切换失败回滚 .old，成功后删 .old。"""
        backup = dest_dir + ".old"
        if os.path.isdir(backup):
            shutil.rmtree(backup, ignore_errors=True)
        if os.path.isdir(dest_dir):
            os.replace(dest_dir, backup)
        try:
            os.replace(staging, dest_dir)
        except Exception:
            if os.path.isdir(backup) and not os.path.isdir(dest_dir):
                os.replace(backup, dest_dir)
            raise
        if os.path.isdir(backup):
            shutil.rmtree(backup, ignore_errors=True)

    def commit_generation(self, citation_key: str, content: str, figures: list[dict],
                          zotero_key: str | None = None,
                          note_title: str | None = None) -> list[str]:
        """Markdown 与图片作为整体事务交付：失败回滚到旧态，绝不产生「旧笔记 + 新图」。

        1. 无图 → 仅写笔记（保留手写区），返回 []。
        2. 全图先拷入 images/<stem>.tmp/；任一缺失 → 清理 tmp，返回缺失列表（什么都不提交）。
        3. 归属校验定位目标（占用冲突抛 NotePathConflict）→ 原子写 Markdown（同步 note_file）。
        4. 一次性切换图片目录（旧 → .old，tmp → 正式）。
        任一步失败：恢复旧 Markdown（原不存在则删除新文件）、恢复旧图片目录、清理 tmp 后 raise。
        返回缺失文件名列表（空 = 已提交）。"""
        if not figures:
            self.write_note_preserving(citation_key, content, zotero_key, note_title)
            return []
        dest_dir = os.path.join(self.notes_dir, "images", self._stem(citation_key, zotero_key))
        missing = self._stage_images(dest_dir, figures)
        if missing:
            return missing

        path = None
        existed = False
        old = ""
        try:
            path = self._resolve_write_path(citation_key, zotero_key, note_title)
            if os.path.exists(path):
                existed = True
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        old = f.read()
                except OSError:
                    old = ""
            merged = merge_handwritten(old, _sync_note_file(content, os.path.basename(path)))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self._atomic_write(path, merged)  # Markdown 先落盘，再切图片
            self._swap_images(dest_dir, dest_dir + ".tmp")
        except Exception:
            # 回滚：Markdown 恢复旧内容（原不存在则删新文件），图片恢复旧目录
            if path is not None and os.path.exists(path):
                if existed:
                    self._atomic_write(path, old)
                else:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            shutil.rmtree(dest_dir + ".tmp", ignore_errors=True)
            raise
        return []

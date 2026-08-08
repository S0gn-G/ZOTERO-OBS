"""只读测试：拉取 Zotero 文献 + 检测 vault 中已生成的笔记状态（不写文件）。"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import load_config
from obsidian_writer import ObsidianWriter
from zotero_client import ZoteroClient, ZoteroError


def main():
    cfg = load_config()
    print("config: vault =", cfg["vault_path"], "| notes_folder =", cfg["notes_folder"])
    print()

    client = ZoteroClient(cfg["zotero_base"])
    try:
        papers = client.fetch_papers()
    except ZoteroError as e:
        print("ERROR:", e)
        sys.exit(1)

    print(f"共 {len(papers)} 篇文献\n")

    writer = ObsidianWriter(cfg["vault_path"], cfg["notes_folder"])
    done = writer.existing_note_keys()
    print(f"已生成笔记的 zotero_key 数: {len(done)}\n")

    for p in papers:
        cite = p["citationKey"] or ZoteroClient.fallback_citation_key(p)
        status = "✔ 已生成" if p["key"] in done else "— 未生成"
        pdf = "PDF" if p.get("pdf_path") else "无PDF"
        print(f"[{status}] {p['year']} | {p['title'][:50]}")
        print(f"    key={p['key']} cite={cite} | {p['first_author']} | {pdf}")


if __name__ == "__main__":
    main()

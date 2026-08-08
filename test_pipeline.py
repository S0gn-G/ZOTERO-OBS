"""端到端测试：拉取 Zotero 文献 → 选一篇含 PDF → 跑多阶段管道。
只验证不写 vault（除了图表暂存在系统临时目录）。"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import load_config
from zotero_client import ZoteroClient, ZoteroError
from note_generator import generate_note, _extract_figures


def main():
    cfg = load_config()
    client = ZoteroClient(cfg["zotero_base"])
    try:
        papers = client.fetch_papers()
    except ZoteroError as e:
        print("ERROR:", e)
        sys.exit(1)

    papers = [p for p in papers if p.get("pdf_path")]
    print(f"共 {len(papers)} 篇含 PDF 文献\n")

    # 选一篇（优先最近年份）
    papers.sort(key=lambda p: (p.get("year") or "0"), reverse=True)
    p = papers[0]
    cite = p["citationKey"] or ZoteroClient.fallback_citation_key(p)
    print(f"测试论文：{p['title'][:60]}")
    print(f"  cite={cite} | pdf={p['pdf_path']}\n")

    # 先单独测图表提取
    figs = _extract_figures(p["pdf_path"], cite)
    print(f"图表提取：{len(figs)} 张")
    for f in figs[:5]:
        print(f"  {f['name']} page={f['page']} caption={f['caption'][:40]!r}")

    # 完整管道
    result = generate_note(p, cfg, note_key=cite)
    print(f"\n生成状态：{result['status']}")
    content = result["content"]
    print(f"笔记长度：{len(content)} 字符")
    print(f"图表数：{len(result['figures'])}")
    print("是否占位符：", "待补充" in content or "（待补充）" in content)

    # 验证必需章节
    for sec in ("## 核心信息", "## 原文摘要翻译", "## 创新点", "## 一句话总结", "## 方法主线"):
        print(f"  {'✔' if sec in content else '✘ 缺'} {sec}")

    # 预览开头
    print("\n--- 笔记开头 1500 字符 ---")
    print(content[:1500])


if __name__ == "__main__":
    main()

"""笔记生成：多阶段深度精读管道。

参考 DeepPaperNote 的设计，为批量化 GUI 工具做的务实移植：
  1. 正文提取   —— pdfplumber 抽取 PDF 全文（截断到上限）
  2. 图表提取   —— PyMuPDF 抽取 PDF 内嵌图片，保存到临时暂存目录
  3. 证据包     —— 元数据 + 摘要 + 正文 + 图表清单 汇总为 bundle
  4. 写作计划   —— LLM 第一轮：输出结构化 JSON 计划（论文类型/要点/图表取舍/机制流程）
  5. 正文写作   —— LLM 第二轮：按 DeepPaperNote 章节骨架写整篇笔记
  6. 校验与修复 —— 结构 lint（必需章节/图表引用），不通过则 LLM 修复一轮
  7. 交付       —— 返回 content + 需拷贝的图表；由调用方写入 Obsidian

fail-closed：无 PDF 正文且无摘要时不做 LLM 硬编，生成骨架笔记并标记
`evidence: insufficient`，GUI 据此显示「需原文」。
"""
import json
import os
import re
import shutil
import tempfile

from openai import OpenAI

from config import BASE_DIR
from obsidian_writer import note_stem, safe_citekey

PDF_MAX_CHARS = 30000  # 深度笔记需要更多证据

# ---------------- 正文提取（Stage 1） ----------------


def _extract_pdf_text(pdf_path: str, max_chars: int = PDF_MAX_CHARS) -> str:
    """提取 PDF 正文（截断到 max_chars）。无 PDF / 读取失败 / 扫描版时返回空串。"""
    if not pdf_path or not os.path.exists(pdf_path):
        return ""
    try:
        import pdfplumber

        parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
                if sum(len(p) for p in parts) >= max_chars:
                    break
        return "\n".join(parts)[:max_chars]
    except Exception:
        return ""


# ---------------- 图表提取（Stage 2） ----------------


# 图注识别：Figure/Fig. 与 Table/Tab.，捕获类型与编号
CAPTION_RE = re.compile(r"(?im)^\s*(?:(Figure|Fig\.?)|(Table|Tab\.?))\s+(\d+)[.:]\s*(.*)$")
MIN_FIG_H = 60          # 渲染区域最小高度（像素，过滤装饰性图注）
FIG_SCALE = 2.0         # 渲染缩放
FIG_CAPTION_MAX_GAP = 60  # 图/表与其 caption 之间允许的最大空隙（点）
FIG_MAX_HEIGHT = 360      # fig 从 caption 向上最多找多高
MARGIN_TOP = 55.0         # 页边距上界
MARGIN_BOTTOM = 40.0      # 页边距下界
MARGIN_LEFT = 45.0        # 页边距左界


def _page_captions(doc, page_no: int) -> list[dict]:
    """返回指定页上所有图注：[{kind, num, y0, y1, x0, x1, text}]。kind ∈ fig/table。"""
    page = doc[page_no - 1]
    caps: list[dict] = []
    for block in page.get_text("dict")["blocks"]:
        if "lines" not in block:
            continue
        # 多行图注：拼接整个 block 的文本，仍以 block 首行做匹配判定
        text = " ".join(
            "".join(s["text"] for s in ln["spans"]) for ln in block["lines"]
        ).strip()
        m = CAPTION_RE.match(text)
        if not m:
            continue
        kind = "table" if m.group(2) else "fig"
        x0, y0, x1, y1 = block["bbox"]
        caps.append({"kind": kind, "num": int(m.group(3)), "y0": y0, "y1": y1,
                     "x0": x0, "x1": x1, "text": text})
    caps.sort(key=lambda c: c["y0"])
    return caps


def _image_rects(page) -> list:
    """页面内嵌图片的矩形列表（用于图注附近纵向探图）。渲染异常时返回空。"""
    try:
        rects: list = []
        for img in page.get_images(full=True):
            rects.extend(page.get_image_rects(img[0]))
        return rects
    except Exception:
        return []


def _clip_region(cap, next_cap, image_rects, prev_bottom, margin_top, page_w, page_h):
    """按图注类型计算裁剪区 (x0, y0, x1, y1)。

    fig（图注在图下方）：默认裁 caption 上方，可用内嵌图片 bbox 在 gap 内上探；
    table（图注在表格上方）：默认裁 caption 下方，向下探到 next caption 或页底。
    返回 y 区间为 [y0, y1)；过矮区间由调用方跳过。"""
    x0 = MARGIN_LEFT
    x1 = max(page_w - MARGIN_LEFT, MARGIN_LEFT + 100)
    if cap["kind"] == "table":
        y0 = max(margin_top, prev_bottom, cap["y1"] + 4)
        y1 = (next_cap["y0"] - 4) if next_cap else (page_h - MARGIN_BOTTOM)
        for r in image_rects:
            if 0 <= r.y0 - cap["y1"] <= FIG_CAPTION_MAX_GAP and r.y1 > cap["y1"] \
                    and r.x1 > x0 and r.x0 < x1:
                y1 = max(y1, r.y1)
    else:  # fig
        y1 = cap["y0"] - 4
        y0 = max(margin_top, prev_bottom, y1 - FIG_MAX_HEIGHT)
        for r in image_rects:
            if 0 <= cap["y0"] - r.y1 <= FIG_CAPTION_MAX_GAP and r.y0 < cap["y0"] \
                    and r.x1 > x0 and r.x0 < x1:
                y0 = min(y0, r.y0)
    return x0, y0, x1, y1


def _extract_figures(pdf_path: str, seed: str) -> list[dict]:
    """按图注定位并渲染 PDF 中的图表区域（能抓住矢量 pipeline/架构图）。

    Figure：图注在下方，裁图注上方区域，可用内嵌图片 bbox 上探（允许合理 gap）；
    Table：图注在表格上方，裁图注下方直到下一个图注或页底。
    横向放宽到正文整页宽度（图注通常比图本身窄，不能按图注宽度裁剪）。
    暂存到临时目录。返回 [{name, page, caption, staging_path}]。无图注的页不提取。
    """
    if not pdf_path or not os.path.exists(pdf_path):
        return []
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []
    staging = tempfile.mkdtemp(prefix=f"zotnotes_fig_{seed}_")
    figs: list[dict] = []
    doc = None
    try:
        doc = fitz.open(pdf_path)
        for pno in range(1, doc.page_count + 1):
            caps = _page_captions(doc, pno)
            if not caps:
                continue
            page = doc[pno - 1]
            page_w = page.rect.width
            page_h = page.rect.height
            image_rects = _image_rects(page)
            prev_bottom = MARGIN_TOP
            for i, cap in enumerate(caps):
                next_cap = caps[i + 1] if i + 1 < len(caps) else None
                x0, y0, x1, y1 = _clip_region(cap, next_cap, image_rects, prev_bottom,
                                              MARGIN_TOP, page_w, page_h)
                if y1 - y0 < MIN_FIG_H:
                    prev_bottom = cap["y1"]
                    continue
                clip = fitz.Rect(x0, y0, x1, y1)
                name = f"{cap['kind']}_{cap['num']}_p{pno}.png"
                path = os.path.join(staging, name)
                try:
                    pix = page.get_pixmap(matrix=fitz.Matrix(FIG_SCALE, FIG_SCALE), clip=clip)
                    pix.save(path)
                except Exception:
                    prev_bottom = cap["y1"]
                    continue
                figs.append({"name": name, "page": pno, "caption": cap["text"], "staging_path": path})
                prev_bottom = cap["y1"] if cap["kind"] == "fig" else max(prev_bottom, y1)
    except Exception:
        pass  # 渲染部分失败返回已有图；doc 由 finally 保证关闭
    finally:
        if doc is not None:
            doc.close()
    if not figs:
        shutil.rmtree(staging, ignore_errors=True)  # 空目录当场清，不留残留
    return figs


def cleanup_figures(figures: list[dict]) -> None:
    """删除图表暂存目录。幂等：无图/路径不合法/已删均安全。由调用方在拷贝到 vault 后调用。"""
    if not figures:
        return
    staging = os.path.dirname(figures[0].get("staging_path") or "")
    if not staging or not os.path.basename(staging).startswith("zotnotes_fig_"):
        return
    shutil.rmtree(staging, ignore_errors=True)


# ---------------- 模板 ----------------

# frontmatter 字段顺序。加字段只改这里 + _placeholder_vals，DEFAULT_TEMPLATE 与 render_skeleton 自动同步。
FM_ORDER = ("zotero_key", "title", "aliases", "authors", "year", "doi", "url", "item_type", "tags", "pdf", "note_file")


def _frontmatter(vals: dict, extra: str | None = None) -> str:
    """生成 frontmatter。tags/aliases 的 vals 值需自带内层引号（如 '"tag1", "tag2"'）。"""
    lines = ["---"]
    for f in FM_ORDER:
        v = vals.get(f, "")
        lines.append(f"{f}: [{v}]" if f in ("tags", "aliases") else f'{f}: "{v}"')
    if extra:
        lines.append(extra)
    lines.append("---")
    return "\n".join(lines)


def _default_template() -> str:
    """默认模板正文。需与磁盘 template.md 的结构保持一致。"""
    vals = {f: "{{zotero:" + f + "}}" for f in FM_ORDER}
    vals["aliases"] = '"{{zotero:title}}"'
    vals["tags"] = "{{zotero:tags}}"
    return (
        _frontmatter(vals)
        + "\n\n# {{zotero:title}}\n\n{{zotero:llm}}\n\n"
        + "## 我的笔记\n\n\n## 疑问\n"
    )


DEFAULT_TEMPLATE = _default_template()


def default_template_path() -> str:
    return os.path.join(BASE_DIR, "template.md")


def load_template(cfg: dict) -> str:
    """读取模板；指定路径不存在时自动创建默认模板，保证可用。"""
    path = (cfg.get("template_path") or "").strip() or default_template_path()
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(DEFAULT_TEMPLATE)
        except OSError:
            pass
        return DEFAULT_TEMPLATE
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return DEFAULT_TEMPLATE


def _yaml_escape(s: str) -> str:
    """YAML 双引号字符串转义（\\ 与 "）。对 Markdown 正文基本透明（\\\" 渲染为 "）。"""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _placeholder_vals(paper: dict, note_file: str) -> dict:
    authors = ", ".join(paper["authors"]) if paper["authors"] else paper["first_author"]
    tags = ", ".join(f'"{_yaml_escape(t)}"' for t in paper["tags"]) if paper["tags"] else ""
    esc = _yaml_escape
    return {
        "zotero_key": esc(paper["key"]),
        "title": esc(paper["title"]),
        "aliases": f'"{esc(paper["title"])}"',
        "authors": esc(authors),
        "year": esc(paper["year"]),
        "doi": esc(paper.get("doi", "")),
        "url": esc(paper.get("url", "")),
        "item_type": esc(paper.get("itemType", "")),
        "tags": tags,
        "pdf": esc(paper.get("pdf_path") or ""),
        "note_file": esc(note_file),
        "llm": "",
    }


def _substitute(template: str, paper: dict, llm_body: str, note_file: str) -> str:
    vals = _placeholder_vals(paper, note_file)
    vals["llm"] = llm_body
    out = template
    for k, v in vals.items():
        out = out.replace("{{zotero:" + k + "}}", v)
    return out


def _add_evidence_line(content: str, value: str) -> str:
    """在 frontmatter 块末尾（闭合 --- 前）插入 evidence 行。"""
    if not content.startswith("---"):
        return content
    end = content.find("\n---", 3)
    if end == -1:
        return content
    return content[:end] + f"\nevidence: {value}" + content[end:]


# ---------------- 证据包（Stage 3） ----------------


def _build_bundle(paper: dict, cfg: dict, pdf_text: str, figures: list[dict]) -> dict:
    fig_info = [
        {"file": f["name"], "page": f["page"], "caption": f["caption"]} for f in figures
    ]
    return {
        "meta": {
            "title": paper["title"],
            "authors": ", ".join(paper["authors"]) or paper["first_author"],
            "year": paper["year"],
            "item_type": paper.get("itemType", ""),
            "doi": paper.get("doi", ""),
            "url": paper.get("url", ""),
            "abstract": paper.get("abstract") or "",
        },
        "pdf_text": pdf_text,
        "figures": fig_info,
    }


# ---------------- LLM 客户端 ----------------


def _client(cfg: dict) -> OpenAI:
    return OpenAI(
        base_url=cfg["llm_base_url"],
        api_key=cfg["llm_api_key"],
        timeout=180.0,
        max_retries=2,
    )


# 领域画像：config 里 llm_profile 可覆盖（空则用默认 SR/ReID 画像），
# 使工具可服务任意研究领域，而不是写死某两个子方向。
DEFAULT_DOMAIN_PROFILE = "你是一名图像超分辨率（SR）与行人重识别（ReID）领域的资深研究员"


def _domain_profile(cfg: dict) -> str:
    return (cfg.get("llm_profile") or "").strip() or DEFAULT_DOMAIN_PROFILE


PLAN_SYSTEM_TMPL = """{profile}。
给定一篇论文的证据包（元数据、摘要、正文摘录、图表清单），先输出一个结构化 JSON 写作计划，
供后续生成深度精读笔记。只输出 JSON，不要任何前后缀或解释。

JSON 结构：
{
  "paper_type": "method | benchmark | survey | clinical | humanities",
  "figures_to_reference": ["文件名1", "文件名2"],
  "required_sections": ["核心信息","原文摘要翻译","创新点","一句话总结","方法主线","核心实验","局限"],
  "mechanism_flow": ["第1步", "第2步", "第3步", "第4步"],
  "key_numbers": ["关键数值1", "关键数值2"],
  "comparison_table": true,
  "key_formulas": ["$公式1$", "$公式2$"],
  "claim_boundaries": ["论文证明了什么", "没有证明什么"],
  "limitations": ["作者承认的局限"],
  "followup_questions": ["读完原文要追查的问题"],
  "notes": "补充说明"
}

规则：
- 只依据证据包内容，不得虚构任何数字、方法或结论。
- method 类论文的 mechanism_flow 写 3-4 步机制流程（输入→中间变换→输出），证据不足就写"证据不足"。
- figures_to_reference 必须来自给定的图表清单中的文件名，不得编造；不重要的图不放进来。
- comparison_table 仅当正文含 3 组及以上系统/设置对比时为 true。
- key_formulas 仅当方法涉及目标函数、更新规则、复杂度表达式时才填。"""


def PLAN_SYSTEM(cfg: dict) -> str:
    return PLAN_SYSTEM_TMPL.format(profile=_domain_profile(cfg))


def _plan_user(bundle: dict) -> str:
    return (
        "论文证据包（JSON）：\n" + json.dumps(bundle, ensure_ascii=False)
        + "\n\n请输出 JSON 写作计划。"
    )


def _extract_json(text: str) -> str:
    """从模型输出中提取 JSON 子串（剥离代码块、取首个 { 到末尾 }）。"""
    t = _strip_fences(text)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return t[start:end + 1]


ALLOWED_PAPER_TYPES = {"method", "benchmark", "survey", "clinical", "humanities"}
LIST_PLAN_FIELDS = (
    "figures_to_reference", "required_sections", "mechanism_flow", "key_numbers",
    "claim_boundaries", "limitations", "followup_questions",
)


def _validate_plan(plan) -> list[str]:
    """校验计划 JSON 的关键字段，返回错误列表（空 = 合法）。"""
    if not isinstance(plan, dict):
        return ["plan 不是 JSON 对象"]
    errs: list[str] = []
    if plan.get("paper_type") not in ALLOWED_PAPER_TYPES:
        errs.append(f"paper_type 非法：{plan.get('paper_type')!r}")
    for f in LIST_PLAN_FIELDS:
        v = plan.get(f)
        if v is not None and not isinstance(v, list):
            errs.append(f"{f} 应为数组")
    return errs


def llm_plan(bundle: dict, cfg: dict) -> dict:
    client = _client(cfg)
    last_err = None
    for _ in range(3):  # 推理模型输出可能截断/加围栏，容错重试
        for use_json_mode in (True, False):  # 部分接口不支持 response_format，回退普通请求
            try:
                kwargs = {"response_format": {"type": "json_object"}} if use_json_mode else {}
                resp = client.chat.completions.create(
                    model=cfg["llm_model"],
                    messages=[
                        {"role": "system", "content": PLAN_SYSTEM(cfg)},
                        {"role": "user", "content": _plan_user(bundle)},
                    ],
                    temperature=0.3,
                    max_tokens=8000,
                    **kwargs,
                )
                text = resp.choices[0].message.content or ""
                plan = json.loads(_extract_json(text))
                errs = _validate_plan(plan)
                if errs:
                    raise ValueError("plan 校验失败：" + "; ".join(errs))
                return plan
            except Exception as e:
                last_err = e
    raise ValueError(f"LLM 计划生成失败：{last_err}")


WRITE_SYSTEM_TMPL = """{profile}，正在为同行写一份
复现导向的深度精读笔记。基于证据包与写作计划输出整篇笔记正文（Markdown）。
只输出正文，不要 frontmatter，不要前言或总结。图表文件夹里（images/<image_dir>/）有提取出的图片。

笔记章节必须按以下顺序：
## 核心信息
（每行 `- 字段名: 值`，只写证据包中真实存在的字段，缺失的整行省略，不得编造）：
标题 / 标题翻译 / 作者 / 机构 / 发表时间 / 发表渠道 / DOI / arXiv / 论文链接 / 代码 / 数据 / 论文类型

## 原文摘要翻译
（忠实翻译原始摘要为中文，不加自己的判断或事后信息，整段中文）

## 创新点
（3-5 条，每条说明解决什么问题、带来什么新能力，避免空泛夸奖）

## 一句话总结
（论文定位的一句话）

## 方法主线
（技术类论文必须包含）
### 机制流程
1. ...（输入）
2. ...（中间变换）
3. ...（输出）
4. ...（训练/推理循环）
（3-4 步编号流程，每步描述操作而非模块名；需要时再加 ### 数据来源 / ### 任务定义 / ### 训练细节）

## 核心实验
（3 组及以上对比用 Markdown 表格并附文字解读；保留关键数值；关键公式用 $...$ 或 $$...$$ 渲染，
不要用代码块）

## 局限
（作者承认的 + 读者能观察到的"没被证明的东西"）

## 与我的研究的关系
（与 SR / ReID 领域的交叉点、可复用的思路、与主流方法的差异）

图表引用：对写作计划 figures_to_reference 里的每个文件，在引用它的章节（通常在方法主线或实验）
插入：
![图注说明](images/<note_key>/<文件名>)

格式规则（Obsidian 渲染约束，必须遵守）：
- 表格单元格内禁用行内公式 $...$ 或 $$...$$（Obsidian 表格内公式渲染异常），单元格内的符号用纯文本或反引号代码，如 `I_SR` 而非 $I_{SR}$。
- 每个表格各行列数必须一致（表头、分隔行、数据行的 | 数量相同）。
- 标题层级只允许 ##（章节）与 ###（小节），不得使用 #、#### 及以上。

语言规则：
- 中文自然行文；专有名词（模型/数据集/指标/方法名）保留英文，可加反引号
- 禁止机械翻译残留（如 "KV缓存 of"、"批量ing" 这类中英混排）
- 禁止句子中间硬换行或残留 PDF 折行
- 禁止输出「待补充」「占位符」「暂无」「TBD」等空内容占位词——证据包提供的材料必须直接写实，材料没有的章节就写「信息不足，需读原文」并保持该章节存在"""


def WRITE_SYSTEM(cfg: dict) -> str:
    return WRITE_SYSTEM_TMPL.format(profile=_domain_profile(cfg))


def _write_user(bundle: dict, plan: dict, image_dir: str) -> str:
    plan_for_model = {k: v for k, v in plan.items() if k != "required_sections"}
    return (
        f"图表文件夹：images/{image_dir}/\n\n"
        "证据包（JSON）：\n" + json.dumps(bundle, ensure_ascii=False) + "\n\n"
        "写作计划（JSON）：\n" + json.dumps(plan_for_model, ensure_ascii=False)
        + "\n\n请输出完整笔记正文。"
    )


MIN_WRITE_CHARS = 800   # 正文太短视为生成失败（防模型空输出/骨架），触发重试


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if t.count("```") >= 2 else t
    return t.strip()


def llm_write(bundle: dict, plan: dict, cfg: dict, image_dir: str) -> str:
    client = _client(cfg)
    last_err = None
    for _ in range(3):  # 推理模型偶发返回空 content，重试
        try:
            resp = client.chat.completions.create(
                model=cfg["llm_model"],
                messages=[
                    {"role": "system", "content": WRITE_SYSTEM(cfg)},
                    {"role": "user", "content": _write_user(bundle, plan, image_dir)},
                ],
                temperature=0.7,
                max_tokens=16000,
            )
            text = _strip_fences(resp.choices[0].message.content or "")
            if len(text) >= MIN_WRITE_CHARS:
                return text
            last_err = ValueError(f"正文输出过短（{len(text)} 字符，需 ≥{MIN_WRITE_CHARS}）")
        except Exception as e:
            last_err = e
    raise ValueError(f"笔记正文生成失败：{last_err}")


# ---------------- 校验与修复（Stage 6） ----------------

CODE_FENCE_RE = re.compile(r"^\s*```")


def _non_code_lines(body: str):
    """生成正文中的非代码块行（lint 只针对正文，跳过 ``` 围栏内的行）。"""
    in_fence = False
    for ln in body.splitlines():
        if CODE_FENCE_RE.match(ln):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield ln


def _table_issues(body: str) -> list[str]:
    """表格质量检查：单元格禁用 $...$ 公式、各行列数一致。返回问题列表。"""
    issues: list[str] = []
    block: list[str] = []
    for ln in _non_code_lines(body):
        if ln.strip().startswith("|") and "|" in ln:
            block.append(ln)
            continue
        issues.extend(_check_table_block(block))
        block = []
    issues.extend(_check_table_block(block))
    return issues


def _check_table_block(block: list[str]) -> list[str]:
    if len(block) < 2:
        return []
    out: list[str] = []
    for ln in block:
        if "$" in ln:
            out.append(f"表格单元格含行内公式 $...$（Obsidian 渲染异常），需改为纯文本或反引号：{ln.strip()[:50]}")
    counts = [ln.count("|") for ln in block]
    if len(set(counts)) > 1:
        out.append(f"表格列数不一致（各行 | 数量 {counts}），需对齐各行列数")
    return out


HEADING_RE = re.compile(r"^(#{1,6})\s+\S")


def _heading_issues(body: str) -> list[str]:
    """标题层级检查：正文只允许 ## 与 ###（# 与 #### 及以上视为错误）。"""
    out: list[str] = []
    for ln in _non_code_lines(body):
        m = HEADING_RE.match(ln)
        if m and len(m.group(1)) not in (2, 3):
            out.append(f"标题层级错误（只允许 ## 与 ###）：{ln.strip()[:50]}")
    return out


def lint_note(body: str, plan: dict, figures: list[dict], image_dir: str) -> list[str]:
    issues: list[str] = []
    for sec in ("## 核心信息", "## 原文摘要翻译", "## 创新点", "## 一句话总结"):
        if sec not in body:
            issues.append(f"缺少必需章节 {sec}")
    if plan.get("paper_type") == "method":
        if "## 方法主线" not in body:
            issues.append("缺少必需章节 ## 方法主线")
        if "### 机制流程" not in body:
            issues.append("缺少必需章节 ### 机制流程")
    # 占位符防线：模型偶发输出「待补充」骨架，需触发修复轮
    placeholder_hits = re.findall(r"(?:待补充|占位符|\[?TODO|TBD)", body)
    if placeholder_hits:
        issues.append(f"笔记含 {len(placeholder_hits)} 处占位符内容（待补充/TODO），需按证据包写实")
    # 图表引用：必须指向已提取的图；计划选定的图必须被引用。目录用唯一 stem（与 prompt/落盘一致）。
    refs = [m.group(1) for m in re.finditer(r"\]\((images/[^)]+)\)", body)]
    wanted = {f"images/{image_dir}/{f['name']}" for f in figures}
    for ref in refs:
        if ref not in wanted:
            issues.append(f"图表引用指向不存在的文件：{ref}")
    for name in plan.get("figures_to_reference") or []:
        if f"images/{image_dir}/{name}" not in refs:
            issues.append(f"计划要求引用的图表未在正文中出现：{name}")
    # 表格与标题质量（Obsidian 渲染约束）
    issues.extend(_table_issues(body))
    issues.extend(_heading_issues(body))
    return issues


FIX_SYSTEM = """你是论文笔记的审校专家。给定一份草稿笔记和问题清单，只修正问题清单指出的问题，
输出修正后的完整笔记正文。
规则：
- 只输出修正后的正文，保持原有章节结构，不要省略任何章节。
- 必须保留草稿中已有的实质内容（数据、方法、结论），只针对问题清单逐条修正，不得凭空重写整篇。
- 禁止输出「待补充」「占位符」「暂无」「TBD」等空内容占位词——证据包提供的材料必须直接写实；
  某处草稿确实没有信息时，如实保留现有内容并写「信息不足，需读原文」，不要填占位符。
- 若草稿缺少某个必需章节，必须补出该章节标题，并基于草稿已有信息写出实质内容。
- 修正时同样遵守格式约束：表格单元格内不用 $...$ 公式、表格各行列数一致、标题只用 ##/###。"""


def llm_fix(body: str, issues: list[str], cfg: dict, bundle: dict | None = None) -> str:
    client = _client(cfg)
    last_err = None
    for _ in range(2):  # 修复轮也可能输出过短骨架，重试一次
        try:
            user_content = "问题清单：\n" + "\n".join(f"- {i}" for i in issues) + "\n\n"
            if bundle is not None:
                # 修复轮附上原始证据包，约束修正以事实为准，不脱离证据重写
                user_content += "原始证据包（JSON，修正时必须以其中的事实为准）：\n" \
                    + json.dumps(bundle, ensure_ascii=False) + "\n\n"
            user_content += "草稿笔记：\n" + body + "\n\n请输出修正后的完整正文。"
            resp = client.chat.completions.create(
                model=cfg["llm_model"],
                messages=[
                    {"role": "system", "content": FIX_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.4,
                max_tokens=12000,
            )
            text = _strip_fences(resp.choices[0].message.content or body)
            if len(text) >= 300:
                return text
            last_err = ValueError(f"修复输出过短（{len(text)} 字符）")
        except Exception as e:
            last_err = e
    # 修复失败保留原稿，由 generate_note 二次 lint 判定
    return body


# ---------------- 骨架笔记（fail-closed） ----------------


def render_skeleton(paper: dict, cfg: dict, note_file: str, reason: str) -> str:
    """无 PDF 正文且无摘要时生成骨架笔记：保留 frontmatter + 空分区骨架，标记证据不足。"""
    vals = _placeholder_vals(paper, note_file)
    body = [
        "",
        f"# {vals['title']}",
        "",
        f"> [!warning] 证据不足（{reason}）",
        "> 未读取到 PDF 正文且库中无摘要，已按 fail-closed 原则生成骨架。请打开原文补充后重试。",
        "",
        "## 核心信息",
        "",
        "## 原文摘要翻译",
        "",
        "## 创新点",
        "",
        "## 一句话总结",
        "",
        "## 方法主线",
        "",
        "### 机制流程",
        "",
        "## 核心实验",
        "",
        "## 局限",
        "",
        "## 与我的研究的关系",
        "",
        "## 我的笔记",
        "",
        "## 疑问",
        "",
    ]
    return _frontmatter(vals, "evidence: insufficient") + "\n\n" + "\n".join(body)


# ---------------- 入口 ----------------


def render_note(paper: dict, cfg: dict, note_file: str) -> str:
    """无 LLM 时的简单模板渲染（占位符 + 空 LLM 区块）。generate_note 在 LLM 关闭时调用。"""
    template = load_template(cfg)
    return _substitute(template, paper, "", note_file)


def generate_note(paper: dict, cfg: dict, note_key: str) -> dict:
    """多阶段深度笔记管道。返回：
    {"content": str, "figures": [figure_dict...], "status": "ok"|"abstract_only"|"needs_source"}
    文件名与图片目录统一用唯一 stem（<safe citekey>-<zotero key>），杜绝 citekey sanitize 碰撞。
    LLM 关闭（cfg["llm_enabled"]=False）时按模板渲染，不调任何接口。
    LLM 调用失败时抛异常并清理暂存图表；成功后由调用方拷贝图表并调 cleanup_figures。
    """
    stem = note_stem(note_key, paper["key"])
    note_file = stem + ".md"
    if not cfg.get("llm_enabled", True):
        # LLM 关闭：无需 PDF 正文/图表，直接按模板渲染（占位符 + 空 LLM 区块）
        return {"content": render_note(paper, cfg, note_file), "figures": [], "status": "ok"}

    pdf_text = ""
    figures: list[dict] = []
    if cfg.get("use_pdf_text", True):
        pdf_text = _extract_pdf_text(paper.get("pdf_path"))
        if pdf_text:
            figures = _extract_figures(paper.get("pdf_path"), stem)

    # 证据等级三级：fulltext（读全正文）/ abstract_only（仅摘要）/ none（无证据）
    abstract = (paper.get("abstract") or "").strip()
    if pdf_text.strip():
        evidence = "fulltext"
    elif abstract:
        evidence = "abstract_only"
    else:
        evidence = "none"
    if evidence == "none":
        content = render_skeleton(
            paper, cfg, note_file,
            reason="PDF 正文不可读（扫描版或无 PDF）且库中无摘要",
        )
        return {"content": content, "figures": [], "status": "needs_source"}

    template = load_template(cfg)
    bundle = _build_bundle(paper, cfg, pdf_text, figures)
    try:
        plan = llm_plan(bundle, cfg)
        body = llm_write(bundle, plan, cfg, stem)
        issues = lint_note(body, plan, figures, stem)
        if issues:
            try:
                body = llm_fix(body, issues, cfg, bundle)
                issues = lint_note(body, plan, figures, stem)  # 二次校验修复结果
            except Exception:
                pass  # 修复调用失败保留原稿，按首次 lint 结果判定
            fatal = [i for i in issues
                     if "缺少必需章节" in i or "占位符" in i or "图表引用指向不存在的文件" in i]
            if fatal:
                raise ValueError("笔记校验未通过：" + "；".join(fatal))
    except Exception:
        cleanup_figures(figures)  # LLM 阶段失败：清掉暂存图表，避免残留
        raise
    content = _substitute(template, paper, body, note_file)
    if evidence == "abstract_only":
        content = _add_evidence_line(content, "abstract_only")
    return {"content": content, "figures": figures,
            "status": "ok" if evidence == "fulltext" else "abstract_only"}

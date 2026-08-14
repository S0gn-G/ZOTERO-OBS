"""lint_note 单元测试：表格 / 标题 / 必需章节 / 占位符 / 图表引用。"""
from core.note_generator import (
    _check_table_block,
    _finalize_body,
    _heading_issues,
    _normalize_plan_figures,
    lint_note,
)


def test_table_cell_formula_issue():
    issues = _check_table_block(["| a | b |", "| --- | --- |", "| 1 | 2 $x$ |"])
    assert any("行内公式" in i for i in issues)


def test_table_column_count_issue():
    issues = _check_table_block(["| a | b |", "| --- | --- |", "| 1 |"])
    assert any("列数" in i for i in issues)


def test_table_valid_block_no_issue():
    assert _check_table_block(["| a | b |", "| --- | --- |", "| 1 | 2 |"]) == []


def test_heading_only_h2_h3():
    issues = _heading_issues("# Big\n## Sec\n### Sub\n#### Deep\n")
    assert len(issues) == 2  # # 与 #### 各报一条


def test_lint_required_sections():
    issues = lint_note("## 核心信息\n", {"paper_type": "benchmark"}, [], "k")
    assert any("缺少必需章节 ## 原文摘要翻译" in i for i in issues)


def test_lint_method_requires_flow():
    body = "## 核心信息\n## 原文摘要翻译\n## 创新点\n## 一句话总结\n## 方法主线\n"
    issues = lint_note(body, {"paper_type": "method"}, [], "k")
    assert any("### 机制流程" in i for i in issues)


def test_lint_placeholder_hits():
    body = "## 核心信息\n## 原文摘要翻译\n## 创新点\n## 一句话总结\n待补充 待补充\n"
    issues = lint_note(body, {"paper_type": "benchmark"}, [], "k")
    assert any("占位符" in i for i in issues)


def test_lint_figure_ref_check():
    body = "## 核心信息\n## 原文摘要翻译\n## 创新点\n## 一句话总结\n![图](images/k/fig_1.png)\n"
    figures = [{"name": "fig_2.png"}]
    issues = lint_note(body, {"paper_type": "benchmark"}, figures, "k")
    assert any("不存在的文件" in i for i in issues)


def test_lint_canonical_dir_no_false_positive():
    # 特殊字符 citekey 下，prompt/落盘/lint 统一用唯一 stem；正确路径不应被误报
    body = ("## 核心信息\n## 原文摘要翻译\n## 创新点\n## 一句话总结\n"
            "![图](images/Wang_Li_2022-K1/fig_1_p1.png)\n")
    figures = [{"name": "fig_1_p1.png"}]
    issues = lint_note(body, {"paper_type": "benchmark"}, figures, "Wang_Li_2022-K1")
    assert not any("不存在的文件" in i for i in issues)
    assert issues == []


def test_lint_canonical_dir_missing_ref_still_flagged():
    # 正确目录下引用不存在的图名仍要报（目录对、文件错）
    body = ("## 核心信息\n## 原文摘要翻译\n## 创新点\n## 一句话总结\n"
            "![图](images/Wang_Li_2022-K1/fig_1_p1.png)\n")
    figures = [{"name": "fig_9_p1.png"}]
    issues = lint_note(body, {"paper_type": "benchmark"}, figures, "Wang_Li_2022-K1")
    assert any("不存在的文件" in i for i in issues)


def test_normalize_plan_figures_removes_names_not_extracted():
    plan = {"figures_to_reference": ["fig_1.png", "invented.png"]}
    _normalize_plan_figures(plan, [{"name": "fig_1.png"}])

    assert plan["figures_to_reference"] == ["fig_1.png"]


def test_finalize_body_resolves_placeholders_and_missing_figure_refs():
    body = (
        "## 核心信息\n待补充\n## 原文摘要翻译\n内容\n## 创新点\n内容\n"
        "## 一句话总结\n内容\n## 局限\n内容\n"
    )
    plan = {"paper_type": "benchmark", "figures_to_reference": ["fig_4_p5.png"]}
    figures = [{"name": "fig_4_p5.png", "caption": "Figure 4. Main results"}]

    finalized = _finalize_body(body, plan, figures, "paper-K1")

    assert "待补充" not in finalized
    assert "信息不足，需读原文" in finalized
    assert "![Figure 4. Main results](images/paper-K1/fig_4_p5.png)" in finalized
    assert finalized.index("### 相关图表") < finalized.index("## 局限")
    assert lint_note(finalized, plan, figures, "paper-K1") == []


def test_finalize_body_does_not_duplicate_existing_figure_ref():
    body = (
        "## 核心信息\n内容\n## 原文摘要翻译\n内容\n## 创新点\n内容\n"
        "## 一句话总结\n内容\n![图](images/paper-K1/fig_1.png)\n"
    )
    plan = {"paper_type": "benchmark", "figures_to_reference": ["fig_1.png"]}
    figures = [{"name": "fig_1.png", "caption": "Figure 1"}]

    finalized = _finalize_body(body, plan, figures, "paper-K1")

    assert finalized.count("images/paper-K1/fig_1.png") == 1

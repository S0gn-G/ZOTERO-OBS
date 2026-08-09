"""generate_note 证据等级与 LLM 开关分支（monkeypatch 掉全部 LLM/PDF 调用）。"""
import os
import tempfile

import pytest

import note_generator as ng


def _paper(**kw):
    base = {
        "key": "K1", "title": "T", "authors": [], "first_author": "A",
        "year": "2021", "date": "", "doi": "", "url": "", "abstract": "",
        "tags": [], "citationKey": "cite", "pdf_path": None,
        "itemType": "journalArticle", "dateAdded": "",
    }
    base.update(kw)
    return base


def _cfg(**kw):
    cfg = {
        "llm_enabled": True, "use_pdf_text": True,
        "llm_base_url": "http://x", "llm_api_key": "k", "llm_model": "m",
        "llm_profile": "",
    }
    cfg.update(kw)
    return cfg


def _clean_body():
    return (
        "## 核心信息\n\n- 标题: X\n\n"
        "## 原文摘要翻译\n\n摘要\n\n"
        "## 创新点\n\n1. x\n\n"
        "## 一句话总结\n\nx\n\n"
        "## 方法主线\n\n### 机制流程\n\n1. a\n\n"
        "## 核心实验\n\n表\n\n"
        "## 局限\n\nx\n\n"
        "## 与我的研究的关系\n\nx\n"
    )


def _fake_plan(bundle, cfg):
    return {
        "paper_type": "method", "figures_to_reference": [],
        "required_sections": [], "mechanism_flow": [], "key_numbers": [],
        "comparison_table": False, "key_formulas": [],
        "claim_boundaries": [], "limitations": [], "followup_questions": [],
        "notes": "",
    }


def _no_text(pdf_path, max_chars=30000):
    return ""


def test_llm_disabled_renders_template(monkeypatch):
    paper = _paper()
    result = ng.generate_note(paper, _cfg(llm_enabled=False), note_key="cite")
    assert result["status"] == "ok"
    assert result["figures"] == []
    assert "## 我的笔记" in result["content"]


def test_evidence_none_skeleton(monkeypatch):
    monkeypatch.setattr(ng, "_extract_pdf_text", _no_text)
    paper = _paper()
    result = ng.generate_note(paper, _cfg(), note_key="cite")
    assert result["status"] == "needs_source"
    assert result["figures"] == []
    assert "evidence: insufficient" in result["content"]


def test_evidence_abstract_only(monkeypatch):
    monkeypatch.setattr(ng, "_extract_pdf_text", _no_text)
    monkeypatch.setattr(ng, "llm_plan", _fake_plan)
    monkeypatch.setattr(ng, "llm_write", lambda b, p, c, k: _clean_body())
    paper = _paper(abstract="Some abstract text about the method.")
    result = ng.generate_note(paper, _cfg(), note_key="cite")
    assert result["status"] == "abstract_only"
    assert "evidence: abstract_only" in result["content"]


def test_evidence_fulltext(monkeypatch):
    monkeypatch.setattr(ng, "_extract_pdf_text", lambda p, max_chars=30000: "real full text " * 500)
    monkeypatch.setattr(ng, "_extract_figures", lambda p, k: [])
    monkeypatch.setattr(ng, "llm_plan", _fake_plan)
    monkeypatch.setattr(ng, "llm_write", lambda b, p, c, k: _clean_body())
    paper = _paper(pdf_path="C:/x.pdf", abstract="has abstract")
    result = ng.generate_note(paper, _cfg(), note_key="cite")
    assert result["status"] == "ok"
    assert "evidence:" not in result["content"]


def test_llm_failure_cleans_figures(monkeypatch):
    staging = tempfile.mkdtemp(prefix="zotnotes_fig_evid_")
    fig = {"name": "fig_1_p1.png", "page": 1, "caption": "Figure 1",
           "staging_path": os.path.join(staging, "fig_1_p1.png")}
    open(fig["staging_path"], "w").close()
    monkeypatch.setattr(ng, "_extract_pdf_text", lambda p, max_chars=30000: "text " * 100)
    monkeypatch.setattr(ng, "_extract_figures", lambda p, k: [fig])

    def boom(bundle, cfg):
        raise RuntimeError("llm down")

    monkeypatch.setattr(ng, "llm_plan", boom)
    with pytest.raises(RuntimeError):
        ng.generate_note(_paper(pdf_path="C:/x.pdf"), _cfg(), note_key="cite")
    assert not os.path.exists(staging)


def test_cleanup_figures_idempotent(tmp_path):
    ng.cleanup_figures([])
    d = tmp_path / "not_prefix"
    d.mkdir()
    ng.cleanup_figures([{"name": "x.png", "staging_path": str(d / "x.png")}])
    assert d.is_dir()  # 目录名不合法，不应被删

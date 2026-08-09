"""_clip_region 图表裁剪几何测试：fig 上探 / 高图 gap / table bbox / 兜底封顶 / Table→Figure 不跳过。"""
from note_generator import _clip_region, CAPTION_RE, MIN_FIG_H


class R:
    """模拟 fitz.Rect，只暴露裁剪用到的属性。"""

    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1


def cap(kind, y0, y1, num=1):
    return {"kind": kind, "num": num, "y0": y0, "y1": y1}


# ---------- fig：caption 上方 ----------

def test_fig_uses_image_rect_upward_probe():
    # 图注 y≈487，图上沿 60、底 460，gap=27（≤60）→ 上探到 60
    c = cap("fig", 487, 497)
    r = R(50, 60, 300, 460)
    x0, y0, x1, y1 = _clip_region(c, None, [r], [], 55.0, 55.0, 595, 842)
    assert y0 <= 60
    assert y1 == 483


def test_fig_gap_too_large_no_probe():
    # gap=487-380=107 > FIG_CAPTION_MAX_GAP → 不上探，回到默认高度
    c = cap("fig", 487, 497)
    r = R(50, 60, 300, 380)
    x0, y0, x1, y1 = _clip_region(c, None, [r], [], 55.0, 55.0, 595, 842)
    assert y0 == 123  # 483 - FIG_MAX_HEIGHT
    assert y1 == 483


def test_fig_no_image_default_height():
    c = cap("fig", 487, 497)
    x0, y0, x1, y1 = _clip_region(c, None, [], [], 55.0, 55.0, 595, 842)
    assert y0 == 123
    assert y1 == 483


def test_fig_respects_prev_bottom():
    c = cap("fig", 487, 497)
    x0, y0, x1, y1 = _clip_region(c, None, [], [], 300.0, 55.0, 595, 842)
    assert y0 == 300  # prev_bottom 高于默认上探
    assert y1 == 483


# ---------- table：caption 下方（bbox 主选 / 兜底封顶） ----------

def test_table_uses_bbox_when_found():
    c = cap("table", 180, 190)
    tb = R(50, 200, 300, 400)  # find_tables 检测到的表格
    x0, y0, x1, y1 = _clip_region(c, None, [], [tb], 55.0, 55.0, 595, 842)
    assert y0 == 194
    assert y1 == 408  # 表底 400 + TABLE_PAD，精确而非整页


def test_table_bbox_preferred_over_fallback():
    c = cap("table", 180, 190)
    tb = R(50, 200, 300, 250)
    x0, y0, x1, y1 = _clip_region(c, None, [], [tb], 55.0, 55.0, 595, 842)
    assert y1 == 258  # 用 bbox，而不是兜底 194+220


def test_table_bbox_limited_by_next_caption():
    c = cap("table", 180, 190)
    nxt = cap("fig", 500, 510)
    tb = R(50, 200, 300, 550)  # bbox 越过下一图注
    x0, y0, x1, y1 = _clip_region(c, nxt, [], [tb], 55.0, 55.0, 595, 842)
    assert y0 == 194
    assert y1 == 496  # next_cap y0 - 4，不吞后面内容


def test_table_fallback_capped_height():
    # 无 bbox：不再截到页底，封顶 y0 + TABLE_MAX_HEIGHT
    c = cap("table", 180, 190)
    x0, y0, x1, y1 = _clip_region(c, None, [], [], 55.0, 55.0, 595, 842)
    assert y0 == 194
    assert y1 == 414  # 194 + 220，而非 802（页底）


def test_table_stops_at_next_caption_fallback():
    c = cap("table", 180, 190)
    nxt = cap("fig", 420, 430)
    x0, y0, x1, y1 = _clip_region(c, nxt, [], [], 55.0, 55.0, 595, 842)
    assert y0 == 194
    assert y1 == 414  # min(next_bound=416, 194+220=414)


def test_table_respects_prev_bottom():
    c = cap("table", 180, 190)
    x0, y0, x1, y1 = _clip_region(c, None, [], [], 200.0, 55.0, 595, 842)
    assert y0 == 200  # prev_bottom 高于 cap+4


# ---------- Table→Figure 同页排列回归（P1-1） ----------

def test_fig_after_table_not_skipped():
    # 表注(180,190) → 图注(420,430)，无 bbox、无内嵌图：Figure 高度不能被 prev_bottom 归零
    tab = cap("table", 180, 190)
    fig = cap("fig", 420, 430)
    x0, ty0, x1, ty1 = _clip_region(tab, fig, [], [], 55.0, 55.0, 595, 842)
    x0, fy0, x1, fy1 = _clip_region(fig, None, [], [], ty1, 55.0, 595, 842)
    assert fy1 - fy0 >= MIN_FIG_H


def test_fig_after_table_with_bbox():
    # 表有 bbox → prev_bottom 停在表底，Figure 有更充足的区域
    tab = cap("table", 180, 190)
    fig = cap("fig", 420, 430)
    tb = R(50, 200, 300, 300)
    x0, ty0, x1, ty1 = _clip_region(tab, fig, [], [tb], 55.0, 55.0, 595, 842)
    assert ty1 == 308  # 300 + TABLE_PAD
    x0, fy0, x1, fy1 = _clip_region(fig, None, [], [], ty1, 55.0, 595, 842)
    assert fy1 - fy0 >= MIN_FIG_H
    assert fy0 == 308  # 从表底开始，不吞表


# ---------- Roman 数字表注（P2） ----------

def test_caption_re_roman_table():
    m = CAPTION_RE.match("TABLE I. Accuracy results")
    assert m and m.group(2) is not None  # 表注（(?i) 保留原大小写，只判 truthy）
    assert m.group(3) == "I"


def test_caption_re_arabic_still_works():
    m = CAPTION_RE.match("Table 3: Results")
    assert m and m.group(3) == "3"


def test_caption_re_rejects_roman_inside_word():
    # "Table Index" 不应被当成 Table I
    assert CAPTION_RE.match("Table Index 2021") is None

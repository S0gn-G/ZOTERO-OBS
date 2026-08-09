"""_clip_region 图表裁剪几何测试：fig 上探 / 高图 gap / table 向下 / prev_bottom 约束。"""
from note_generator import _clip_region


class R:
    """模拟 fitz.Rect，只暴露裁剪用到的属性。"""

    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1


def cap(kind, y0, y1, num=1):
    return {"kind": kind, "num": num, "y0": y0, "y1": y1}


def test_fig_uses_image_rect_upward_probe():
    # 图注 y≈487，图上沿 60、底 460，gap=27（≤60）→ 上探到 60
    c = cap("fig", 487, 497)
    r = R(50, 60, 300, 460)
    x0, y0, x1, y1 = _clip_region(c, None, [r], 55.0, 55.0, 595, 842)
    assert y0 <= 60
    assert y1 == 483


def test_fig_gap_too_large_no_probe():
    # gap=487-380=107 > FIG_CAPTION_MAX_GAP → 不上探，回到默认高度
    c = cap("fig", 487, 497)
    r = R(50, 60, 300, 380)
    x0, y0, x1, y1 = _clip_region(c, None, [r], 55.0, 55.0, 595, 842)
    assert y0 == 123  # 483 - FIG_MAX_HEIGHT
    assert y1 == 483


def test_fig_no_image_default_height():
    c = cap("fig", 487, 497)
    x0, y0, x1, y1 = _clip_region(c, None, [], 55.0, 55.0, 595, 842)
    assert y0 == 123
    assert y1 == 483


def test_fig_respects_prev_bottom():
    c = cap("fig", 487, 497)
    x0, y0, x1, y1 = _clip_region(c, None, [], 300.0, 55.0, 595, 842)
    assert y0 == 300  # prev_bottom 高于默认上探
    assert y1 == 483


def test_table_crops_below_caption():
    # 表格在 caption 下方：默认裁到页底
    c = cap("table", 180, 190)
    x0, y0, x1, y1 = _clip_region(c, None, [], 55.0, 55.0, 595, 842)
    assert y0 == 194  # cap y1 + 4
    assert y1 == 802  # 842 - MARGIN_BOTTOM


def test_table_stops_at_next_caption():
    c = cap("table", 180, 190)
    nxt = cap("fig", 420, 430)
    x0, y0, x1, y1 = _clip_region(c, nxt, [], 55.0, 55.0, 595, 842)
    assert y0 == 194
    assert y1 == 416  # next_cap y0 - 4


def test_table_probe_image_below():
    # 表下方图片超出 next caption → 下探到图片底
    c = cap("table", 180, 190)
    nxt = cap("fig", 420, 430)
    r = R(50, 200, 300, 500)
    x0, y0, x1, y1 = _clip_region(c, nxt, [r], 55.0, 55.0, 595, 842)
    assert y1 == 500


def test_table_respects_prev_bottom():
    c = cap("table", 180, 190)
    x0, y0, x1, y1 = _clip_region(c, None, [], 200.0, 55.0, 595, 842)
    assert y0 == 200  # prev_bottom 高于 cap+4

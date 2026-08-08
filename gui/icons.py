"""程序内图标：用 Pillow 绘制简洁线性图标，返回 CTkImage。"""
import math

from PIL import Image, ImageDraw
import customtkinter as ctk

SIZE = 20
COLOR = "#FFFFFF"


def _base():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _ctk(img):
    return ctk.CTkImage(light_image=img, dark_image=img, size=(SIZE, SIZE))


def _pt(cx, cy, r, deg):
    a = math.radians(deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def settings():
    """三条滑块 = 设置。"""
    img, d = _base()
    for y in (6, 10, 14):
        d.line([(4, y), (16, y)], fill=COLOR, width=2)
    d.ellipse([(12, 4), (16, 8)], fill=COLOR)
    d.ellipse([(8, 8), (12, 12)], fill=COLOR)
    d.ellipse([(13, 12), (17, 16)], fill=COLOR)
    return _ctk(img)


def template():
    """文档 + 折角 + 文字行 = 模板。"""
    img, d = _base()
    d.rectangle([(5, 3), (15, 17)], outline=COLOR, width=2)
    d.polygon([(12, 3), (12, 7), (15, 7)], fill=COLOR)
    for y in (10, 13):
        d.line([(7, y), (13, y)], fill=COLOR, width=1)
    return _ctk(img)


def refresh():
    """圆环 + 双箭头 = 刷新。"""
    img, d = _base()
    cx = cy = 10
    d.arc([cx - 7, cy - 7, cx + 7, cy + 7], start=40, end=320, fill=COLOR, width=2)
    # 缺口两端的箭头
    tip = _pt(cx, cy, 8, 320)
    b1 = _pt(cx, cy, 5.5, 320 - 30)
    b2 = _pt(cx, cy, 5.5, 320 + 30)
    d.polygon([tip, b1, b2], fill=COLOR)
    tip = _pt(cx, cy, 8, 40)
    b1 = _pt(cx, cy, 5.5, 40 - 30)
    b2 = _pt(cx, cy, 5.5, 40 + 30)
    d.polygon([tip, b1, b2], fill=COLOR)
    return _ctk(img)


def play():
    """三角播放 = 生成。"""
    img, d = _base()
    d.polygon([(6, 4), (6, 16), (16, 10)], fill=COLOR)
    return _ctk(img)


def pdf():
    """小文档 = PDF。"""
    img, d = _base()
    d.rectangle([(5, 4), (15, 16)], outline=COLOR, width=2)
    d.line([(7, 8), (13, 8)], fill=COLOR, width=1)
    d.line([(7, 11), (13, 11)], fill=COLOR, width=1)
    return _ctk(img)

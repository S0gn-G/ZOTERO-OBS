"""程序内图标：用 Pillow 绘制轻量线性图标，返回缓存的 CTkImage。"""
import math
from functools import lru_cache

from PIL import Image, ImageDraw
import customtkinter as ctk

SIZE = 20


def _base():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _ctk(img, size=SIZE):
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


def _pt(cx, cy, r, deg):
    a = math.radians(deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


@lru_cache(maxsize=None)
def refresh(color="#FFFFFF"):
    """圆环 + 双箭头 = 刷新。"""
    img, d = _base()
    cx = cy = 10
    d.arc([cx - 7, cy - 7, cx + 7, cy + 7], start=40, end=320, fill=color, width=2)
    # 缺口两端的箭头
    tip = _pt(cx, cy, 8, 320)
    b1 = _pt(cx, cy, 5.5, 320 - 30)
    b2 = _pt(cx, cy, 5.5, 320 + 30)
    d.polygon([tip, b1, b2], fill=color)
    tip = _pt(cx, cy, 8, 40)
    b1 = _pt(cx, cy, 5.5, 40 - 30)
    b2 = _pt(cx, cy, 5.5, 40 + 30)
    d.polygon([tip, b1, b2], fill=color)
    return _ctk(img)


@lru_cache(maxsize=None)
def play(color="#FFFFFF"):
    """三角播放 = 生成。"""
    img, d = _base()
    d.polygon([(6, 4), (6, 16), (16, 10)], fill=color)
    return _ctk(img)


@lru_cache(maxsize=None)
def search(color="#73847A"):
    img, d = _base()
    d.ellipse([(4, 4), (13, 13)], outline=color, width=2)
    d.line([(12, 12), (17, 17)], fill=color, width=2)
    return _ctk(img, 18)


@lru_cache(maxsize=None)
def book(color="#FFFFFF"):
    img, d = _base()
    d.rounded_rectangle([(3, 3), (17, 17)], radius=2, outline=color, width=2)
    d.line([(7, 3), (7, 17)], fill=color, width=2)
    d.line([(9, 7), (14, 7)], fill=color, width=1)
    d.line([(9, 10), (14, 10)], fill=color, width=1)
    return _ctk(img)


@lru_cache(maxsize=None)
def file(color="#2F8F68"):
    img, d = _base()
    d.line([(5, 3), (13, 3), (16, 6), (16, 17), (5, 17), (5, 3)], fill=color, width=2)
    d.line([(13, 3), (13, 7), (16, 7)], fill=color, width=2)
    return _ctk(img, 18)


@lru_cache(maxsize=None)
def sliders(color="#2F8F68"):
    img, d = _base()
    for y, knob in ((5, 12), (10, 8), (15, 13)):
        d.line([(3, y), (17, y)], fill=color, width=2)
        d.ellipse([(knob - 2, y - 2), (knob + 2, y + 2)], fill=color)
    return _ctk(img, 18)

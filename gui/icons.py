"""高分辨率自绘图标；每个图标同时提供日间与夜间版本。"""
import math
from functools import lru_cache

from PIL import Image, ImageDraw
import customtkinter as ctk

from gui import design as ui

SIZE = 20
SCALE = 4


def _base():
    image = Image.new("RGBA", (SIZE * SCALE, SIZE * SCALE), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def _v(value):
    return round(value * SCALE)


def _box(values):
    return tuple(_v(value) for value in values)


def _points(values):
    return [(_v(x), _v(y)) for x, y in values]


def _ctk(draw_icon, colors, size=SIZE):
    images = []
    for color in colors:
        image, draw = _base()
        draw_icon(draw, color)
        images.append(image.resize((SIZE, SIZE), Image.Resampling.LANCZOS))
    return ctk.CTkImage(light_image=images[0], dark_image=images[1], size=(size, size))


def _pt(cx, cy, radius, degrees):
    angle = math.radians(degrees)
    return (cx + radius * math.cos(angle), cy + radius * math.sin(angle))


def _draw_refresh(draw, color):
    draw.arc(_box((3, 3, 17, 17)), start=40, end=320, fill=color, width=_v(2))
    for degrees in (320, 40):
        tip = _pt(10, 10, 8, degrees)
        base_1 = _pt(10, 10, 5.5, degrees - 30)
        base_2 = _pt(10, 10, 5.5, degrees + 30)
        draw.polygon(_points((tip, base_1, base_2)), fill=color)


def _draw_play(draw, color):
    draw.polygon(_points(((6.5, 4.5), (6.5, 15.5), (15.5, 10))), fill=color)


def _draw_search(draw, color):
    draw.ellipse(_box((3.5, 3.5, 13.5, 13.5)), outline=color, width=_v(2))
    draw.line(_points(((12.5, 12.5), (17, 17))), fill=color, width=_v(2))


def _draw_book(draw, color):
    draw.rounded_rectangle(
        _box((3, 3, 17, 17)), radius=_v(2), outline=color, width=_v(2)
    )
    draw.line(_points(((7, 3), (7, 17))), fill=color, width=_v(2))
    draw.line(_points(((9.5, 7), (14, 7))), fill=color, width=_v(1.5))
    draw.line(_points(((9.5, 10), (14, 10))), fill=color, width=_v(1.5))


def _draw_file(draw, color):
    draw.line(
        _points(((5, 3), (13, 3), (16, 6), (16, 17), (5, 17), (5, 3))),
        fill=color, width=_v(2), joint="curve",
    )
    draw.line(_points(((13, 3), (13, 7), (16, 7))), fill=color, width=_v(2))


def _draw_sliders(draw, color):
    for y, knob in ((5, 12), (10, 8), (15, 13)):
        draw.line(_points(((3, y), (17, y))), fill=color, width=_v(2))
        draw.ellipse(_box((knob - 2, y - 2, knob + 2, y + 2)), fill=color)


def _draw_moon(draw, color):
    draw.ellipse(_box((3.5, 2.5, 16.5, 17.5)), fill=color)
    draw.ellipse(_box((8, 0.5, 19, 12.5)), fill=(0, 0, 0, 0))


def _draw_sun(draw, color):
    draw.ellipse(_box((7, 7, 13, 13)), outline=color, width=_v(2))
    for degrees in range(0, 360, 45):
        draw.line(
            _points((_pt(10, 10, 5, degrees), _pt(10, 10, 8, degrees))),
            fill=color, width=_v(1.7),
        )


@lru_cache(maxsize=None)
def refresh():
    return _ctk(_draw_refresh, ui.ON_ACCENT)


@lru_cache(maxsize=None)
def play():
    return _ctk(_draw_play, ui.ON_ACCENT)


@lru_cache(maxsize=None)
def search():
    return _ctk(_draw_search, ui.TEXT_TERTIARY, 18)


@lru_cache(maxsize=None)
def book():
    return _ctk(_draw_book, ui.ON_ACCENT)


@lru_cache(maxsize=None)
def file():
    return _ctk(_draw_file, ui.ACCENT_TEXT, 18)


@lru_cache(maxsize=None)
def sliders():
    return _ctk(_draw_sliders, ui.ACCENT_TEXT, 18)


@lru_cache(maxsize=None)
def sliders_on_accent():
    return _ctk(_draw_sliders, ui.ON_ACCENT, 18)


@lru_cache(maxsize=None)
def moon():
    return _ctk(_draw_moon, ui.ACCENT_TEXT, 17)


@lru_cache(maxsize=None)
def sun():
    return _ctk(_draw_sun, ui.ACCENT_TEXT, 17)

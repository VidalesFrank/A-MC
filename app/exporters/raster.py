"""Rasteriza una `drawing.Scene` a PNG.

El SVG, el PDF y el DXF salen vectoriales, pero Word no admite ninguno de los
tres desde `python-docx`: solo mapas de bits. Aqui se dibuja la misma escena con
Pillow para poder incrustar las figuras en la memoria de calculo.

Se rasteriza con supermuestreo y luego se reduce, que es la forma barata de
tener lineas y texto suavizados sin dibujar nada a mano.
"""
from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw, ImageFont

from .drawing import LAYERS, Arc, Circle, Line, Poly, Scene, Text

SS = 3          # factor de supermuestreo


def _rgb(hexcolor: str) -> tuple[int, int, int]:
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _fuente(px: int):
    """Una fuente TrueType si el sistema la tiene; si no, la de mapa de bits."""
    px = max(int(px), 1)
    for nombre in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "calibri.ttf"):
        try:
            return ImageFont.truetype(nombre, px)
        except OSError:
            continue
    return ImageFont.load_default()


def to_png(sc: Scene, ancho_px: int = 1600, alto_px: int | None = None,
           margen: float = 0.03, fondo: str = "#ffffff") -> bytes:
    """Devuelve el PNG de la escena, ajustada y centrada en el lienzo."""
    x0, y0, x1, y1 = sc.bbox()
    w = max(x1 - x0, 1e-9)
    h = max(y1 - y0, 1e-9)
    if alto_px is None:
        alto_px = max(int(ancho_px * h / w), 40)

    W, H = int(ancho_px) * SS, int(alto_px) * SS
    mg = margen * min(W, H)
    k = min((W - 2 * mg) / w, (H - 2 * mg) / h)
    ox = (W - w * k) / 2.0 - x0 * k
    oy = (H - h * k) / 2.0 + y1 * k          # la Y de la imagen crece hacia abajo

    def X(x):
        return ox + x * k

    def Y(y):
        return oy - y * k

    img = Image.new("RGB", (W, H), fondo)
    d = ImageDraw.Draw(img)

    for p in sc.prims:
        L = LAYERS.get(p.layer, LAYERS["TEXTO"])
        col = _rgb(L.rgb)
        gr = max(int(L.lw * SS * 1.6), 1)
        if isinstance(p, Line):
            d.line([X(p.x1), Y(p.y1), X(p.x2), Y(p.y2)], fill=col, width=gr)
        elif isinstance(p, Circle):
            r = p.r * k
            d.ellipse([X(p.cx) - r, Y(p.cy) - r, X(p.cx) + r, Y(p.cy) + r],
                      outline=col, width=gr)
        elif isinstance(p, Arc):
            r = p.r * k
            # Pillow mide los angulos en sentido horario desde las 3; la escena
            # los da antihorarios, asi que se invierten.
            d.arc([X(p.cx) - r, Y(p.cy) - r, X(p.cx) + r, Y(p.cy) + r],
                  start=-p.a1, end=-p.a0, fill=col, width=gr)
        elif isinstance(p, Poly):
            pts = [(X(x), Y(y)) for x, y in p.pts]
            if p.closed:
                pts.append(pts[0])
            d.line(pts, fill=col, width=gr, joint="curve")
        elif isinstance(p, Text):
            _texto(d, p, X, Y, k, col)

    if SS > 1:
        img = img.resize((int(ancho_px), int(alto_px)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _texto(d, p: Text, X, Y, k: float, col) -> None:
    px = max(p.h * k, 1.0)
    f = _fuente(px)
    try:
        caja = d.textbbox((0, 0), p.s, font=f)
        ancho, alto = caja[2] - caja[0], caja[3] - caja[1]
    except Exception:
        ancho, alto = len(p.s) * px * 0.55, px
    dx = {"left": 0.0, "center": -ancho / 2.0, "right": -ancho}[p.halign]
    dy = {"base": -alto, "middle": -alto / 2.0, "top": 0.0}[p.valign]
    x, y = X(p.x), Y(p.y)

    if abs(p.rot) < 1e-9:
        d.text((x + dx, y + dy), p.s, fill=col, font=f)
        return
    # El texto girado se pinta aparte y se pega rotado
    tmp = Image.new("RGBA", (max(int(ancho) + 4, 2), max(int(alto) + 4, 2)), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((0, 0), p.s, fill=col + (255,), font=f)
    tmp = tmp.rotate(p.rot, expand=True, resample=Image.BICUBIC)
    a = math.radians(p.rot)
    px2 = x + dx * math.cos(a) - dy * math.sin(a)
    py2 = y + dx * math.sin(a) + dy * math.cos(a)
    d.bitmap((px2 - tmp.width / 2.0, py2 - tmp.height / 2.0), tmp.split()[3], fill=col)

"""Escena de dibujo neutra, comun a DXF, SVG y PDF.

Se define una sola vez la geometria del despiece en coordenadas de modelo
(X a la derecha, Y arriba, metros) y de ahi salen los tres formatos: el DXF para
el dibujante, y el SVG y el PDF para revisar e incrustar en la memoria.

Es el mismo criterio que ya sigue el modelo estructural con el .s2k y el OAPI:
una representacion intermedia y varios exportadores.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Capas
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Layer:
    name: str
    aci: int          # indice de color de AutoCAD
    rgb: str          # color para SVG/PDF
    lw: float = 0.25  # grosor de linea en mm
    dashed: bool = False


LAYERS = {
    "CONCRETO": Layer("CONCRETO", 8, "#808080", 0.35),
    "REFUERZO": Layer("REFUERZO", 1, "#d02020", 0.50),
    "ESTRIBOS": Layer("ESTRIBOS", 4, "#0e8bb8", 0.35),
    "EJES": Layer("EJES", 2, "#b58900", 0.18, dashed=True),
    "COTAS": Layer("COTAS", 3, "#0c8f63", 0.18),
    "TEXTO": Layer("TEXTO", 7, "#202020", 0.18),
    "TABLA": Layer("TABLA", 7, "#202020", 0.18),
    "TERRENO": Layer("TERRENO", 33, "#8b6b4a", 0.25),
}


# --------------------------------------------------------------------------
# Primitivas
# --------------------------------------------------------------------------
@dataclass
class Line:
    x1: float; y1: float; x2: float; y2: float
    layer: str = "CONCRETO"


@dataclass
class Circle:
    cx: float; cy: float; r: float
    layer: str = "CONCRETO"


@dataclass
class Arc:
    """Arco en sentido antihorario de a0 a a1, en grados."""
    cx: float; cy: float; r: float; a0: float; a1: float
    layer: str = "REFUERZO"


@dataclass
class Poly:
    pts: list[tuple[float, float]]
    layer: str = "CONCRETO"
    closed: bool = False


@dataclass
class Text:
    x: float; y: float
    h: float                     # altura del texto en unidades de modelo
    s: str
    layer: str = "TEXTO"
    rot: float = 0.0             # grados
    halign: str = "left"         # left | center | right
    valign: str = "base"         # base | middle | top
    # Una nota larga explica el dibujo pero no forma parte de el. Si entra en el
    # encuadre, una linea de cuatro metros de modelo obliga a dibujar el muro a
    # la mitad de escala para que quepa la frase.
    encuadre: bool = True


Prim = Line | Circle | Arc | Poly | Text


# --------------------------------------------------------------------------
# Escena
# --------------------------------------------------------------------------
class Scene:
    """Contenedor de primitivas con helpers de cota y de transformacion."""

    def __init__(self, nombre: str = "Despiece") -> None:
        self.nombre = nombre
        self.prims: list[Prim] = []

    # -- primitivas --------------------------------------------------------
    def line(self, x1, y1, x2, y2, layer="CONCRETO") -> None:
        self.prims.append(Line(x1, y1, x2, y2, layer))

    def circle(self, cx, cy, r, layer="CONCRETO") -> None:
        self.prims.append(Circle(cx, cy, r, layer))

    def arc(self, cx, cy, r, a0, a1, layer="REFUERZO") -> None:
        self.prims.append(Arc(cx, cy, r, a0, a1, layer))

    def poly(self, pts, layer="CONCRETO", closed=False) -> None:
        if len(pts) >= 2:
            self.prims.append(Poly(list(pts), layer, closed))

    def text(self, x, y, h, s, layer="TEXTO", rot=0.0, halign="left", valign="base",
             encuadre: bool = True) -> None:
        if s:
            self.prims.append(Text(x, y, h, str(s), layer, rot, halign, valign, encuadre))

    def rect(self, x, y, w, h, layer="CONCRETO") -> None:
        self.poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], layer, closed=True)

    # -- ayudas ------------------------------------------------------------
    def hatch_diag(self, x, y, w, h, paso: float, layer="TERRENO", ang: float = 45.0) -> None:
        """Rayado diagonal simple, recortado al rectangulo."""
        if paso <= 0 or w <= 0 or h <= 0:
            return
        t = math.tan(math.radians(ang)) or 1.0
        x0 = x - h / t
        n = int((w + h / t) / paso) + 1
        for i in range(n + 1):
            xa = x0 + i * paso
            # recta de pendiente t desde (xa, y); se recorta a la caja
            pts = []
            for xx, yy in ((xa, y), (xa + h / t, y + h)):
                pts.append((xx, yy))
            (ax, ay), (bx, by) = pts
            # recorte por X
            if bx <= x or ax >= x + w:
                continue
            if ax < x:
                ay = ay + (x - ax) * t
                ax = x
            if bx > x + w:
                by = by - (bx - (x + w)) * t
                bx = x + w
            self.line(ax, ay, bx, by, layer)

    def dim_h(self, x1, x2, y, texto: str, h: float, layer="COTAS", off: float = 0.0) -> None:
        """Cota horizontal con marcas inclinadas en los extremos."""
        yy = y + off
        self.line(x1, yy, x2, yy, layer)
        for xx in (x1, x2):
            self.line(xx - h * 0.35, yy - h * 0.35, xx + h * 0.35, yy + h * 0.35, layer)
            self.line(xx, yy - h * 0.8, xx, yy + h * 0.8, layer)
        self.text((x1 + x2) / 2.0, yy + h * 0.45, h, texto, layer, halign="center")

    def dim_v(self, y1, y2, x, texto: str, h: float, layer="COTAS", off: float = 0.0) -> None:
        """Cota vertical; el texto va girado 90 grados."""
        xx = x + off
        self.line(xx, y1, xx, y2, layer)
        for yy in (y1, y2):
            self.line(xx - h * 0.35, yy - h * 0.35, xx + h * 0.35, yy + h * 0.35, layer)
            self.line(xx - h * 0.8, yy, xx + h * 0.8, yy, layer)
        self.text(xx - h * 0.45, (y1 + y2) / 2.0, h, texto, layer, rot=90.0, halign="center")

    def leader(self, x, y, xt, yt, texto: str, h: float, layer="TEXTO") -> None:
        """Directriz con texto: una linea quebrada y la etiqueta al final."""
        self.line(x, y, xt, yt, layer)
        lado = h * 0.8 if xt >= x else -h * 0.8
        self.line(xt, yt, xt + lado, yt, layer)
        self.text(xt + lado * 1.3, yt - h * 0.35, h, texto, layer,
                  halign="left" if xt >= x else "right")

    # -- composicion -------------------------------------------------------
    def bbox(self) -> tuple[float, float, float, float]:
        xs, ys = [], []
        for p in self.prims:
            if isinstance(p, Line):
                xs += [p.x1, p.x2]; ys += [p.y1, p.y2]
            elif isinstance(p, Circle):
                xs += [p.cx - p.r, p.cx + p.r]; ys += [p.cy - p.r, p.cy + p.r]
            elif isinstance(p, Arc):
                xs += [p.cx - p.r, p.cx + p.r]; ys += [p.cy - p.r, p.cy + p.r]
            elif isinstance(p, Poly):
                xs += [q[0] for q in p.pts]; ys += [q[1] for q in p.pts]
            elif isinstance(p, Text):
                if not p.encuadre:
                    continue
                # El ancho se estima por numero de caracteres, y el alineado
                # decide hacia donde crece: un rotulo centrado ocupa media
                # cadena a cada lado de su punto de insercion, no toda a la
                # derecha. Sin esto, el encuadre da por desbordado lo que cabe
                # y por cabido lo que se sale.
                w = len(p.s) * p.h * 0.6
                if p.halign == "center":
                    x_ini, x_fin = p.x - w / 2.0, p.x + w / 2.0
                elif p.halign == "right":
                    x_ini, x_fin = p.x - w, p.x
                else:
                    x_ini, x_fin = p.x, p.x + w
                xs += [x_ini, x_fin]; ys += [p.y, p.y + p.h]
        if not xs:
            return 0.0, 0.0, 1.0, 1.0
        return min(xs), min(ys), max(xs), max(ys)

    def merge(self, otra: "Scene", dx: float = 0.0, dy: float = 0.0, k: float = 1.0,
              h_min: float | None = None, h_max: float | None = None) -> None:
        """Inserta otra escena escalada por k y desplazada a (dx, dy).

        `h_min` y `h_max` acotan la altura del texto YA ESCALADO, en las unidades
        de la escena destino. Sin ellos, una vista a 1:40 hereda rotulos de un
        milimetro y medio: legibles en el modelo, invisibles en el papel.
        """
        def T(x, y):
            return dx + x * k, dy + y * k
        for p in otra.prims:
            if isinstance(p, Line):
                (a, b), (c, d) = T(p.x1, p.y1), T(p.x2, p.y2)
                self.prims.append(Line(a, b, c, d, p.layer))
            elif isinstance(p, Circle):
                a, b = T(p.cx, p.cy)
                self.prims.append(Circle(a, b, p.r * k, p.layer))
            elif isinstance(p, Arc):
                a, b = T(p.cx, p.cy)
                self.prims.append(Arc(a, b, p.r * k, p.a0, p.a1, p.layer))
            elif isinstance(p, Poly):
                self.prims.append(Poly([T(x, y) for x, y in p.pts], p.layer, p.closed))
            elif isinstance(p, Text):
                a, b = T(p.x, p.y)
                h = p.h * k
                if h_min is not None:
                    h = max(h, h_min)
                if h_max is not None:
                    h = min(h, h_max)
                self.prims.append(Text(a, b, h, p.s, p.layer, p.rot, p.halign,
                                       p.valign, p.encuadre))


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------
def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def to_svg(sc: Scene, ancho_mm: float = 1189.0, alto_mm: float = 841.0,
           margen_mm: float = 15.0, fondo: str = "#ffffff") -> str:
    """Renderiza la escena a SVG en milimetros, ajustada a la hoja."""
    x0, y0, x1, y1 = sc.bbox()
    w = max(x1 - x0, 1e-6)
    h = max(y1 - y0, 1e-6)
    util_w, util_h = ancho_mm - 2 * margen_mm, alto_mm - 2 * margen_mm
    k = min(util_w / w, util_h / h)
    # centrado en la hoja; la Y del SVG crece hacia abajo, se invierte
    ox = margen_mm + (util_w - w * k) / 2.0 - x0 * k
    oy = margen_mm + (util_h - h * k) / 2.0 + y1 * k

    def X(x):
        return ox + x * k

    def Y(y):
        return oy - y * k

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        'width="%.2fmm" height="%.2fmm" viewBox="0 0 %.2f %.2f">' % (
            ancho_mm, alto_mm, ancho_mm, alto_mm),
        '<title>%s</title>' % _esc(sc.nombre),
        '<rect width="%.2f" height="%.2f" fill="%s"/>' % (ancho_mm, alto_mm, fondo),
    ]
    for p in sc.prims:
        L = LAYERS.get(p.layer, LAYERS["TEXTO"])
        st = 'stroke="%s" stroke-width="%.2f" fill="none"' % (L.rgb, L.lw)
        if L.dashed:
            st += ' stroke-dasharray="3,2"'
        if isinstance(p, Line):
            out.append('<line x1="%.3f" y1="%.3f" x2="%.3f" y2="%.3f" %s/>'
                       % (X(p.x1), Y(p.y1), X(p.x2), Y(p.y2), st))
        elif isinstance(p, Circle):
            out.append('<circle cx="%.3f" cy="%.3f" r="%.3f" %s/>'
                       % (X(p.cx), Y(p.cy), p.r * k, st))
        elif isinstance(p, Arc):
            r = p.r * k
            a0, a1 = math.radians(p.a0), math.radians(p.a1)
            sx, sy = X(p.cx + p.r * math.cos(a0)), Y(p.cy + p.r * math.sin(a0))
            ex, ey = X(p.cx + p.r * math.cos(a1)), Y(p.cy + p.r * math.sin(a1))
            barrido = (p.a1 - p.a0) % 360.0
            grande = 1 if barrido > 180.0 else 0
            out.append('<path d="M %.3f %.3f A %.3f %.3f 0 %d 0 %.3f %.3f" %s/>'
                       % (sx, sy, r, r, grande, ex, ey, st))
        elif isinstance(p, Poly):
            d = " ".join("%.3f,%.3f" % (X(x), Y(y)) for x, y in p.pts)
            tag = "polygon" if p.closed else "polyline"
            out.append('<%s points="%s" %s/>' % (tag, d, st))
        elif isinstance(p, Text):
            anchor = {"left": "start", "center": "middle", "right": "end"}[p.halign]
            tr = ""
            if p.rot:
                tr = ' transform="rotate(%.2f %.3f %.3f)"' % (-p.rot, X(p.x), Y(p.y))
            out.append('<text x="%.3f" y="%.3f" font-size="%.2f" fill="%s" '
                       'font-family="Helvetica, Arial, sans-serif" '
                       'text-anchor="%s"%s>%s</text>'
                       % (X(p.x), Y(p.y), p.h * k, L.rgb, anchor, tr, _esc(p.s)))
    out.append("</svg>")
    return "\n".join(out)

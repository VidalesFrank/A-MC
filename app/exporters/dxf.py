"""Escritor de DXF R12 (ASCII) a partir de una `drawing.Scene`.

R12 a proposito: es el dialecto que abre cualquier CAD sin discusion —AutoCAD,
BricsCAD, LibreCAD, QCAD— y no necesita tablas de objetos ni clases. Con LINE,
CIRCLE, ARC, POLYLINE y TEXT se dibuja todo el despiece.

Las unidades del DXF son las de la escena: metros. El dibujante escala al
insertar, o trabaja directamente en metros.
"""
from __future__ import annotations

import unicodedata

from .drawing import LAYERS, Arc, Circle, Line, Poly, Scene, Text

# Alineaciones de TEXT en DXF
_H = {"left": 0, "center": 1, "right": 2}
_V = {"base": 0, "middle": 2, "top": 3}


def _ascii(s: str) -> str:
    """DXF R12 es ASCII: se translitera y se usan los codigos de AutoCAD."""
    s = s.replace("Ø", "%%c").replace("ø", "%%c").replace("°", "%%d").replace("±", "%%p")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("—", "-").replace("–", "-").replace("·", ".")
    s = s.replace("≤", "<=").replace("≥", ">=").replace("²", "2").replace("³", "3")
    return s.encode("ascii", "replace").decode("ascii")


class _W:
    """Acumulador de pares (codigo, valor) del formato DXF."""

    def __init__(self) -> None:
        self.out: list[str] = []

    def p(self, code: int, value) -> None:
        # Cada par ocupa dos lineas: codigo y valor. Se guardan por separado
        # para que todo el archivo use el MISMO final de linea; un DXF con
        # finales mezclados lo rechazan algunos lectores.
        self.out.append(str(code))
        self.out.append("%.6f" % value if isinstance(value, float) else str(value))

    def text(self) -> str:
        return "\r\n".join(self.out) + "\r\n"


def _tables(w: _W, sc: Scene) -> None:
    usados = sorted({p.layer for p in sc.prims} | {"0"})

    w.p(0, "SECTION"); w.p(2, "TABLES")

    # tipos de linea
    w.p(0, "TABLE"); w.p(2, "LTYPE"); w.p(70, 2)
    w.p(0, "LTYPE"); w.p(2, "CONTINUOUS"); w.p(70, 0); w.p(3, "Solida")
    w.p(72, 65); w.p(73, 0); w.p(40, 0.0)
    w.p(0, "LTYPE"); w.p(2, "DASHED"); w.p(70, 0); w.p(3, "Trazos")
    w.p(72, 65); w.p(73, 2); w.p(40, 0.75); w.p(49, 0.5); w.p(49, -0.25)
    w.p(0, "ENDTAB")

    # capas
    w.p(0, "TABLE"); w.p(2, "LAYER"); w.p(70, len(usados))
    for name in usados:
        L = LAYERS.get(name)
        w.p(0, "LAYER"); w.p(2, _ascii(name)); w.p(70, 0)
        w.p(62, L.aci if L else 7)
        w.p(6, "DASHED" if (L and L.dashed) else "CONTINUOUS")
    w.p(0, "ENDTAB")

    # estilo de texto
    w.p(0, "TABLE"); w.p(2, "STYLE"); w.p(70, 1)
    w.p(0, "STYLE"); w.p(2, "STANDARD"); w.p(70, 0); w.p(40, 0.0); w.p(41, 1.0)
    w.p(50, 0.0); w.p(71, 0); w.p(42, 2.5); w.p(3, "txt"); w.p(4, "")
    w.p(0, "ENDTAB")

    w.p(0, "ENDSEC")


def export(sc: Scene) -> str:
    """Devuelve el texto completo del DXF."""
    x0, y0, x1, y1 = sc.bbox()
    w = _W()

    w.p(0, "SECTION"); w.p(2, "HEADER")
    w.p(9, "$ACADVER"); w.p(1, "AC1009")
    w.p(9, "$INSUNITS"); w.p(70, 6)          # 6 = metros
    w.p(9, "$EXTMIN"); w.p(10, x0); w.p(20, y0); w.p(30, 0.0)
    w.p(9, "$EXTMAX"); w.p(10, x1); w.p(20, y1); w.p(30, 0.0)
    w.p(0, "ENDSEC")

    _tables(w, sc)

    w.p(0, "SECTION"); w.p(2, "ENTITIES")
    for p in sc.prims:
        cap = _ascii(p.layer)
        if isinstance(p, Line):
            w.p(0, "LINE"); w.p(8, cap)
            w.p(10, p.x1); w.p(20, p.y1); w.p(30, 0.0)
            w.p(11, p.x2); w.p(21, p.y2); w.p(31, 0.0)
        elif isinstance(p, Circle):
            w.p(0, "CIRCLE"); w.p(8, cap)
            w.p(10, p.cx); w.p(20, p.cy); w.p(30, 0.0); w.p(40, p.r)
        elif isinstance(p, Arc):
            w.p(0, "ARC"); w.p(8, cap)
            w.p(10, p.cx); w.p(20, p.cy); w.p(30, 0.0); w.p(40, p.r)
            w.p(50, p.a0); w.p(51, p.a1)
        elif isinstance(p, Poly):
            w.p(0, "POLYLINE"); w.p(8, cap); w.p(66, 1)
            w.p(70, 1 if p.closed else 0)
            w.p(10, 0.0); w.p(20, 0.0); w.p(30, 0.0)
            for x, y in p.pts:
                w.p(0, "VERTEX"); w.p(8, cap)
                w.p(10, x); w.p(20, y); w.p(30, 0.0)
            w.p(0, "SEQEND"); w.p(8, cap)
        elif isinstance(p, Text):
            w.p(0, "TEXT"); w.p(8, cap)
            w.p(10, p.x); w.p(20, p.y); w.p(30, 0.0)
            w.p(40, p.h); w.p(1, _ascii(p.s))
            if p.rot:
                w.p(50, p.rot)
            w.p(7, "STANDARD")
            ha, va = _H.get(p.halign, 0), _V.get(p.valign, 0)
            if ha or va:
                w.p(72, ha); w.p(73, va)
                # con alineacion distinta de la de por defecto manda el punto 11
                w.p(11, p.x); w.p(21, p.y); w.p(31, 0.0)
    w.p(0, "ENDSEC")
    w.p(0, "EOF")
    return w.text()


def write_file(sc: Scene, path: str) -> str:
    with open(path, "w", encoding="ascii", newline="") as fh:
        fh.write(export(sc))
    return path

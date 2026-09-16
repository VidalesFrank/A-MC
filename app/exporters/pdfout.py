"""Escritor de PDF vectorial minimo a partir de una `drawing.Scene`.

Sin dependencias: se arma un PDF 1.4 con una pagina por escena. Es suficiente
para un juego de laminas —lineas, arcos, textos— y mantiene el dibujo vectorial,
de modo que se puede ampliar sin pixelarse y se imprime a escala.
"""
from __future__ import annotations

import math

from .drawing import LAYERS, Arc, Circle, Line, Poly, Scene, Text

MM = 72.0 / 25.4          # milimetros a puntos PDF
K_BEZIER = 0.5522847498   # aproximacion de circunferencia con bezier


def _rgb(hexcolor: str) -> tuple[float, float, float]:
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _arco_bezier(cx, cy, r, a0, a1, X, Y):
    """Aproxima un arco por tramos de bezier de 90 grados o menos."""
    barrido = (a1 - a0) % 360.0
    if barrido < 1e-9:
        barrido = 360.0
    n = max(1, int(math.ceil(barrido / 90.0)))
    paso = math.radians(barrido / n)
    k = 4.0 / 3.0 * math.tan(paso / 4.0)
    ops = []
    t = math.radians(a0)
    px, py = cx + r * math.cos(t), cy + r * math.sin(t)
    ops.append("%.3f %.3f m" % (X(px), Y(py)))
    for _ in range(n):
        t2 = t + paso
        x1, y1 = cx + r * math.cos(t), cy + r * math.sin(t)
        x4, y4 = cx + r * math.cos(t2), cy + r * math.sin(t2)
        x2 = x1 - k * r * math.sin(t)
        y2 = y1 + k * r * math.cos(t)
        x3 = x4 + k * r * math.sin(t2)
        y3 = y4 - k * r * math.cos(t2)
        ops.append("%.3f %.3f %.3f %.3f %.3f %.3f c"
                   % (X(x2), Y(y2), X(x3), Y(y3), X(x4), Y(y4)))
        t = t2
    return ops


def _contenido(sc: Scene, W: float, H: float, margen_mm: float) -> bytes:
    """Flujo de contenido de una pagina, con la escena ajustada a la hoja."""
    x0, y0, x1, y1 = sc.bbox()
    w = max(x1 - x0, 1e-6)
    h = max(y1 - y0, 1e-6)
    util_w = W - 2 * margen_mm * MM
    util_h = H - 2 * margen_mm * MM
    k = min(util_w / w, util_h / h)
    ox = margen_mm * MM + (util_w - w * k) / 2.0 - x0 * k
    oy = margen_mm * MM + (util_h - h * k) / 2.0 - y0 * k

    def X(x):
        return ox + x * k

    def Y(y):
        return oy + y * k      # en PDF la Y ya crece hacia arriba

    ops = ["1 1 1 rg", "0 0 %.2f %.2f re f" % (W, H), "1 J", "1 j"]
    capa_actual = None
    for p_ in sc.prims:
        L = LAYERS.get(p_.layer, LAYERS["TEXTO"])
        if p_.layer != capa_actual:
            r, g, b = _rgb(L.rgb)
            ops.append("%.3f %.3f %.3f RG" % (r, g, b))
            ops.append("%.3f %.3f %.3f rg" % (r, g, b))
            ops.append("%.2f w" % max(L.lw * MM, 0.15))
            ops.append("[3 2] 0 d" if L.dashed else "[] 0 d")
            capa_actual = p_.layer

        if isinstance(p_, Line):
            ops.append("%.3f %.3f m %.3f %.3f l S"
                       % (X(p_.x1), Y(p_.y1), X(p_.x2), Y(p_.y2)))
        elif isinstance(p_, Circle):
            ops += _arco_bezier(p_.cx, p_.cy, p_.r, 0.0, 360.0, X, Y)
            ops.append("s")
        elif isinstance(p_, Arc):
            ops += _arco_bezier(p_.cx, p_.cy, p_.r, p_.a0, p_.a1, X, Y)
            ops.append("S")
        elif isinstance(p_, Poly):
            pts = p_.pts
            ops.append("%.3f %.3f m" % (X(pts[0][0]), Y(pts[0][1])))
            for x, y in pts[1:]:
                ops.append("%.3f %.3f l" % (X(x), Y(y)))
            ops.append("s" if p_.closed else "S")
        elif isinstance(p_, Text):
            size = max(p_.h * k, 0.5)
            # Helvetica: ancho medio ~0.52 em, suficiente para centrar etiquetas
            ancho = len(p_.s) * size * 0.52
            dx = {"left": 0.0, "center": -ancho / 2.0, "right": -ancho}[p_.halign]
            dy = {"base": 0.0, "middle": -size * 0.36, "top": -size * 0.72}[p_.valign]
            tx, ty = X(p_.x), Y(p_.y)
            ops.append("BT /F1 %.2f Tf" % size)
            if p_.rot:
                a = math.radians(p_.rot)
                ca, sa = math.cos(a), math.sin(a)
                ops.append("%.5f %.5f %.5f %.5f %.3f %.3f Tm"
                           % (ca, sa, -sa, ca,
                              tx + dx * ca - dy * sa, ty + dx * sa + dy * ca))
            else:
                ops.append("1 0 0 1 %.3f %.3f Tm" % (tx + dx, ty + dy))
            ops.append("(%s) Tj ET" % _esc(p_.s))

    return "\n".join(ops).encode("latin-1", "replace")


def export(sc: Scene, ancho_mm: float = 1189.0, alto_mm: float = 841.0,
           margen_mm: float = 15.0) -> bytes:
    """PDF de una pagina con la escena ajustada a la hoja."""
    return export_multi([sc], ancho_mm, alto_mm, margen_mm)


def export_multi(escenas, ancho_mm: float = 1189.0, alto_mm: float = 841.0,
                 margen_mm: float = 15.0) -> bytes:
    """PDF multipagina: una escena por pagina.

    Es lo que se usa para el juego de laminas, que se lee y se imprime mucho
    mejor con una lamina por hoja que con las tres en fila.
    """
    escenas = [e for e in escenas if e is not None]
    if not escenas:
        escenas = [Scene("vacia")]
    W, H = ancho_mm * MM, alto_mm * MM
    flujos = [_contenido(sc, W, H, margen_mm) for sc in escenas]
    n = len(flujos)

    # 1 catalogo, 1 nodo de paginas, n paginas, n contenidos, 1 fuente
    id_pagina = [3 + i for i in range(n)]
    id_flujo = [3 + n + i for i in range(n)]
    id_fuente = 3 + 2 * n

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        ("<< /Type /Pages /Kids [%s] /Count %d >>"
         % (" ".join("%d 0 R" % i for i in id_pagina), n)).encode("ascii"),
    ]
    for i in range(n):
        objs.append(
            ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
             "/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
             % (W, H, id_fuente, id_flujo[i])).encode("ascii"))
    for f in flujos:
        objs.append(b"<< /Length " + str(len(f)).encode("ascii")
                    + b" >>\nstream\n" + f + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                b"/Encoding /WinAnsiEncoding >>")

    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, cuerpo in enumerate(objs, start=1):
        offsets.append(len(buf))
        buf += ("%d 0 obj\n" % i).encode("ascii") + cuerpo + b"\nendobj\n"
    xref = len(buf)
    total = len(objs) + 1
    buf += ("xref\n0 %d\n" % total).encode("ascii")
    buf += b"0000000000 65535 f \n"
    for off in offsets:
        buf += ("%010d 00000 n \n" % off).encode("ascii")
    buf += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (total, xref)).encode("ascii")
    return bytes(buf)


def write_file(sc, path: str, **kw) -> str:
    """Acepta una escena o una lista de escenas."""
    datos = export_multi(sc, **kw) if isinstance(sc, (list, tuple)) else export(sc, **kw)
    with open(path, "wb") as fh:
        fh.write(datos)
    return path

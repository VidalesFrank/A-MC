"""Lamina de despiece: de la planilla de aceros a geometria dibujable.

Cada detalle se construye en su propia escena, en metros y en coordenadas
naturales del elemento, y luego se monta en la lamina a la escala que le toca.
La lamina se mide en milimetros de papel, asi que el factor de montaje es
`1000 / escala` milimetros por metro.

De aqui salen el DXF para el dibujante y el SVG/PDF para revisar.
"""
from __future__ import annotations

import datetime as _dt
import math

from ..core.params import WallProject
from ..exporters.drawing import Scene
from . import design as D
from . import rebar as R

# Alturas de texto en milimetros de papel
# Alturas de texto en milimetros de PAPEL. En una A1 por debajo de 2.5 mm no se
# lee a un brazo de distancia, y un plano se revisa de pie sobre una mesa.
H_TIT = 6.0
H_SUB = 4.0
H_TXT = 3.0
H_MIN = 2.5

# Cota de legibilidad para lo que viene de una vista escalada: el rotulo de una
# seccion a 1:40 no puede heredar el tamano que tenia en metros de modelo.
H_VISTA_MIN = 2.6
H_VISTA_MAX = 7.0


def _fmt(x: float, n: int = 2) -> str:
    return ("%%.%df" % n) % x


# --------------------------------------------------------------------------
# Planta de replanteo
# --------------------------------------------------------------------------
def planta(p: WallProject, sch: dict) -> Scene:
    """Planta de replanteo: ejes, pilas, viga cabezal y pantalla.

    Ejes horizontales del dibujo = Y del modelo (desarrollo del muro); vertical
    = X (espesor). Es la primera vista que necesita el replanteo en obra.
    """
    sc = Scene("Planta de replanteo")
    t = p.wall.thickness
    cb = p.cap_beam
    dp = p.piles.diameter
    ys = p.pile_y_positions()
    y0, y1 = p.wall.y_start, p.wall.y_end
    h = max((y1 - y0) * 0.012, 0.08)          # altura de texto en metros

    ancho = cb.width if cb.enabled else t
    # viga cabezal (o el ancho de la pantalla si no la hay)
    sc.rect(y0, -ancho / 2.0, y1 - y0, ancho, "CONCRETO")
    # pantalla, mas estrecha y centrada
    sc.rect(y0, -t / 2.0, y1 - y0, t, "CONCRETO")

    # pilas
    for i, y in enumerate(ys, start=1):
        sc.circle(y, 0.0, dp / 2.0, "CONCRETO")
        sc.circle(y, 0.0, dp / 2.0 - 0.075, "REFUERZO")
        # eje con burbuja
        sc.line(y, ancho / 2.0 + 0.15, y, ancho / 2.0 + 1.15, "EJES")
        sc.line(y, -ancho / 2.0 - 0.15, y, -ancho / 2.0 - 0.6, "EJES")
        sc.circle(y, ancho / 2.0 + 1.45, 0.30, "EJES")
        sc.text(y, ancho / 2.0 + 1.45 - h * 0.35, h, str(i), "EJES", halign="center")

    # cotas: entre ejes y total
    yc = -ancho / 2.0 - 0.7
    for a, b in zip(ys, ys[1:]):
        sc.dim_h(a, b, yc, "%s" % _fmt(b - a), h)
    sc.dim_h(y0, y1, yc - 0.6, "%s m" % _fmt(y1 - y0), h)
    sc.dim_v(-ancho / 2.0, ancho / 2.0, y0 - 0.6, "%s" % _fmt(ancho), h)
    sc.dim_v(-t / 2.0, t / 2.0, y0 - 1.2, "%s" % _fmt(t), h)

    # etiquetas
    sc.leader(ys[0], dp / 2.0, ys[0] + (y1 - y0) * 0.10, ancho / 2.0 + 0.55,
              "%d pilas %s%s m" % (len(ys), "Ø", _fmt(dp)), h)
    sc.text(y0, -ancho / 2.0 - 2.9, h, "Pantalla %s m  |  viga cabezal %s x %s m"
            % (_fmt(t), _fmt(cb.width), _fmt(cb.depth)) if cb.enabled
            else "Pantalla %s m" % _fmt(t), "TEXTO")
    # indicacion del lado del relleno
    sc.hatch_diag(y0, t / 2.0 + 0.12, y1 - y0, 0.35, (y1 - y0) / 26.0, "TERRENO")
    sc.text(y1 + 0.2, t / 2.0 + 0.2, h, "relleno", "TERRENO")
    return sc


# --------------------------------------------------------------------------
# Alzado general del muro
# --------------------------------------------------------------------------
def alzado_muro(p: WallProject, checks: dict, sch: dict) -> Scene:
    """Desarrollo completo del muro en Y, con las franjas de refuerzo.

    Es el alzado que se cota y se arma: la corona puede ser variable, las
    franjas llevan su armado y las pilas se ven bajo la viga cabezal.
    """
    sc = Scene("Alzado del muro")
    w = p.wall
    cb = p.cap_beam
    dp = p.piles.diameter
    ys = p.pile_y_positions()
    y0, y1 = w.y_start, w.y_end
    h = max((y1 - y0) * 0.012, 0.08)

    # pantalla: la corona puede ser un perfil quebrado
    n = 40
    corona = [(y0 + (y1 - y0) * k / n, w.crown_at(y0 + (y1 - y0) * k / n))
              for k in range(n + 1)]
    base = [(y0 + (y1 - y0) * k / n, w.base_at(y0 + (y1 - y0) * k / n))
            for k in range(n, -1, -1)]
    sc.poly(corona + base, "CONCRETO", closed=True)

    # viga cabezal: sigue la base del muro, que puede ir en pendiente
    inclinada = bool(w.base_profile)
    zc = cb.z if cb.z is not None else 0.0

    def _zv(y: float) -> float:
        return w.base_at(y) if inclinada else zc

    if cb.enabled:
        sup = [(yy, _zv(yy) + cb.depth / 2.0) for yy, _ in corona]
        inf = [(yy, _zv(yy) - cb.depth / 2.0) for yy, _ in reversed(corona)]
        sc.poly(sup + inf, "CONCRETO", closed=True)

    # pilas: cada una cuelga de su propia cabeza y baja hasta su punta
    cabezas = p.piles.z_tops(w, ys)
    for i, y in enumerate(ys):
        zb = p.piles.z_bot_of(i)
        zt = cabezas[i]
        sc.rect(y - dp / 2.0, zb, dp, zt - zb, "EJES")
        sc.line(y, zt + 0.4, y, zb - 0.5, "EJES")
        if p.piles.z_bots or inclinada:
            # Con pilas de distinta longitud la cota de cada punta es un dato
            # de replanteo, no un detalle: va rotulada pila por pila.
            sc.text(y, zb - 0.75, h, "L %s m" % _fmt(zt - zb),
                    "TEXTO", halign="center")
            sc.text(y, zb - 0.75 - h * 1.5, h, "N %s" % _fmt(zb),
                    "TEXTO", halign="center")

    # franjas de diseno con su armado
    fr = ((checks.get("muro") or {}).get("franjas") or {}).get("franjas") or []
    marcas = sch.get("marcas") or []
    # Las franjas son fracciones de la altura, no cotas absolutas: con la base
    # en pendiente su limite va paralelo a la base y no horizontal.
    h_dis = max(w.crown_at(yy) - w.base_at(yy) for yy, _ in corona) or 1.0
    z_base_dis = min(w.base_at(yy) for yy, _ in corona)

    def _linea_franja(z_abs: float) -> None:
        frac = (z_abs - z_base_dis) / h_dis
        pts = [(yy, w.base_at(yy) + frac * (w.crown_at(yy) - w.base_at(yy)))
               for yy, _ in corona]
        sc.poly(pts, "COTAS")

    for f in fr:
        _linea_franja(f["z_fin"])
        mv = next((m for m in marcas if m.get("franja") == f["franja"]
                   and "vertical" in m["posicion"] and "tierra" in m["posicion"]), None)
        mh = next((m for m in marcas if m.get("franja") == f["franja"]
                   and "horizontal" in m["posicion"] and "tierra" in m["posicion"]), None)
        etq = "F%d" % f["franja"]
        if mv:
            etq += "   V %s %s@%.0f" % (mv["marca"], mv["diametro"], mv["s_mm"])
        if mh:
            etq += "   H %s %s@%.0f" % (mh["marca"], mh["diametro"], mh["s_mm"])
        sc.text(y0 + 0.25, (f["z_ini"] + f["z_fin"]) / 2.0 - h * 0.35, h, etq, "TEXTO")
        sc.dim_v(f["z_ini"], f["z_fin"], y1 + 0.45, _fmt(f["z_fin"] - f["z_ini"]), h)

    # cotas generales
    sc.dim_h(y0, y1, w.z_top + 0.6, "%s m" % _fmt(y1 - y0), h)
    zb_min = p.piles.z_bot_min
    for a, b in zip(ys, ys[1:]):
        sc.dim_h(a, b, zb_min - 1.1, _fmt(b - a), h)
    sc.dim_v(zb_min, max(cabezas), y0 - 0.8,
             "pila %s m max" % _fmt(max(cabezas) - zb_min), h)
    sc.line(y0 - 0.5, w.z_top, y1 + 0.2, w.z_top, "EJES")
    sc.text(y1 + 0.3, w.z_top + 0.1, h,
            "N %s%s" % ("±" if abs(w.z_top) < 1e-9 else "", _fmt(w.z_top)), "EJES")
    if inclinada:
        # Nota explicativa: no entra en el encuadre, o la frase manda sobre el muro
        sc.text(y0, w.z_top + 1.3, h,
                "Base en pendiente %.4f m/m — la viga cabezal se desplanta en el fondo de la excavacion"
                % ((w.base_at(y0) - w.base_at(y1)) / (y1 - y0)), "TEXTO",
                encuadre=False)
    return sc


# --------------------------------------------------------------------------
# Notas generales
# --------------------------------------------------------------------------
def notas_generales(p: WallProject, sch: dict, ancho: float) -> Scene:
    """Cuadro de notas: materiales, recubrimientos, traslapos y normativa."""
    sc = Scene("Notas generales")
    fc = p.materials.concrete.fc
    fy = p.materials.rebar.fy
    hl = 3.4                                   # se ajusta abajo al ancho dado
    lineas: list[str] = [
        "1.  Normativa: ACI 318-19.  Unidades en metros salvo indicacion.",
        "2.  Concreto f'c = %.0f MPa.  Acero de refuerzo fy = %.0f MPa."
        % (fc / 1000.0, fy / 1000.0),
        "3.  Recubrimientos libres: pantalla 50 mm, viga cabezal %.0f mm, pilas %.0f mm."
        % (p.cap_beam.rebar.cover * 1000.0,
           (p.piles.zones[0].rebar.cover * 1000.0) if p.piles.zones else 75.0),
        "4.  Los ganchos son estandar segun ACI 318-19 25.3: extension 12db a 90%s "
        "y 6db (min. 75 mm) a 135%s." % ("°", "°"),
        "5.  Traslapos por solape clase B (ACI 25.5.2.1):",
    ]
    barras = sorted({m["diametro"] for m in sch.get("marcas", [])},
                    key=lambda b: int(b.lstrip("#")))
    trozos = ["%s: %.0f mm" % (b, R.solape_clase_b(b, fc, fy) * 1000.0) for b in barras]
    for i in range(0, len(trozos), 4):
        lineas.append("      " + "     ".join(trozos[i:i + 4]))
    lineas += [
        "6.  Barra comercial de %.0f m.  Las longitudes de la planilla son de corte, "
        "medidas al eje." % R.LARGO_COMERCIAL,
        "7.  El armado de la pantalla se da por franjas; ver alzado y planilla.",
        "8.  No empalmar mas del 50%s de las barras en una misma seccion." % "%",
        "9.  Verificar el replanteo de pilas antes de perforar.",
        "10. Este plano procede de un modelo de calculo; debe revisarse y firmarse.",
    ]
    # El cuadro tiene un ancho asignado en la lamina: se escoge la altura de
    # texto que llena esa columna, en vez de dejarlo a un tamano fijo que se
    # veria diminuto en una A1.
    largo = max((len(t) for t in lineas), default=40)
    hl = min(max(ancho / (largo * 0.58), 2.4), 5.0)
    for i, t in enumerate(lineas):
        sc.text(0, -i * hl * 1.55, hl, t, "TEXTO")
    return sc


# --------------------------------------------------------------------------
# Corte transversal del conjunto: pantalla + viga cabezal + pila
# --------------------------------------------------------------------------
def corte_conjunto(p: WallProject, sch: dict) -> Scene:
    """Seccion perpendicular al muro, en el eje de una pila.

    Coordenadas: X = espesor del muro, Y = cota Z del modelo.
    """
    sc = Scene("Corte transversal")
    t = p.wall.thickness
    z0, z1 = p.wall.z_base, p.wall.z_top
    cb = p.cap_beam
    dp = p.piles.diameter
    zp0, zp1 = p.piles.z_bot_min, p.piles.z_top
    cover = 0.05
    h = 0.10                                   # altura de texto en metros de modelo

    # ---- concreto --------------------------------------------------------
    zcb0 = (cb.z or 0.0) - cb.depth / 2.0
    zcb1 = (cb.z or 0.0) + cb.depth / 2.0
    if cb.enabled:
        sc.rect(-cb.width / 2.0, zcb0, cb.width, cb.depth, "CONCRETO")
    zv0 = max(z0, zcb1)
    if p.wall.is_tapered:
        # Vastago acartelado: el trapecio es el dibujo, no un adorno. El
        # dibujante necesita ver que las dos caras no son paralelas.
        tt = p.wall.thickness_top
        sc.poly([(-t / 2.0, zv0), (t / 2.0, zv0),
                 (tt / 2.0, z1), (-tt / 2.0, z1)], "CONCRETO", closed=True)
    else:
        sc.rect(-t / 2.0, zv0, t, z1 - zv0, "CONCRETO")
    sc.line(-dp / 2.0, zcb0, -dp / 2.0, zp0, "CONCRETO")
    sc.line(dp / 2.0, zcb0, dp / 2.0, zp0, "CONCRETO")
    sc.line(-dp / 2.0, zp0, dp / 2.0, zp0, "CONCRETO")

    # ---- terreno retenido ------------------------------------------------
    sc.line(t / 2.0, z1, t / 2.0 + 1.2, z1, "TERRENO")
    sc.hatch_diag(t / 2.0, z1 - 0.45, 1.2, 0.45, 0.22, "TERRENO")
    # Sobre la linea de corona: a la altura del relleno choca con la directriz
    # de la barra vertical mas alta.
    sc.text(t / 2.0 + 0.1, z1 + 0.18, h, "Relleno retenido", "TERRENO", encuadre=False)

    # ---- refuerzo de la pantalla, franja a franja ------------------------
    marcas = sch["marcas"]
    xv = t / 2.0 - cover
    for m in marcas:
        if m["elemento"] != "Pantalla" or "vertical" not in m["posicion"]:
            continue
        # "Franja 2 (z 2.00 a 4.00) - vertical, cara de tierra"
        try:
            tramo = m["posicion"].split("(z ")[1].split(")")[0]
            za, zb = (float(v) for v in tramo.split(" a "))
        except (IndexError, ValueError):
            continue
        tierra = "tierra" in m["posicion"]
        x = xv if tierra else -xv
        sc.line(x, za, x, min(zb + (0.0 if zb >= z1 else 0.6), z1), "REFUERZO")
        if za <= z0 + 1e-6:
            # gancho en la viga cabezal
            ext = R.ext_gancho(m["diametro"], 90)
            sc.line(x, za, x, zcb0 + cover, "REFUERZO")
            sc.line(x, zcb0 + cover, x - math.copysign(ext, x), zcb0 + cover, "REFUERZO")
        sc.leader(x, (za + zb) / 2.0,
                  math.copysign(t / 2.0 + 0.7, x), (za + zb) / 2.0 + 0.25,
                  "%s  %s" % (m["marca"], m["nota"].split(" (")[0]), h)

    # horizontales: puntos en las dos caras
    for m in marcas:
        if m["elemento"] != "Pantalla" or "horizontal" not in m["posicion"]:
            continue
        try:
            tramo = m["posicion"].split("(z ")[1].split(")")[0]
            za, zb = (float(v) for v in tramo.split(" a "))
            s = float(m["nota"].split("@ ")[1].split(" mm")[0]) / 1000.0
        except (IndexError, ValueError):
            continue
        x = (xv - 0.03) if "tierra" in m["posicion"] else -(xv - 0.03)
        n = max(int((zb - za) / s), 1)
        for i in range(n):
            sc.circle(x, za + (i + 0.5) * s, 0.012, "ESTRIBOS")

    # ---- viga cabezal ----------------------------------------------------
    if cb.enabled:
        cbc = cb.rebar.cover
        x1 = cb.width / 2.0 - cbc
        sc.rect(-x1, zcb0 + cbc, 2 * x1, cb.depth - 2 * cbc, "ESTRIBOS")
        vc = [m for m in marcas if m["elemento"] == "Viga cabezal"]
        for m in vc:
            if "Longitudinal superior" in m["posicion"]:
                y = zcb1 - cbc - 0.03
            elif "Longitudinal inferior" in m["posicion"]:
                y = zcb0 + cbc + 0.03
            elif "torsion" in m["posicion"]:
                y = (zcb0 + zcb1) / 2.0
            else:
                continue
            n = min(m["cantidad"], 6)
            for i in range(n):
                xx = -x1 + 0.06 + (2 * x1 - 0.12) * (i / max(n - 1, 1))
                sc.circle(xx, y, 0.022, "REFUERZO")
            sc.leader(x1, y, cb.width / 2.0 + 0.7, y + 0.1,
                      "%s  %d%s" % (m["marca"], m["cantidad"], m["diametro"]), h)
        est = next((m for m in vc if m["forma"] == "estribo_rect"), None)
        if est:
            # Solo el paso: la nota completa del estribo trae el area de torsion
            # y el paso recomendado, cuatro metros de texto que se comian la
            # escala del corte. Ese detalle esta en la seccion de viga.
            sc.leader(-x1, zcb0 + cb.depth * 0.3, -cb.width / 2.0 - 0.7,
                      zcb0 + cb.depth * 0.3 - 0.15,
                      "%s  E%s @ %.0f" % (est["marca"], est["diametro"],
                                          est.get("s_mm") or 0.0), h)

    # ---- pila ------------------------------------------------------------
    pil = [m for m in marcas if m["elemento"] == "Pila"]
    zonas = sorted(p.piles.zones, key=lambda z: -max(z.z_from, z.z_to))
    for zona in zonas:
        za, zb = min(zona.z_from, zona.z_to), max(zona.z_from, zona.z_to)
        xr = dp / 2.0 - zona.rebar.cover
        sc.line(-xr, za, -xr, zb, "REFUERZO")
        sc.line(xr, za, xr, zb, "REFUERZO")
        s = zona.rebar.tie_spacing
        n = max(int((zb - za) / s), 1)
        for i in range(n + 1):
            zz = za + i * s
            if zz <= zb:
                sc.line(-xr, zz, xr, zz, "ESTRIBOS")
        mk = next((m for m in pil if zona.name in m["posicion"]
                   and "longitudinal" in m["posicion"]), None)
        mkt = next((m for m in pil if zona.name in m["posicion"]
                    and "estribo" in m["posicion"]), None)
        etq = "%s  %d%s" % (mk["marca"], zona.rebar.num_bars, zona.rebar.bar_size) if mk else ""
        if mkt:
            etq += "   %s  E%s @ %.0f" % (mkt["marca"], zona.rebar.tie_size, s * 1000.0)
        sc.leader(xr, (za + zb) / 2.0, dp / 2.0 + 0.8, (za + zb) / 2.0 + 0.2, etq, h)
        sc.line(-dp / 2.0 - 0.3, zb, dp / 2.0 + 0.3, zb, "EJES")

    # ---- cotas -----------------------------------------------------------
    sc.dim_v(z0, z1, -t / 2.0 - 1.4, "%s m" % _fmt(z1 - z0), h)
    sc.dim_v(zp0, zcb1, -dp / 2.0 - 2.2, "pila %s m" % _fmt(zcb1 - zp0), h)
    sc.dim_h(-t / 2.0, t / 2.0, z1 + 0.6, "%.2f" % t, h)
    if cb.enabled:
        sc.dim_h(-cb.width / 2.0, cb.width / 2.0, zcb0 - 0.7, "%.2f" % cb.width, h)
    sc.line(-dp / 2.0 - 0.6, z0, dp / 2.0 + 0.6, z0, "EJES")
    sc.text(dp / 2.0 + 0.7, z0 + 0.05, h, "N ± 0.00", "EJES")
    return sc


# --------------------------------------------------------------------------
# Secciones transversales
# --------------------------------------------------------------------------
def _armados_distintos(p: WallProject) -> list[tuple[object, list[int], list[str]]]:
    """(zona representativa, pilas que lo llevan, nombres de zona) por armado.

    Dos zonas con el mismo numero de barras, diametro, zuncho y recubrimiento
    son la misma seccion en el plano aunque esten en pilas distintas: se dibujan
    una sola vez y se rotulan con las pilas a las que pertenecen.
    """
    n_pilas = len(p.pile_y_positions())
    grupos: dict[tuple, list] = {}
    for n in range(1, n_pilas + 1):
        for zona in p.piles.zones_of(n):
            r = zona.rebar
            clave = (r.num_bars, r.bar_size, r.tie_size, r.tie_spacing, r.cover)
            g = grupos.setdefault(clave, [zona, [], []])
            if n not in g[1]:
                g[1].append(n)
            base = zona.name.split("__P")[0]
            if base not in g[2]:
                g[2].append(base)
    return [(g[0], sorted(g[1]), g[2]) for g in grupos.values()]


def secciones_pila(p: WallProject, sch: dict) -> Scene:
    """Todas las secciones de pila distintas, en fila.

    Con pilas de distinta profundidad y armado propio, una sola seccion ya no
    describe la obra: el plano tiene que mostrarlas todas y decir cual es cual.
    """
    armados = _armados_distintos(p)
    if len(armados) <= 1:
        return seccion_pila(p, sch)
    sc = Scene("Secciones de pila")
    Rp = p.piles.diameter / 2.0
    paso = 2.0 * Rp + max(0.6, Rp * 0.8)
    for k, (zona, pilas, bases) in enumerate(armados):
        uno = seccion_pila(p, sch, zona=zona, pilas=pilas, bases=bases)
        sc.merge(uno, dx=k * paso, dy=0.0)
    return sc


def seccion_pila(p: WallProject, sch: dict, zona_idx: int = 0,
                 zona=None, pilas: list[int] | None = None,
                 bases: list[str] | None = None) -> Scene:
    """Seccion circular de la pila con longitudinal y zuncho."""
    sc = Scene("Seccion de pila")
    if zona is None:
        zonas = sorted(p.piles.zones, key=lambda z: -max(z.z_from, z.z_to))
        zona = zonas[min(zona_idx, len(zonas) - 1)]
    Rp = p.piles.diameter / 2.0
    rec = zona.rebar.cover
    db_t = D.bar_diam(zona.rebar.tie_size) / 1000.0
    r_tie = Rp - rec - db_t / 2.0
    r_bar = r_tie - db_t / 2.0 - D.bar_diam(zona.rebar.bar_size) / 2000.0
    h = 0.05

    sc.circle(0, 0, Rp, "CONCRETO")
    sc.circle(0, 0, r_tie, "ESTRIBOS")
    for i in range(zona.rebar.num_bars):
        a = 2 * math.pi * i / zona.rebar.num_bars
        sc.circle(r_bar * math.cos(a), r_bar * math.sin(a),
                  D.bar_diam(zona.rebar.bar_size) / 2000.0, "REFUERZO")
    sc.dim_h(-Rp, Rp, -Rp - 0.28, "%s%s m" % ("Ø", _fmt(2 * Rp)), h)
    sc.text(0, Rp + 0.16, h * 1.3,
            "PILA %s%s  —  %d%s + E%s @ %.0f mm"
            % ("Ø", _fmt(2 * Rp), zona.rebar.num_bars, zona.rebar.bar_size,
               zona.rebar.tie_size, zona.rebar.tie_spacing * 1000.0),
            "TEXTO", halign="center")
    etq = ", ".join(bases) if bases else zona.name
    if pilas:
        etq += "   pilas %s" % ", ".join(str(v) for v in pilas)
    sc.text(0, Rp + 0.05, h, "Zona %s   rec. %.0f mm" % (etq, rec * 1000.0),
            "TEXTO", halign="center")
    return sc


def seccion_viga(p: WallProject, sch: dict, checks: dict) -> Scene:
    """Seccion rectangular de la viga cabezal con estribo cerrado y torsion."""
    sc = Scene("Seccion de viga cabezal")
    cb = p.cap_beam
    b, d = cb.width, cb.depth
    rec = cb.rebar.cover
    db_t = D.bar_diam(cb.rebar.tie_size) / 1000.0
    x1 = b / 2.0 - rec - db_t / 2.0
    y1 = d / 2.0 - rec - db_t / 2.0
    h = 0.05
    tor = checks.get("torsion_viga") or {}
    vc = [m for m in sch["marcas"] if m["elemento"] == "Viga cabezal"]

    sc.rect(-b / 2.0, -d / 2.0, b, d, "CONCRETO")
    sc.rect(-x1, -y1, 2 * x1, 2 * y1, "ESTRIBOS")

    def fila(y, marca):
        if not marca:
            return
        n = marca["cantidad"] if marca["cantidad"] <= 8 else 8
        rb = D.bar_diam(marca["diametro"]) / 2000.0
        for i in range(n):
            xx = -x1 + rb + (2 * x1 - 2 * rb) * (i / max(n - 1, 1))
            sc.circle(xx, y, rb, "REFUERZO")

    sup = next((m for m in vc if "superior" in m["posicion"]), None)
    inf = next((m for m in vc if "inferior" in m["posicion"]), None)
    fila(y1 - 0.04, sup)
    fila(-y1 + 0.04, inf)

    tors = next((m for m in vc if "torsion" in m["posicion"]), None)
    if tors:
        n = max(int(tors["cantidad"]), 4)
        por_lado = max((n - 4) // 2, 1)
        rb = D.bar_diam(tors["diametro"]) / 2000.0
        for i in range(1, por_lado + 1):
            yy = -y1 + 2 * y1 * i / (por_lado + 1)
            sc.circle(-x1 + rb, yy, rb, "REFUERZO")
            sc.circle(x1 - rb, yy, rb, "REFUERZO")

    sc.dim_h(-b / 2.0, b / 2.0, -d / 2.0 - 0.22, "%s" % _fmt(b), h)
    sc.dim_v(-d / 2.0, d / 2.0, -b / 2.0 - 0.22, "%s" % _fmt(d), h)
    tit = "VIGA CABEZAL %.2f x %.2f" % (b, d)
    sc.text(0, d / 2.0 + 0.20, h * 1.3, tit, "TEXTO", halign="center")
    if tor:
        sc.text(0, d / 2.0 + 0.10, h,
                "E%s cerrado @ %.0f mm + %d%s por torsion (Al = %.0f mm2)"
                % (cb.rebar.tie_size, tor.get("s_estribo", 0.0),
                   tor.get("n_barras_torsion", 0), tor.get("barra_torsion", ""),
                   tor.get("Al", 0.0)), "TEXTO", halign="center")
    return sc


def alzado_viga(p: WallProject, sch: dict, checks: dict) -> Scene:
    """Alzado de la viga cabezal con el paso de estribos y las pilas."""
    sc = Scene("Alzado de viga cabezal")
    cb = p.cap_beam
    L = p.wall.length
    d = cb.depth
    ys = p.pile_y_positions()
    h = 0.14
    tor = checks.get("torsion_viga") or {}
    s = (tor.get("s_estribo") or cb.rebar.tie_spacing * 1000.0) / 1000.0

    sc.rect(0, -d / 2.0, L, d, "CONCRETO")
    rec = cb.rebar.cover
    sc.line(rec, d / 2.0 - rec, L - rec, d / 2.0 - rec, "REFUERZO")
    sc.line(rec, -d / 2.0 + rec, L - rec, -d / 2.0 + rec, "REFUERZO")
    n = int(L / s)
    for i in range(n + 1):
        x = rec + i * s
        if x <= L - rec:
            sc.line(x, -d / 2.0 + rec, x, d / 2.0 - rec, "ESTRIBOS")
    for y in ys:
        sc.line(y - p.piles.diameter / 2.0, -d / 2.0,
                y - p.piles.diameter / 2.0, -d / 2.0 - 0.9, "CONCRETO")
        sc.line(y + p.piles.diameter / 2.0, -d / 2.0,
                y + p.piles.diameter / 2.0, -d / 2.0 - 0.9, "CONCRETO")
        sc.line(y, -d / 2.0, y, -d / 2.0 - 1.1, "EJES")
    sc.dim_h(ys[0], ys[1] if len(ys) > 1 else L, d / 2.0 + 0.5,
             "%s m" % _fmt(ys[1] - ys[0]) if len(ys) > 1 else "", h)
    sc.dim_h(0, L, d / 2.0 + 1.1, "%s m" % _fmt(L), h)
    sc.text(L / 2.0, d / 2.0 + 1.7, h * 1.3,
            "E%s cerrado @ %.0f mm en toda la longitud"
            % (cb.rebar.tie_size, s * 1000.0), "TEXTO", halign="center")
    return sc


def detalle_arranque(p: WallProject, sch: dict, checks: dict) -> Scene:
    """Detalle del arranque de la pantalla sobre la viga cabezal.

    Es el nudo que decide el despiece: aqui anclan los verticales del muro y los
    longitudinales de la pila, y es donde el dibujante necesita ver recubrimientos,
    ganchos y longitudes de desarrollo.
    """
    sc = Scene("Detalle de arranque")
    cb = p.cap_beam
    if not cb.enabled:
        return sc
    t = p.wall.thickness
    dp = p.piles.diameter
    fc = p.materials.concrete.fc
    fy = p.materials.rebar.fy
    cbc = cb.rebar.cover
    zcb0 = (cb.z or 0.0) - cb.depth / 2.0
    zcb1 = (cb.z or 0.0) + cb.depth / 2.0
    z_top = zcb1 + 1.1
    h = 0.022

    # concreto
    sc.rect(-cb.width / 2.0, zcb0, cb.width, cb.depth, "CONCRETO")
    sc.rect(-t / 2.0, zcb1, t, z_top - zcb1, "CONCRETO")
    sc.line(-t / 2.0, z_top, t / 2.0, z_top, "EJES")
    sc.line(-dp / 2.0, zcb0, -dp / 2.0, zcb0 - 0.55, "CONCRETO")
    sc.line(dp / 2.0, zcb0, dp / 2.0, zcb0 - 0.55, "CONCRETO")

    # estribo de la viga
    x1 = cb.width / 2.0 - cbc
    sc.rect(-x1, zcb0 + cbc, 2 * x1, cb.depth - 2 * cbc, "ESTRIBOS")

    # verticales del muro con gancho de 90 en la viga
    mv = next((m for m in sch["marcas"]
               if m["elemento"] == "Pantalla" and "vertical" in m["posicion"]
               and "z 0.00" in m["posicion"]), None)
    bar_v = mv["diametro"] if mv else "#5"
    ext = R.ext_gancho(bar_v, 90)
    ldh = R.ldh_gancho(bar_v, fc, fy)
    xv = t / 2.0 - 0.05
    for signo in (1.0, -1.0):
        x = signo * xv
        sc.line(x, z_top, x, zcb0 + cbc + 0.02, "REFUERZO")
        sc.line(x, zcb0 + cbc + 0.02, x - signo * ext, zcb0 + cbc + 0.02, "REFUERZO")
    sc.leader(xv, zcb1 + 0.45, t / 2.0 + 0.62, zcb1 + 0.62,
              "%s  vertical %s, gancho 90%s" % (mv["marca"] if mv else "MV", bar_v, "\u00b0"), h)
    sc.dim_v(zcb0 + cbc + 0.02, zcb1, cb.width / 2.0 + 0.10,
             "ldh %.0f" % (ldh * 1000.0), h)

    # longitudinales de la pila
    zona = sorted(p.piles.zones, key=lambda z: -max(z.z_from, z.z_to))[0]
    bar_p = zona.rebar.bar_size
    ext_p = R.ext_gancho(bar_p, 90)
    xr = dp / 2.0 - zona.rebar.cover
    for signo in (1.0, -1.0):
        x = signo * xr
        sc.line(x, zcb0 - 0.55, x, zcb1 - cbc - 0.02, "REFUERZO")
        sc.line(x, zcb1 - cbc - 0.02, x - signo * ext_p, zcb1 - cbc - 0.02, "REFUERZO")
    mp = next((m for m in sch["marcas"]
               if m["elemento"] == "Pila" and "longitudinal" in m["posicion"]), None)
    sc.leader(-xr, zcb0 - 0.32, -cb.width / 2.0 - 0.62, zcb0 - 0.42,
              "%s  %d%s de la pila" % (mp["marca"] if mp else "P", zona.rebar.num_bars, bar_p), h)

    # cotas y notas
    sc.dim_h(-t / 2.0, t / 2.0, z_top + 0.12, "%s" % _fmt(t), h)
    sc.dim_h(-cb.width / 2.0, cb.width / 2.0, zcb0 - 0.72, "%s" % _fmt(cb.width), h)
    sc.dim_v(zcb0, zcb1, -cb.width / 2.0 - 0.14, "%s" % _fmt(cb.depth), h)
    sc.text(-cb.width / 2.0, z_top + 0.34, h * 1.2,
            "Extension del gancho %.0f mm  |  recubrimiento viga %.0f mm  |  "
            "recubrimiento muro 50 mm" % (ext * 1000.0, cbc * 1000.0), "TEXTO")
    sc.text(-cb.width / 2.0, z_top + 0.24, h,
            "El gancho debe quedar dentro del estribo de la viga; comprobar que el canto "
            "de %.0f mm aloja la ldh de %.0f mm." % (cb.depth * 1000.0, ldh * 1000.0), "TEXTO")
    return sc


# --------------------------------------------------------------------------
# Graficas para la memoria
# --------------------------------------------------------------------------
def _ejes(sc: Scene, x0, y0, x1, y1, h, titulo_x, titulo_y) -> None:
    sc.line(x0, y0, x1, y0, "TEXTO")
    sc.line(x0, y0, x0, y1, "TEXTO")
    sc.text((x0 + x1) / 2.0, y0 - h * 2.6, h, titulo_x, "TEXTO", halign="center")
    sc.text(x0 - h * 6.2, (y0 + y1) / 2.0, h, titulo_y, "TEXTO",
            rot=90.0, halign="center")


def diagrama_empujes(p: WallProject, report: dict) -> Scene:
    """Diagrama de presiones sobre la pantalla, por componentes."""
    sc = Scene("Diagrama de empujes")
    D = report.get("diagrama") or []
    if not D:
        return sc
    zs = [d["z"] for d in D]
    z0, z1 = min(zs), max(zs)
    pmax = max([d.get("total", 0.0) for d in D] + [1e-6])
    alto = max(z1 - z0, 1e-6)
    ancho = alto * 0.9                      # el dibujo se hace en "metros"
    h = alto * 0.035

    def X(v):
        return v / pmax * ancho

    def Y(z):
        return z - z0

    _ejes(sc, 0.0, 0.0, ancho * 1.12, alto, h, "presion [kPa]", "cota Z [m]")

    capas = (("suelo", "REFUERZO", "Empuje del relleno"),
             ("sobrecarga", "COTAS", "Sobrecarga"),
             ("sismo", "TERRENO", "Incremento sismico"),
             ("agua", "ESTRIBOS", "Agua"))
    ly = alto
    for clave, capa, etiqueta in capas:
        vals = [d.get(clave, 0.0) or 0.0 for d in D]
        if max(vals) <= 1e-9:
            continue
        sc.poly([(X(v), Y(d["z"])) for v, d in zip(vals, D)], capa)
        sc.line(ancho * 1.18, ly, ancho * 1.26, ly, capa)
        sc.text(ancho * 1.30, ly - h * 0.35, h, etiqueta, "TEXTO")
        ly -= h * 2.0

    sc.poly([(X(d.get("total", 0.0)), Y(d["z"])) for d in D], "TEXTO")
    sc.line(ancho * 1.18, ly, ancho * 1.26, ly, "TEXTO")
    sc.text(ancho * 1.30, ly - h * 0.35, h, "Total", "TEXTO")

    for i in range(5):
        z = z0 + (z1 - z0) * i / 4.0
        sc.text(-h * 0.5, Y(z) - h * 0.35, h, _fmt(z), "TEXTO", halign="right")
        v = max((d.get("total", 0.0) for d in D
                 if abs(d["z"] - z) < (z1 - z0) / 8.0), default=0.0)
        sc.text(X(v) + h * 0.4, Y(z) - h * 0.35, h, "%.1f" % v, "COTAS")
    return sc


def diagrama_interaccion(checks: dict, zona: str | None = None) -> Scene:
    """Curva P-M de una zona de pila con la demanda de cada elemento."""
    sc = Scene("Interaccion P-M")
    inter = checks.get("interaccion") or {}
    if not inter:
        return sc
    if zona is None:
        zona = max(inter, key=lambda k: max((d[2] for d in inter[k]["demanda"]),
                                            default=0.0))
    z = inter[zona]
    curva = z["curva"]
    dem = z["demanda"]
    mmax = max([m for _, m in curva] + [d[1] for d in dem] + [1e-6]) * 1.1
    pmin = min([pp for pp, _ in curva] + [d[0] for d in dem] + [0.0]) * 1.1
    pmax = max([pp for pp, _ in curva] + [d[0] for d in dem] + [0.0]) * 1.1
    ancho, alto = 1.0, 1.0
    h = 0.032

    def X(m):
        return m / mmax * ancho

    def Y(pp):
        return (pp - pmin) / max(pmax - pmin, 1e-9) * alto

    _ejes(sc, 0.0, 0.0, ancho * 1.05, alto, h,
          "phiMn [kN-m]", "phiPn [kN] (compresion +)")
    sc.poly([(X(m), Y(pp)) for pp, m in curva], "REFUERZO")
    if pmin < 0.0 < pmax:
        sc.line(0.0, Y(0.0), ancho * 1.05, Y(0.0), "EJES")
        sc.text(ancho * 1.06, Y(0.0) - h * 0.35, h, "P = 0", "EJES")
    for d in dem:
        sc.circle(X(d[1]), Y(d[0]), h * 0.30, "ESTRIBOS")
    peor = max(dem, key=lambda d: d[2]) if dem else None
    if peor:
        sc.circle(X(peor[1]), Y(peor[0]), h * 0.62, "TERRENO")
        sc.leader(X(peor[1]), Y(peor[0]), ancho * 0.62, alto * 0.86,
                  "Pu %.0f  Mu %.0f  D/C %.2f" % (peor[0], peor[1], peor[2]), h)
    sc.text(0.0, alto + h * 1.4, h * 1.2,
            "%s  (%d%s)" % (zona, z["num_bars"], z["bar_size"]), "TEXTO")
    for i in range(5):
        m = mmax * i / 4.0
        sc.text(X(m), -h * 1.3, h, "%.0f" % m, "TEXTO", halign="center")
        pp = pmin + (pmax - pmin) * i / 4.0
        sc.text(-h * 0.5, Y(pp) - h * 0.35, h, "%.0f" % pp, "TEXTO", halign="right")
    return sc


# --------------------------------------------------------------------------
# Formas de doblado y planilla
# --------------------------------------------------------------------------
def forma_barra(m: dict, ancho: float, alto: float) -> Scene:
    """Croquis de la forma de doblado de una marca, encajado en ancho x alto."""
    sc = Scene("forma")
    dims = m.get("dims_mm") or [m["largo_m"] * 1000.0]
    forma = m["forma"]
    hh = alto * 0.22

    if forma == "recta":
        sc.line(0, alto / 2.0, ancho, alto / 2.0, "REFUERZO")
        sc.text(ancho / 2.0, alto / 2.0 + hh * 0.4, hh, "%.0f" % dims[0],
                "COTAS", halign="center")
    elif forma == "L":
        a = ancho * 0.82
        b = min(alto * 0.6, ancho * 0.18)
        sc.poly([(0, alto * 0.82), (0, alto * 0.82 - b), (0, alto * 0.82)], "REFUERZO")
        sc.line(0, alto * 0.78, a, alto * 0.78, "REFUERZO")
        sc.line(a, alto * 0.78, a, alto * 0.78 - b, "REFUERZO")
        sc.text(a / 2.0, alto * 0.86, hh, "%.0f" % dims[0], "COTAS", halign="center")
        if len(dims) > 1:
            sc.text(a + ancho * 0.03, alto * 0.78 - b / 2.0, hh, "%.0f" % dims[1], "COTAS")
    elif forma == "U":
        a = ancho * 0.82
        b = min(alto * 0.55, ancho * 0.16)
        sc.line(0, alto * 0.75, a, alto * 0.75, "REFUERZO")
        sc.line(0, alto * 0.75, 0, alto * 0.75 - b, "REFUERZO")
        sc.line(a, alto * 0.75, a, alto * 0.75 - b, "REFUERZO")
        sc.text(a / 2.0, alto * 0.83, hh, "%.0f" % dims[0], "COTAS", halign="center")
        if len(dims) > 1:
            sc.text(a + ancho * 0.03, alto * 0.75 - b / 2.0, hh, "%.0f" % dims[1], "COTAS")
    elif forma == "estribo_rect":
        w = ancho * 0.45
        hgt = alto * 0.62
        x0, y0 = ancho * 0.08, alto * 0.18
        sc.rect(x0, y0, w, hgt, "ESTRIBOS")
        g = min(w, hgt) * 0.22
        sc.line(x0 + w, y0 + hgt, x0 + w - g, y0 + hgt - g, "ESTRIBOS")
        sc.line(x0, y0 + hgt, x0 + g, y0 + hgt - g, "ESTRIBOS")
        sc.text(x0 + w / 2.0, y0 - hh * 1.1, hh, "%.0f" % dims[0], "COTAS", halign="center")
        if len(dims) > 1:
            sc.text(x0 + w + ancho * 0.03, y0 + hgt / 2.0, hh, "%.0f" % dims[1], "COTAS")
        sc.text(x0 + w + ancho * 0.03, y0 + hgt * 0.15, hh * 0.9,
                "gancho 135%s" % "°", "COTAS")
    elif forma == "estribo_circ":
        r = min(ancho * 0.22, alto * 0.34)
        cx, cy = ancho * 0.28, alto * 0.5
        sc.circle(cx, cy, r, "ESTRIBOS")
        sc.line(cx + r * 0.7, cy + r * 0.7, cx + r * 1.25, cy + r * 1.25, "ESTRIBOS")
        sc.text(cx + r * 1.4, cy + r * 1.2, hh, "gancho 135%s" % "°", "COTAS")
        sc.text(cx, cy - r - hh * 1.2, hh, "%s%.0f" % ("Ø", dims[0]),
                "COTAS", halign="center")
    return sc


def planilla(sch: dict, ancho: float, h_fila: float = 7.0) -> Scene:
    """Tabla de despiece dibujada, con una columna de croquis de doblado."""
    sc = Scene("Planilla de aceros")
    cols = [
        ("MARCA", 0.07), ("ELEMENTO", 0.12), ("POSICION", 0.30), ("Ø", 0.05),
        ("FORMA", 0.16), ("LARGO m", 0.08), ("CANT", 0.06), ("PESO kg", 0.08),
    ]
    xs, acc = [], 0.0
    for _, frac in cols:
        xs.append(acc * ancho)
        acc += frac
    xs.append(ancho)

    filas = sch["marcas"]
    n = len(filas) + 2                      # cabecera + totales
    alto = n * h_fila
    y_top = alto

    # rejilla
    for i in range(n + 1):
        y = y_top - i * h_fila
        sc.line(0, y, ancho, y, "TABLA")
    for x in xs:
        sc.line(x, y_top - alto, x, y_top, "TABLA")

    ht = h_fila * 0.38
    for (t, _), x0, x1 in zip(cols, xs, xs[1:]):
        sc.text((x0 + x1) / 2.0, y_top - h_fila * 0.65, ht, t, "TABLA", halign="center")

    for i, m in enumerate(filas):
        y = y_top - (i + 2) * h_fila
        yc = y + h_fila * 0.35
        vals = [m["marca"], m["elemento"], m["posicion"], m["diametro"], None,
                "%.2f" % m["largo_m"], str(m["cantidad"]), "%.1f" % m["peso_total_kg"]]
        for (t, _), x0, x1, v in zip(cols, xs, xs[1:], vals):
            if v is None:
                sc.merge(forma_barra(m, (x1 - x0) * 0.94, h_fila * 0.92),
                         x0 + (x1 - x0) * 0.03, y + h_fila * 0.04, 1.0)
            elif t == "POSICION" or t == "ELEMENTO":
                sc.text(x0 + ancho * 0.004, yc, ht, v[:58], "TABLA")
            else:
                sc.text((x0 + x1) / 2.0, yc, ht, v, "TABLA", halign="center")

    y = y_top - n * h_fila
    sc.text(xs[2] + ancho * 0.004, y + h_fila * 0.35, ht,
            "TOTAL  —  concreto %.1f m3,  acero %.0f kg,  cuantia %.0f kg/m3"
            % (sch["volumen_concreto_m3"], sch["peso_total_kg"],
               sch["cuantia_kg_m3"] or 0.0), "TABLA")
    sc.text((xs[7] + xs[8]) / 2.0, y + h_fila * 0.35, ht,
            "%.0f" % sch["peso_total_kg"], "TABLA", halign="center")
    return sc


def resumen_diametros(sch: dict, ancho: float, h_fila: float = 7.0) -> Scene:
    """Resumen de peso por diametro."""
    sc = Scene("Resumen por diametro")
    cols = [("Ø", 0.22), ("db mm", 0.22), ("LARGO m", 0.28), ("PESO kg", 0.28)]
    xs, acc = [], 0.0
    for _, frac in cols:
        xs.append(acc * ancho)
        acc += frac
    xs.append(ancho)
    filas = sch["por_diametro"]
    n = len(filas) + 1
    y_top = n * h_fila
    for i in range(n + 1):
        sc.line(0, y_top - i * h_fila, ancho, y_top - i * h_fila, "TABLA")
    for x in xs:
        sc.line(x, y_top - n * h_fila, x, y_top, "TABLA")
    ht = h_fila * 0.38
    for (t, _), x0, x1 in zip(cols, xs, xs[1:]):
        sc.text((x0 + x1) / 2.0, y_top - h_fila * 0.65, ht, t, "TABLA", halign="center")
    for i, d in enumerate(filas):
        y = y_top - (i + 2) * h_fila + h_fila * 0.35
        for (t, _), x0, x1, v in zip(cols, xs, xs[1:],
                                     [d["diametro"], "%.1f" % d["db_mm"],
                                      "%.0f" % d["largo_m"], "%.0f" % d["peso_kg"]]):
            sc.text((x0 + x1) / 2.0, y, ht, v, "TABLA", halign="center")
    return sc


def cajetin(p: WallProject, sch: dict, ancho: float, alto: float,
            escala: str = "indicadas", titulo_lamina: str = "",
            numero: int = 1, total: int = 1) -> Scene:
    """Cajetin con los datos del proyecto, el numero de lamina y la revision."""
    sc = Scene("Cajetin")
    # Cuatro bandas: titulo, lamina, datos y firmas. Las cotas van en fraccion
    # de la altura y las filas de datos se reparten DENTRO de su banda, no a
    # pasos fijos desde arriba: con pasos fijos la ultima fila se comia la linea
    # de firmas y "Norma" y "Reviso" se imprimian una encima de otra.
    Y_TIT, Y_LAM, Y_DAT = 0.66, 0.44, 0.17
    sc.rect(0, 0, ancho, alto, "TABLA")
    for yy in (Y_TIT, Y_LAM, Y_DAT):
        sc.line(0, alto * yy, ancho, alto * yy, "TABLA")
    sc.line(ancho * 0.70, 0, ancho * 0.70, alto * Y_LAM, "TABLA")

    sc.text(ancho * 0.03, alto * 0.80, H_TIT, p.info.name.upper(), "TEXTO")
    sc.text(ancho * 0.03, alto * 0.70, H_TXT,
            "Muro de contencion sobre pilas con viga cabezal", "TEXTO")

    sc.text(ancho * 0.03, alto * 0.55, H_SUB, titulo_lamina or "DESPIECE", "TEXTO")
    sc.text(ancho * 0.03, alto * 0.47, H_MIN,
            "Acero %.0f kg  |  concreto %.1f m3  |  cuantia %.0f kg/m3"
            % (sch["peso_total_kg"], sch["volumen_concreto_m3"],
               sch["cuantia_kg_m3"] or 0.0), "TEXTO")

    # La matricula va en su propia fila, pegada al nombre: es lo que acompana a
    # la firma en un plano estructural y no puede quedar a interpretacion.
    izq = [("Ingeniero", p.info.engineer),
           ("Matricula", p.info.license),
           ("Cliente", p.info.client),
           ("Norma", "ACI 318-19")]
    der = [("Concreto", "f'c = %.0f MPa" % (p.materials.concrete.fc / 1000.0)),
           ("Acero", "fy = %.0f MPa" % (p.materials.rebar.fy / 1000.0)),
           ("Escalas", escala)]

    def _campo(x_lab: float, x_val: float, x_fin: float, y: float,
               k: str, v: str) -> None:
        """Rotulo y valor; si el valor falta, una linea sobre la que escribir.

        Un guion se lee como «no aplica». Lo que falta por rellenar en obra o al
        firmar necesita sitio, no una marca de descarte.
        """
        sc.text(ancho * x_lab, y, H_TXT, "%s:" % k, "TEXTO")
        if str(v).strip():
            sc.text(ancho * x_val, y, H_TXT, str(v), "TEXTO")
        else:
            sc.line(ancho * x_val, y - H_TXT * 0.35,
                    ancho * x_fin, y - H_TXT * 0.35, "TABLA")

    n = max(len(izq), len(der))
    paso = (Y_LAM - Y_DAT) / (n + 0.4)
    for i in range(n):
        y = alto * (Y_LAM - paso * (i + 0.8))
        if i < len(izq):
            _campo(0.03, 0.17, 0.35, y, *izq[i])
        if i < len(der):
            _campo(0.38, 0.50, 0.68, y, *der[i])

    # bloque de lamina y revision, a la derecha del divisor
    sc.text(ancho * 0.73, alto * (Y_LAM - paso * 0.8), H_TXT, "LAMINA", "TEXTO")
    sc.text(ancho * 0.73, alto * 0.22, H_TIT, "L-%02d / %d" % (numero, total), "TEXTO")
    sc.text(ancho * 0.73, alto * 0.08, H_MIN,
            "Rev. 0   %s" % _dt.date.today().strftime("%d/%m/%Y"), "TEXTO")

    # banda de firmas, con sitio propio bajo la ultima fila de datos
    y_firma = alto * 0.105
    y_linea = alto * 0.085
    sc.text(ancho * 0.03, y_firma, H_MIN, "Reviso:", "TEXTO")
    sc.line(ancho * 0.12, y_linea, ancho * 0.40, y_linea, "TABLA")
    sc.text(ancho * 0.43, y_firma, H_MIN, "Firma:", "TEXTO")
    sc.line(ancho * 0.51, y_linea, ancho * 0.68, y_linea, "TABLA")
    sc.text(ancho * 0.03, alto * 0.035, H_MIN,
            "Generado a partir del modelo SAP2000. Revisar y firmar antes de construir.",
            "TEXTO")
    return sc


# --------------------------------------------------------------------------
# Tabla de franjas de la pantalla
# --------------------------------------------------------------------------
def tabla_franjas(checks: dict, ancho: float, h_fila: float = 9.0) -> Scene:
    """Resumen del armado de la pantalla franja a franja."""
    sc = Scene("Franjas de la pantalla")
    fr = ((checks.get("muro") or {}).get("franjas") or {}).get("franjas") or []
    if not fr:
        return sc
    cols = [("FRANJA", 0.10), ("Z ini", 0.10), ("Z fin", 0.10),
            ("M22 dis.", 0.14), ("As vert", 0.14),
            ("M11 cara", 0.14), ("As h apoyo", 0.14), ("As h vano", 0.14)]
    xs, acc = [], 0.0
    for _, f in cols:
        xs.append(acc * ancho)
        acc += f
    xs.append(ancho)
    n = len(fr) + 1
    y_top = n * h_fila
    for i in range(n + 1):
        sc.line(0, y_top - i * h_fila, ancho, y_top - i * h_fila, "TABLA")
    for x in xs:
        sc.line(x, y_top - n * h_fila, x, y_top, "TABLA")
    ht = h_fila * 0.38
    for (t, _), x0, x1 in zip(cols, xs, xs[1:]):
        sc.text((x0 + x1) / 2.0, y_top - h_fila * 0.65, ht, t, "TABLA", halign="center")
    for i, f in enumerate(fr):
        y = y_top - (i + 2) * h_fila + h_fila * 0.35
        vals = [str(f["franja"]), _fmt(f["z_ini"]), _fmt(f["z_fin"]),
                "%.0f" % f["M22_diseno"], "%.0f" % f["vertical"]["As"],
                "%.0f" % f["M11_cara"], "%.0f" % f["horizontal_apoyo"]["As"],
                "%.0f" % f["horizontal_vano"]["As"]]
        for x0, x1, v in zip(xs, xs[1:], vals):
            sc.text((x0 + x1) / 2.0, y, ht, v, "TABLA", halign="center")
    sc.text(0, -h_fila * 0.6, ht * 0.95,
            "Momentos en kN-m/m y areas en mm2/m. M22 en la cara de la viga cabezal y "
            "M11 en la cara de la pila (ACI 318 9.4.2.1).", "TABLA")
    return sc


# --------------------------------------------------------------------------
# Lamina
# --------------------------------------------------------------------------
_ESCALAS = (5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150, 200, 250, 300, 400, 500)


def _escala_redonda(k_mm_por_m: float) -> int:
    """Escala normalizada inmediatamente por encima de la necesaria."""
    esc = 1000.0 / max(k_mm_por_m, 1e-9)
    for e in _ESCALAS:
        if e >= esc - 1e-9:
            return e
    return _ESCALAS[-1]


def _colocar(hoja: Scene, sub: Scene, x: float, y: float, w: float, h: float,
             titulo: str = "", escalar: bool = True) -> int:
    """Encaja `sub` centrado en la caja (x, y, w, h) de la hoja.

    Con `escalar` se ajusta a una escala de dibujo normalizada y se devuelve su
    denominador; si no, se inserta a tamano natural (tablas y cajetin, que ya
    vienen en milimetros de papel).
    """
    x0, y0, x1, y1 = sub.bbox()
    sw, sh = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    h_util = h - (H_TIT * 2.4 if titulo else 0.0)
    if escalar:
        esc = _escala_redonda(min(w / sw, h_util / sh))
        k = 1000.0 / esc
    else:
        esc, k = 1, 1.0
    dx = x + (w - sw * k) / 2.0 - x0 * k
    dy = y + (h_util - sh * k) / 2.0 - y0 * k
    if escalar:
        hoja.merge(sub, dx, dy, k, h_min=H_VISTA_MIN, h_max=H_VISTA_MAX)
    else:
        hoja.merge(sub, dx, dy, k)
    if titulo:
        etq = titulo if not escalar else "%s   E 1:%d" % (titulo, esc)
        # El rotulo va centrado sobre la caja: si no cabe a la altura nominal se
        # reduce, en vez de salirse del marco.
        ht = min(H_TIT, max((w - 4.0) / max(len(etq) * 0.62, 1.0), H_MIN))
        hoja.text(x + w / 2.0, y + h - ht * 1.2, ht, etq, "TEXTO", halign="center")
    return esc


# Escala de anotacion del DXF: el dibujo va 1:1 en metros y lo unico que se
# escala son las tablas y los cajetines, que nacen en milimetros de papel. A
# 1:25, un milimetro de papel son 25 mm de obra.
ESC_ANOT = 0.025


def _fila(hoja: Scene, piezas: list[tuple[str, Scene, float]],
          x: float, y_top: float, hueco: float) -> float:
    """Coloca escenas de izquierda a derecha colgadas de y_top. Devuelve el alto."""
    alto = 0.0
    for titulo, sub, k in piezas:
        if not sub.prims:
            continue
        x0, y0, x1, y1 = sub.bbox()
        w, h = (x1 - x0) * k, (y1 - y0) * k
        hoja.merge(sub, x - x0 * k, y_top - h - y0 * k, k)
        if titulo:
            ht = ESC_ANOT * H_TIT
            hoja.text(x + w / 2.0, y_top + ht * 0.6, ht, titulo, "TEXTO",
                      halign="center")
        x += w + hueco
        alto = max(alto, h)
    return alto


def modelo(p: WallProject, checks: dict, sch: dict) -> Scene:
    """Todas las vistas en METROS y a escala 1:1, para el DXF.

    Un plano compuesto es papel: sus coordenadas son milimetros de hoja y el
    muro sale a 1:20. Eso vale para revisar e imprimir, pero no para el
    dibujante, que necesita medir sobre el dibujo y montar su propio formato.
    Aqui cada vista va a tamano real y solo las tablas y el cajetin, que nacen
    en milimetros de papel, se escalan a la escala de anotacion.
    """
    hoja = Scene("Modelo en metros")
    ancho_ref = max(p.wall.y_end - p.wall.y_start, 1.0)
    hueco = max(ancho_ref * 0.12, 1.5)
    y = 0.0

    # --- vistas del conjunto, a 1:1 ---------------------------------------
    alto = _fila(hoja, [
        ("ALZADO DEL MURO", alzado_muro(p, checks, sch), 1.0),
        ("PLANTA DE REPLANTEO", planta(p, sch), 1.0),
        ("CORTE TRANSVERSAL", corte_conjunto(p, sch), 1.0),
    ], 0.0, y, hueco)
    y -= alto + hueco * 0.8

    # --- viga y detalles, a 1:1 -------------------------------------------
    piezas = [("ALZADO DE LA VIGA CABEZAL", alzado_viga(p, sch, checks), 1.0),
              ("SECCIONES DE PILA", secciones_pila(p, sch), 1.0),
              ("SECCION DE VIGA", seccion_viga(p, sch, checks), 1.0)]
    da = detalle_arranque(p, sch, checks)
    if da.prims:
        piezas.append(("DETALLE DE ARRANQUE DE LA PANTALLA", da, 1.0))
    alto = _fila(hoja, piezas, 0.0, y, hueco)
    y -= alto + hueco * 0.8

    # --- lo que es papel: tablas, notas y cajetin -------------------------
    k = ESC_ANOT
    ancho_tabla = 900.0                      # en milimetros de papel
    _fila(hoja, [
        ("PLANILLA DE ACEROS", planilla(sch, ancho_tabla, 10.0), k),
        ("RESUMEN POR DIAMETRO", resumen_diametros(sch, 220.0, 10.0), k),
    ], 0.0, y, hueco)
    y -= (len(sch.get("marcas") or []) + 3) * 10.0 * k + hueco * 0.8

    _fila(hoja, [
        ("NOTAS GENERALES", notas_generales(p, sch, 520.0), k),
        ("REFUERZO DE LA PANTALLA POR FRANJA", tabla_franjas(checks, 620.0, 10.0), k),
    ], 0.0, y, hueco)

    return hoja


def lamina(p: WallProject, checks: dict, sch: dict,
           ancho_mm: float = 1189.0, alto_mm: float = 841.0) -> Scene:
    """Las tres laminas en una sola escena, en fila.

    Es lo que se entrega en DXF y en SVG: un unico archivo con el juego
    completo, como se monta en CAD. Para el PDF se usa `laminas`, que las da
    por separado y sale multipagina.
    """
    hojas = laminas(p, checks, sch, ancho_mm, alto_mm)
    junta = Scene("Despiece — %s" % p.info.name)
    for i, (_, hoja) in enumerate(hojas):
        junta.merge(hoja, i * (ancho_mm + 40.0), 0.0, 1.0)
    return junta


def n_laminas(sch: dict, alto_mm: float = 841.0) -> int:
    """Cuantas laminas hace falta, sin dibujarlas.

    El despiece viaja con las secciones salvo que la planilla no quepa ni con
    filas de 5 mm, que es el minimo legible en una A1.
    """
    n_filas = len(sch.get("marcas") or []) + 2
    alto_planilla = n_filas * 5.0 + 46.0
    return 3 if alto_planilla > (alto_mm - 30.0) * 0.46 else 2


def laminas(p: WallProject, checks: dict, sch: dict,
            ancho_mm: float = 1189.0, alto_mm: float = 841.0) -> list[tuple[str, Scene]]:
    """Juego de laminas A1. Devuelve [(titulo, escena), ...].

    Normalmente son **dos**: la planilla de aceros ocupa alrededor de un cuarto
    de hoja incluso en modelos grandes, asi que cabe junto a las secciones. Si
    el despiece crece hasta no caber, se separa solo en una tercera lamina en
    vez de apretar las filas hasta que no se lean.
    """
    total = n_laminas(sch, alto_mm)
    separado = total == 3

    hojas = [("PLANTA Y ALZADO GENERAL",
              _lamina_1(p, checks, sch, ancho_mm, alto_mm, 1, total))]
    if separado:
        hojas.append(("SECCIONES Y DETALLES",
                      _lamina_2(p, checks, sch, ancho_mm, alto_mm, 2, total, False)))
        hojas.append(("DESPIECE DE REFUERZO",
                      _lamina_3(p, checks, sch, ancho_mm, alto_mm, 3, total)))
    else:
        hojas.append(("SECCIONES, DETALLES Y DESPIECE",
                      _lamina_2(p, checks, sch, ancho_mm, alto_mm, 2, total, True)))
    return hojas


def _marco(p: WallProject, titulo: str, ancho_mm: float, alto_mm: float):
    """Hoja con marco y las medidas utiles, comun a las tres laminas."""
    hoja = Scene(titulo)
    m = 15.0
    W, H = ancho_mm - 2 * m, alto_mm - 2 * m
    hoja.rect(m, m, W, H, "TABLA")
    return hoja, m, W, H


def _pie(hoja: Scene, p: WallProject, sch: dict, m: float, W: float, H: float,
         titulo: str, numero: int, total: int, escalas: list[int]) -> None:
    caj_w, caj_h = 300.0, 66.0
    hoja.merge(cajetin(p, sch, caj_w, caj_h,
                       ", ".join("1:%d" % e for e in escalas) or "indicadas",
                       titulo, numero, total),
               m + W - caj_w - 6.0, m + 6.0, 1.0)


def _lamina_1(p: WallProject, checks: dict, sch: dict, ancho_mm: float,
              alto_mm: float, numero: int, total: int) -> Scene:
    """Planta de replanteo, alzado general y notas."""
    titulo = "PLANTA Y ALZADO GENERAL"
    hoja, m, W, H = _marco(p, titulo, ancho_mm, alto_mm)
    # El alzado es casi cuadrado y alto (6 m de muro sobre 10 de pila), asi que
    # se lleva toda la altura de la columna izquierda; la planta, que es ancha y
    # baja, va arriba a la derecha. Asi no queda medio pliego en blanco.
    # Dos columnas. El alzado incluye las pilas, asi que con 9 m de muro y 9 de
    # pila es casi cuadrado: lo que le fija la escala es el ANCHO de su caja, no
    # la altura. Por eso la columna izquierda se lleva algo mas de la mitad de
    # la hoja; con el 42 % de antes el alzado caia a 1:30 y sobraba altura.
    escalas = []
    izq_w = W * 0.52
    der_x = m + izq_w + 18.0
    der_w = W - izq_w - 26.0
    der_y1 = m + H - 6.0                      # techo de la columna derecha
    der_y0 = m + 96.0                         # suelo, por encima del cajetin

    escalas.append(_colocar(hoja, alzado_muro(p, checks, sch),
                            m + 8.0, der_y0, izq_w, der_y1 - der_y0,
                            titulo="ALZADO DEL MURO"))

    # Alturas naturales de lo que no se escala: notas y tabla
    nt = notas_generales(p, sch, der_w)
    _, ny0, _, ny1 = nt.bbox()
    h_notas = (ny1 - ny0) + H_TIT * 2.4

    tf = tabla_franjas(checks, der_w)
    h_tabla = 0.0
    if tf.prims:
        _, fy0, _, fy1 = tf.bbox()
        h_tabla = (fy1 - fy0) + H_TIT * 2.4

    # La planta es ancha y baja: se le da solo la altura que necesita a lo ancho
    # de la columna. Darle el sobrante la dejaba flotando en medio de un hueco.
    pl = planta(p, sch)
    px0, py0, px1, py1 = pl.bbox()
    h_planta = min((py1 - py0) * der_w / max(px1 - px0, 1e-6) + H_TIT * 2.4,
                   der_y1 - der_y0 - h_notas - h_tabla - 24.0)
    h_planta = max(h_planta, H * 0.18)
    escalas.append(_colocar(hoja, pl, der_x, der_y1 - h_planta, der_w, h_planta,
                            titulo="PLANTA DE REPLANTEO"))

    # Notas y tabla cuelgan seguidas de la planta, no de los bordes de la hoja
    y_notas = der_y1 - h_planta - 14.0 - h_notas
    _colocar(hoja, nt, der_x, y_notas, der_w, h_notas,
             titulo="NOTAS GENERALES", escalar=False)

    if tf.prims:
        _colocar(hoja, tf, der_x, max(der_y0, y_notas - 14.0 - h_tabla), der_w,
                 h_tabla, titulo="REFUERZO DE LA PANTALLA POR FRANJA",
                 escalar=False)

    _pie(hoja, p, sch, m, W, H, titulo, numero, total, escalas)
    return hoja


def _lamina_2(p: WallProject, checks: dict, sch: dict, ancho_mm: float,
              alto_mm: float, numero: int, total: int,
              con_despiece: bool = True) -> Scene:
    """Secciones, detalles y —si cabe— la planilla de aceros."""
    titulo = "SECCIONES, DETALLES Y DESPIECE" if con_despiece else "SECCIONES Y DETALLES"
    hoja, m, W, H = _marco(p, titulo, ancho_mm, alto_mm)
    escalas = []

    # La banda inferior es para el despiece; sin el, los dibujos ocupan todo.
    # La banda se ajusta a lo que ocupa la planilla, para no dejar medio pliego
    # en blanco cuando el despiece es corto.
    banda = 0.0
    if con_despiece:
        _, qy0, _, qy1 = planilla(sch, (W - 16.0) * 0.74, 10.0).bbox()
        banda = min(H * 0.50, max(150.0, (qy1 - qy0) + H_TIT * 2.4 + 12.0))
    y_dib = m + (78.0 + banda + 8.0 if con_despiece else 80.0)
    alto_dib = m + H - 6.0 - y_dib

    # El corte transversal parece estrecho pero no lo es: sus directrices salen
    # a lado y lado del muro y es el ANCHO lo que le fija la escala. Con una
    # columna angosta cae a 1:50 y deja de leerse.
    izq_w = W * 0.26
    x2 = m + izq_w + 16.0
    w2 = W - izq_w - 24.0

    # Vistas de detalle: se reparten el ancho en proporcion a lo que ocupan, con
    # un minimo para que quepa su rotulo.
    vistas = [("SECCIONES DE PILA", secciones_pila(p, sch)),
              ("SECCION DE VIGA", seccion_viga(p, sch, checks))]
    da = detalle_arranque(p, sch, checks)
    if da.prims:
        vistas.append(("DETALLE DE ARRANQUE DE LA PANTALLA", da))

    formas = []
    for _, sc in vistas:
        bx0, by0, bx1, by1 = sc.bbox()
        formas.append((max(bx1 - bx0, 1e-6), max(by1 - by0, 1e-6)))
    anchos = [max(a / b, 0.25) for a, b in formas]
    hueco = w2 - 8.0 * (len(vistas) - 1)
    minimos = [len(tit) * H_MIN * 0.62 + 8.0 for tit, _ in vistas]
    if sum(minimos) < hueco:
        libre = hueco - sum(minimos)
        total_a = sum(anchos)
        reparto = [mn + libre * a / total_a for mn, a in zip(minimos, anchos)]
    else:
        k = hueco / sum(minimos)
        reparto = [mn * k for mn in minimos]

    # La fila de detalles solo ocupa lo que necesita: unas secciones de 1.20 m
    # centradas en media hoja son media hoja en blanco. Lo que sobra se lo lleva
    # el alzado de la viga, que es lo que gana con mas altura.
    necesita = max((by / bx) * wv for (bx, by), wv in zip(formas, reparto))
    h3 = min(necesita + H_TIT * 2.4 + 6.0, alto_dib * 0.62)
    alto_alz = alto_dib - h3 - 8.0

    escalas.append(_colocar(hoja, corte_conjunto(p, sch),
                            m + 8.0, y_dib, izq_w, alto_dib,
                            titulo="CORTE TRANSVERSAL"))
    escalas.append(_colocar(hoja, alzado_viga(p, sch, checks),
                            x2, m + H - 6.0 - alto_alz, w2, alto_alz,
                            titulo="ALZADO DE LA VIGA CABEZAL"))

    x = x2
    for (tit, sc), wv in zip(vistas, reparto):
        escalas.append(_colocar(hoja, sc, x, y_dib, wv, h3, titulo=tit))
        x += wv + 8.0

    if con_despiece:
        _bloque_despiece(hoja, p, sch, m + 8.0, m + 78.0, W - 16.0, banda)

    _pie(hoja, p, sch, m, W, H, titulo, numero, total, escalas)
    return hoja


def _bloque_despiece(hoja: Scene, p: WallProject, sch: dict,
                     x: float, y: float, w: float, h: float) -> None:
    """Planilla de aceros con el resumen y los materiales al lado."""
    col_w = w * 0.74
    n_filas = len(sch["marcas"]) + 2
    h_fila = min(10.0, max(5.0, (h - H_TIT * 2.4) / max(n_filas, 1)))
    pl = planilla(sch, col_w, h_fila)
    px0, py0, px1, py1 = pl.bbox()
    _colocar(hoja, pl, x, y + h - (py1 - py0) - H_TIT * 2.4, col_w,
             (py1 - py0) + H_TIT * 2.4, titulo="PLANILLA DE ACEROS", escalar=False)

    rx = x + col_w + 16.0
    rw = w - col_w - 20.0
    rd = resumen_diametros(sch, rw * 0.92, h_fila)
    ax0, ay0, ax1, ay1 = rd.bbox()
    _colocar(hoja, rd, rx, y + h - (ay1 - ay0) - H_TIT * 2.4, rw * 0.92,
             (ay1 - ay0) + H_TIT * 2.4, titulo="RESUMEN POR DIAMETRO", escalar=False)

    yy = y + h - (ay1 - ay0) - H_TIT * 2.4 - 12.0
    hoja.text(rx, yy, H_SUB, "MATERIALES", "TEXTO")
    filas = [("Acero total", "%.0f kg" % sch["peso_total_kg"]),
             ("Concreto", "%.1f m3" % sch["volumen_concreto_m3"]),
             ("Cuantia", "%.0f kg/m3" % (sch["cuantia_kg_m3"] or 0.0))]
    filas += [("  " + k, "%.0f kg" % v) for k, v in sch["por_elemento"].items()]
    for k, v in filas:
        yy -= 8.5
        hoja.text(rx, yy, H_TXT, k, "TEXTO")
        hoja.text(rx + rw * 0.58, yy, H_TXT, v, "TEXTO")
    hoja.text(x, y - 4.0, H_MIN, sch["nota"], "TEXTO")


def _lamina_3(p: WallProject, checks: dict, sch: dict, ancho_mm: float,
              alto_mm: float, numero: int, total: int) -> Scene:
    """Planilla de aceros a hoja completa, cuando no cabe con las secciones."""
    titulo = "DESPIECE DE REFUERZO"
    hoja, m, W, H = _marco(p, titulo, ancho_mm, alto_mm)
    _bloque_despiece(hoja, p, sch, m + 8.0, m + 80.0, W - 16.0, H - 92.0)
    _pie(hoja, p, sch, m, W, H, titulo, numero, total, [])
    return hoja

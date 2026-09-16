"""Dimensionamiento del refuerzo a partir de las solicitaciones ya extraidas.

El resto de la herramienta *verifica* un armado propuesto; esto lo *busca*. Se
apoya en las mismas comprobaciones de `design.py`, de modo que lo que aqui sale
pasa despues la verificacion sin sorpresas.

No hace falta volver a correr SAP entre iteraciones: la rigidez del modelo sale
de la seccion bruta, no del refuerzo, asi que cambiar barras no cambia las
solicitaciones.
"""
from __future__ import annotations

import math

from ..core import model as M
from ..core.params import PileZone, WallProject
from . import design as D
from . import extract

# Escalera de tanteo: primero mas barras del mismo diametro, que es lo que
# prefiere una pila excavada a mano, y solo despues se sube de diametro.
BARRAS = ("#6", "#7", "#8", "#9", "#10", "#11")
RHO_MIN = 0.005          # ACI 318-19 10.6.1.1 para elementos a compresion
RHO_MAX = 0.040          # limite practico de armado y de vaciado


def _rho(n: int, bar: str, diam: float) -> float:
    return n * D.bar_area(bar) / (math.pi * (diam * 1000.0) ** 2 / 4.0)


def _candidatos(diam: float) -> list[tuple[int, str]]:
    """(numero de barras, diametro) ordenados por area, dentro de los limites."""
    out = []
    for bar in BARRAS:
        # Mas de 30 barras en una pila excavada a mano no se coloca ni se vibra:
        # a partir de ahi hay que subir de diametro.
        for n in range(6, 31, 2):
            r = _rho(n, bar, diam)
            if RHO_MIN <= r <= RHO_MAX:
                out.append((n * D.bar_area(bar), n, bar))
    out.sort()
    return [(n, b) for _, n, b in out]


# --------------------------------------------------------------------------
# Demanda pila a pila
# --------------------------------------------------------------------------
def demanda_por_pila(p: WallProject, model: M.StructuralModel,
                     pile_rows: list[dict]) -> dict[tuple[int, str], list[tuple[float, float, float]]]:
    """(numero de pila, nombre de zona) -> [(Pu, Mu, Vu), ...] de sus elementos."""
    env = extract.frame_envelopes(pile_rows, model)
    ids = {str(i) for i in model.group_element_ids("PILAS", "Frame")}
    idx = extract.pile_index_map(model)
    out: dict[tuple[int, str], list[tuple[float, float, float]]] = {}
    for label, ef in env.items():
        if ids and label not in ids:
            continue
        n = idx.get(label, 1)
        z = ef.z if ef.z is not None else p.piles.z_top
        zona = p.piles.zone_at(n, z)
        Pu = -ef.P.min if ef.P.min != float("inf") else 0.0
        Mu = max(ef.M2.abs_max, ef.M3.abs_max)
        Vu = max(ef.V2.abs_max, ef.V3.abs_max)
        out.setdefault((n, zona.name), []).append((Pu, Mu, Vu))
    return out


def separar_zonas_por_pila(p: WallProject) -> None:
    """Da a cada pila su propio juego de zonas, recortado en su punta.

    A partir de aqui cada pila se arma para lo suyo. En un muro de altura
    variable eso es la diferencia entre armar las cinco como la peor y armar
    cada una como le toca.
    """
    ys = p.pile_y_positions()
    cabezas = p.piles.z_tops(p.wall, ys)
    nuevas: list[PileZone] = []
    for i in range(len(ys)):
        n = i + 1
        z_top, z_bot = cabezas[i], p.piles.z_bot_of(i)
        for plantilla in p.piles.zones_of(n):
            hi = min(plantilla.z_hi, z_top)
            lo = max(plantilla.z_lo, z_bot)
            if hi - lo <= 1e-6:
                continue                     # la zona no toca esta pila
            base = plantilla.name.split("__P")[0]
            nuevas.append(PileZone(
                name="%s__P%d" % (base, n), z_from=hi, z_to=lo,
                rebar=plantilla.rebar.model_copy(deep=True), piles=[n],
            ))
    if nuevas:
        p.piles.zones = nuevas


# --------------------------------------------------------------------------
# Dimensionamiento
# --------------------------------------------------------------------------
def dimensionar_pilas(p: WallProject, model: M.StructuralModel,
                      pile_rows: list[dict], objetivo: float = 1.0,
                      pisos: dict[int, float] | None = None,
                      por_pila: bool = False) -> list[str]:
    """Ajusta el refuerzo de las zonas de pila hasta cubrir su demanda.

    Con `por_pila` cada pila recibe primero su propio juego de zonas y se arma
    para su demanda; sin el, todas comparten zonas y cada una se arma para la
    envolvente del grupo.

    `pisos` impone un momento minimo **por pila**, aplicado a su zona superior.
    Sirve para no quedarse por debajo de lo que exige el estudio geotecnico: el
    mecanismo de pila larga de Broms suele pedir mas que el modelo elastico
    sobre resortes, y esa demanda la fija el geotecnista.

    Devuelve una linea por zona describiendo lo que se adopto, y modifica
    `p.piles.zones` en sitio.
    """
    if por_pila:
        separar_zonas_por_pila(p)

    fc = p.materials.concrete.fc
    fy = p.materials.rebar.fy
    dem = demanda_por_pila(p, model, pile_rows)
    n_pilas = len(p.pile_y_positions())

    notas: list[str] = []
    for zona in sorted(p.piles.zones, key=lambda z: (z.piles or [0])[0] * 1000.0 - z.z_hi):
        aplica = [n for n in range(1, n_pilas + 1) if zona.applies_to(n)]
        casos = [c for n in aplica for c in dem.get((n, zona.name), [])]
        if not casos:
            continue

        # Piso de momento: se combina con el axial mas bajo de la zona, que es
        # la pareja P-M que de verdad hay que cubrir en una seccion circular.
        for n in aplica:
            piso = (pisos or {}).get(n)
            if piso and zona is (p.piles.zones_of(n) or [None])[0]:
                casos = casos + [(min(c[0] for c in casos), piso, 0.0)]

        n_bar, bar, dc = _elegir(p, zona, casos, fc, fy, objetivo, notas)
        zona.rebar.num_bars, zona.rebar.bar_size = n_bar, bar
        zona.rebar.tie_spacing = _paso_estribo(p, zona, max(v for _, _, v in casos), fc, fy)
        notas.append("%-22s pilas %-7s %d%s (rho %.2f %%), D/C %.2f; %s @ %.0f mm"
                     % (zona.name, ",".join(str(v) for v in aplica) if zona.piles else "todas",
                        n_bar, bar, _rho(n_bar, bar, p.piles.diameter) * 100.0, dc,
                        zona.rebar.tie_size, zona.rebar.tie_spacing * 1000.0))
    return notas


def _elegir(p: WallProject, zona: PileZone, casos, fc: float, fy: float,
            objetivo: float, notas: list[str]) -> tuple[int, str, float]:
    """Primera combinacion de la escalera que cubre la demanda de la zona."""
    opciones = _candidatos(p.piles.diameter)

    def _dc(n: int, bar: str) -> float:
        col = D.CircularColumn(D=p.piles.diameter, cover=zona.rebar.cover,
                               num_bars=n, bar_size=bar,
                               tie_size=zona.rebar.tie_size, fc=fc, fy=fy)
        return max(D.check_circular_column(col, Pu, Mu).ratio for Pu, Mu, _ in casos)

    for i, (n, bar) in enumerate(opciones):
        if _dc(n, bar) > objetivo:
            continue
        # Entre opciones de area parecida se elige la que de verdad se arma: ni
        # 6 barras gordas ni 26 finas, sino del orden de 10 a 20 repartidas por
        # el perimetro. Se comprueba que la elegida siga cumpliendo, porque la
        # capacidad de una seccion circular no depende solo del area.
        As0 = n * D.bar_area(bar)
        cercanas = [(m, b) for m, b in opciones
                    if As0 <= m * D.bar_area(b) <= As0 * 1.10]
        for m, b in sorted(cercanas, key=lambda v: (0 if 10 <= v[0] <= 20 else 1,
                                                    abs(v[0] - 14))):
            if _dc(m, b) <= objetivo:
                return m, b, _dc(m, b)
        return n, bar, _dc(n, bar)

    n, bar = opciones[-1]
    dc = _dc(n, bar)
    notas.append("%s: ni con %d%s (rho %.2f %%) se llega; D/C %.2f. "
                 "Hace falta mas diametro de pila o mas pilas."
                 % (zona.name, n, bar, _rho(n, bar, p.piles.diameter) * 100.0, dc))
    return n, bar, dc


def _paso_estribo(p: WallProject, zona: PileZone, Vu: float,
                  fc: float, fy: float) -> float:
    """Paso de zuncho que cubre Vu, en pasos de 25 mm y dentro de los maximos."""
    col = D.CircularColumn(D=p.piles.diameter, cover=zona.rebar.cover,
                           num_bars=zona.rebar.num_bars, bar_size=zona.rebar.bar_size,
                           tie_size=zona.rebar.tie_size, fc=fc, fy=fy)
    # Maximos de confinamiento: 16 db longitudinales, 48 db del zuncho, D/2
    s_max = min(16.0 * D.bar_diam(zona.rebar.bar_size) / 1000.0,
                48.0 * D.bar_diam(zona.rebar.tie_size) / 1000.0,
                p.piles.diameter / 2.0, 0.30)
    s = math.floor(s_max / 0.025) * 0.025
    while s > 0.05:
        if D.shear_circular(Vu, col, s).ok:
            return s
        s -= 0.025
    return 0.05

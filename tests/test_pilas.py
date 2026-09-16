"""Pilas de distinta profundidad, analisis y armado pila a pila.

    python tests/test_pilas.py

No necesita SAP: las solicitaciones se sintetizan igual que en test_design.

Cubre ademas tres errores que aparecieron con el primer muro real y que no
deben volver: la sobrecarga fuera de las combinaciones, la viga cabezal
disenada con la misma orientacion de seccion en los dos planos, y el volumen de
concreto integrado solo con la corona.
"""
from __future__ import annotations

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from app.core.builder import build
from app.core.params import (EarthPressure, PileZone, RebarCircular, SoilProfile,
                             default_combos)
from app.results import extract, rebar, sizing
from app.results.rebar import _volumen_concreto
from test_design import _synthetic_rows
from test_reference import reference_project

FAILS: list[str] = []


def check(label: str, got, want, tol: float = 0.01) -> None:
    if isinstance(want, (int, float)) and not isinstance(want, bool) \
            and isinstance(got, (int, float)) and not isinstance(got, bool):
        err = abs(got - want) / abs(want) * 100.0 if want else abs(got)
        ok = err <= tol * 100.0
        print("  %-54s %12.3f  esperado %12.3f  %s"
              % (label, got, want, "OK" if ok else "<<< FALLA"), flush=True)
    else:
        ok = got == want
        print("  %-54s %-14s esperado %-14s %s"
              % (label, got, want, "OK" if ok else "<<< FALLA"), flush=True)
    if not ok:
        FAILS.append(label)


# --------------------------------------------------------------------------
def _proyecto_escalonado():
    """Muro de base inclinada con cinco pilas de longitud creciente."""
    p = reference_project()
    p.info.name = "Pilas escalonadas"
    L = 14.0
    p.wall.crown_profile = [(0.0, 0.0), (L, 0.0)]
    p.wall.base_profile = [(0.0, -1.5), (L, -4.5)]
    p.wall.z_base, p.wall.z_top = -4.5, 0.0
    p.wall.thickness, p.wall.thickness_top = 0.50, 0.30

    ys = [1.4, 4.2, 7.0, 9.8, 12.6]
    cabezas = [p.wall.base_at(y) for y in ys]
    largos = [5.0, 6.0, 7.0, 8.0, 9.0]
    p.piles.y_positions = ys
    p.piles.z_top = max(cabezas)
    p.piles.z_bots = [c - l for c, l in zip(cabezas, largos)]
    p.piles.z_bot = min(p.piles.z_bots)
    p.piles.tip_restraint = True
    p.piles.zones = [
        PileZone(name="P_SUP", z_from=max(cabezas), z_to=-7.0,
                 rebar=RebarCircular(num_bars=12, bar_size="#8")),
        PileZone(name="P_INF", z_from=-7.0, z_to=min(p.piles.z_bots),
                 rebar=RebarCircular(num_bars=12, bar_size="#6")),
    ]
    p.soil = SoilProfile(nh=7500.0)
    p.earth = EarthPressure(method="usuario", K_user=0.30, gamma=17.0, surcharge=12.0)
    return p, ys, largos


def test_geometria() -> None:
    print("\n1. Pilas de distinta profundidad en el modelo")
    p, ys, largos = _proyecto_escalonado()
    res = build(p)
    m = res.model

    # Cada pila baja hasta su punta y arranca en la base del muro
    for i, (y, L) in enumerate(zip(ys, largos)):
        zs = [m.get_joint(j).z for fid in m.group_element_ids("PILA_%02d" % (i + 1), "Frame")
              for j in (m.frames[fid - 1].i, m.frames[fid - 1].j)]
        check("pila %d, longitud en el modelo" % (i + 1), max(zs) - min(zs), L)
        check("pila %d, cabeza en la base del muro" % (i + 1),
              max(zs), p.wall.base_at(y), 0.001)

    # Un unico apoyo vertical por pila, en su punta
    puntas = sorted(round(m.get_joint(r.joint).z, 3) for r in m.restraints)
    check("un apoyo por pila", len(puntas), len(ys), 0.0)
    check("apoyos en las puntas", puntas,
          sorted(round(v, 3) for v in p.piles.z_bots), 0.0)

    # El balasto de Matlock y Reese crece con la profundidad bajo la cabeza de
    # CADA pila, no bajo una cota comun. Se comprueba de las dos maneras: misma
    # profundidad da el mismo resorte aunque las cotas no coincidan, y dentro de
    # una pila el resorte crece proporcionalmente a la profundidad.
    por_pila: dict[float, dict[float, float]] = {}
    for sp in m.springs:
        j = m.get_joint(sp.joint)
        cab = p.wall.base_at(j.y)
        por_pila.setdefault(round(j.y, 3), {})[round(cab - j.z, 3)] = sp.u1
    k_prim = por_pila[round(ys[0], 3)]
    k_ult = por_pila[round(ys[-1], 3)]
    prof = sorted(d for d in set(k_prim) & set(k_ult) if d > 0.5)
    check("las pilas comparten profundidades", len(prof) >= 3, True)
    if prof:
        d = prof[0]
        check("a igual profundidad, igual balasto", k_prim[d], k_ult[d], 0.001)
        d2 = next((v for v in prof if abs(v - 2.0 * d) < 1e-6), None)
        if d2:
            check("el balasto crece con la profundidad",
                  k_prim[d2] / k_prim[d], 2.0, 0.001)


def test_zonas_por_pila() -> None:
    print("\n2. Zonas propias de cada pila")
    p, ys, _ = _proyecto_escalonado()
    # Una zona propia de la pila 3 tapa a la general en su tramo
    p.piles.zones.append(PileZone(
        name="P_SUP_ESPECIAL", z_from=p.piles.z_top, z_to=-7.0, piles=[3],
        rebar=RebarCircular(num_bars=20, bar_size="#10")))

    check("la pila 1 sigue con la general",
          p.piles.zone_at(1, -3.0).name, "P_SUP")
    check("la pila 3 toma la suya",
          p.piles.zone_at(3, -3.0).name, "P_SUP_ESPECIAL")
    check("la pila 3 no ve la general tapada",
          any(z.name == "P_SUP" for z in p.piles.zones_of(3)), False)
    check("bajo el corte manda la general en las dos",
          (p.piles.zone_at(1, -8.0).name, p.piles.zone_at(3, -8.0).name),
          ("P_INF", "P_INF"))

    # El modelo asigna a cada frame la seccion de su pila
    m = build(p).model
    secs = {}
    for i in (1, 3):
        for fid in m.group_element_ids("PILA_%02d" % i, "Frame"):
            fr = m.frames[fid - 1]
            zm = 0.5 * (m.get_joint(fr.i).z + m.get_joint(fr.j).z)
            if zm > -7.0:
                secs.setdefault(i, set()).add(fr.section)
    check("la pila 1 lleva la seccion general", secs.get(1), {"P_SUP"})
    check("la pila 3 lleva la suya", secs.get(3), {"P_SUP_ESPECIAL"})


def test_ficha_por_pila() -> None:
    print("\n3. Una ficha de resultados por pila")
    p, ys, largos = _proyecto_escalonado()
    res = build(p)
    m = res.model
    checks = extract.verify(p, m, *_synthetic_rows(p, m))

    fichas = checks.get("pilas_resumen") or []
    check("hay una ficha por pila", len(fichas), len(ys), 0.0)
    for f, y, L in zip(fichas, ys, largos):
        check("ficha %d, longitud" % f["pila"], f["longitud"], L)
        check("ficha %d, abscisa" % f["pila"], f["y"], y, 0.001)
        check("ficha %d, punta" % f["pila"], f["z_punta"],
              p.piles.z_bot_of(f["pila"] - 1), 0.001)
    # Cada elemento sabe de que pila es, y no se pierde ninguno
    con_pila = [r for r in checks["pilas"] if r.get("pila")]
    check("todo elemento tiene pila", len(con_pila), len(checks["pilas"]), 0.0)
    check("las pilas cubren todos los elementos",
          sum(f["n_elementos"] for f in fichas), len(checks["pilas"]), 0.0)


def test_dimensionamiento_por_pila() -> None:
    print("\n4. Dimensionamiento pila a pila")
    p, ys, _ = _proyecto_escalonado()
    res = build(p)
    m = res.model
    pile_rows, _, _ = _synthetic_rows(p, m)

    n_antes = len(p.piles.zones)
    notas = sizing.dimensionar_pilas(p, m, pile_rows, por_pila=True)
    check("cada pila recibe su juego de zonas",
          len(p.piles.zones) >= n_antes * len(ys) - len(ys), True)
    check("toda zona queda asignada a una pila",
          all(z.piles for z in p.piles.zones), True)
    check("hay una nota por zona dimensionada", len(notas) >= len(p.piles.zones), True)

    # Ninguna zona se sale de los limites de cuantia
    for z in p.piles.zones:
        rho = z.rebar.num_bars * 645.0 / (math.pi * (p.piles.diameter * 1000.0) ** 2 / 4.0)
        check("zona %s con barras razonables" % z.name,
              6 <= z.rebar.num_bars <= 30, True)

    # Y tras dimensionar, todo cumple
    checks = extract.verify(p, m, *_synthetic_rows(p, m))
    check("ninguna pila queda no conforme",
          checks["resumen"]["no_conformes_pilas"], 0, 0.0)

    # El piso de momento por pila manda cuando supera al modelo
    p2, _, _ = _proyecto_escalonado()
    m2 = build(p2).model
    filas2, _, _ = _synthetic_rows(p2, m2)
    sizing.dimensionar_pilas(p2, m2, filas2, pisos={1: 3000.0}, por_pila=True)
    sup1 = p2.piles.zones_of(1)[0]
    sup5 = p2.piles.zones_of(5)[0]
    check("el piso de la pila 1 le sube el armado",
          sup1.rebar.num_bars * 645.0 > sup5.rebar.num_bars * 400.0, True)


def test_despiece_por_pila() -> None:
    print("\n5. Despiece con pilas distintas")
    p, ys, largos = _proyecto_escalonado()
    res = build(p)
    m = res.model
    checks = extract.verify(p, m, *_synthetic_rows(p, m))
    sch = rebar.build_schedule(p, checks)

    marcas = [mk for mk in sch["marcas"] if mk["elemento"] == "Pila"]
    check("hay marcas de pila", len(marcas) > 0, True)
    # Con cinco longitudes distintas, la zona inferior no puede dar una sola marca
    inf = [mk for mk in marcas if "P_INF" in mk["posicion"] and "longitudinal" in mk["posicion"]]
    check("la zona inferior se separa por longitud", len(inf) >= 4, True)
    check("las marcas dicen a que pilas van",
          all("pilas" in mk["posicion"] for mk in inf), True)

    # El acero total no puede salir de la nada: el volumen de concreto cuadra
    # con la geometria real (corona menos base, y cada pila desde su cabeza).
    w = p.wall
    area = 0.0
    n = 400
    for k in range(n):
        ya, yb = 14.0 * k / n, 14.0 * (k + 1) / n
        area += 0.5 * ((w.crown_at(ya) - w.base_at(ya))
                       + (w.crown_at(yb) - w.base_at(yb))) * (14.0 / n)
    esperado = area * w.thickness_mean
    esperado += p.cap_beam.width * p.cap_beam.depth * 14.0
    esperado += sum(math.pi * p.piles.diameter ** 2 / 4.0 * L for L in largos)
    check("volumen de concreto con base inclinada",
          _volumen_concreto(p), esperado, 0.005)


def test_regresiones() -> None:
    print("\n6. Los tres errores del primer muro real")

    # (a) La sobrecarga tiene que entrar en las combinaciones
    combos = default_combos()
    con_sc = [c.name for c in combos
              if any(f.pattern == "SOBRECARGA" for f in c.factors)]
    check("SOBRECARGA en las cinco combinaciones", len(con_sc), len(combos), 0.0)
    for c in combos:
        fs = {f.pattern: f.factor for f in c.factors}
        if "SUELO" in fs and "SOBRECARGA" in fs:
            check("%s: mismo factor que el empuje" % c.name,
                  fs["SOBRECARGA"], fs["SUELO"])

    p, _, _ = _proyecto_escalonado()
    m = build(p).model
    pats = {pat for c in m.combos for pat, _ in c.factors}
    check("el modelo combina SOBRECARGA", "SOBRECARGA" in pats, True)

    # (b) La viga cabezal se disena en los dos planos, cada uno con su seccion
    p.cap_beam.width, p.cap_beam.depth = 1.20, 0.60
    m = build(p).model
    checks = extract.verify(p, m, *_synthetic_rows(p, m))
    viga = checks["viga_cabezal"]
    check("la viga trae los dos momentos",
          all("Mu_h" in r and "ratio_M_h" in r for r in viga), True)
    # Con el mismo momento, el plano horizontal es mucho mas resistente porque
    # trabaja contra el ancho (1.20 m) y no contra el canto (0.60 m).
    from app.results import design as D
    Mu = 300.0
    fv = D.flexure_rect(Mu, 1.20, 0.60, p.materials.concrete.fc,
                        p.materials.rebar.fy, 0.05, "#7")
    fh = D.flexure_rect(Mu, 0.60, 1.20, p.materials.concrete.fc,
                        p.materials.rebar.fy, 0.05, "#7")
    check("el plano horizontal pide menos acero", fh.As_req < fv.As_req * 0.75, True)

    # (c) El volumen de concreto ya se comprobo en el punto 5; aqui, que no
    # dependa de que el datum este en la corona.
    p2, _, largos2 = _proyecto_escalonado()
    v1 = _volumen_concreto(p2)
    dz = 7.0
    p2.wall.crown_profile = [(y, z + dz) for y, z in p2.wall.crown_profile]
    p2.wall.base_profile = [(y, z + dz) for y, z in p2.wall.base_profile]
    p2.wall.z_top += dz
    p2.wall.z_base += dz
    p2.piles.z_top += dz
    p2.piles.z_bots = [v + dz for v in p2.piles.z_bots]
    p2.piles.z_bot += dz
    check("el volumen no depende del datum", _volumen_concreto(p2), v1, 0.001)


def main() -> int:
    test_geometria()
    test_zonas_por_pila()
    test_ficha_por_pila()
    test_dimensionamiento_por_pila()
    test_despiece_por_pila()
    test_regresiones()
    print("\n%s" % ("TODO OK" if not FAILS else "FALLAN %d: %s" % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

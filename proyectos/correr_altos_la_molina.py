"""Ciclo completo del muro de Altos de La Molina, tramo por tramo.

Modelo -> SAP2000 -> resultados -> diseno -> despiece -> laminas -> memoria, y
contraste de lo obtenido contra las tablas 42, 43 y 44 del estudio geotecnico.

    python proyectos/correr_altos_la_molina.py            # los dos tramos
    python proyectos/correr_altos_la_molina.py tramo_2    # solo uno

Requiere SAP2000 instalado y licencia libre. Deja todo en salidas/altos_la_molina.
No canalice la salida por `tail`: use `> salida.log 2>&1 &` y lea el log.
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.builder import build                        # noqa: E402
from app.exporters import drawing, dxf, oapi, pdfout, raster  # noqa: E402
from app.core.builder import G_MURO, G_PILAS, G_VIGA     # noqa: E402
from app.results import detailing, extract, memoria, rebar, report, sizing  # noqa: E402
from proyectos.altos_la_molina import tramo_1, tramo_2    # noqa: E402

OUT = os.path.join(ROOT, "salidas", "altos_la_molina")

# Lo que el estudio entrega al disenador estructural (tablas 42, 43 y 44).
ESTUDIO = {
    "Tramo 1": {
        "vastago_Mu": 93.9, "vastago_Vu": 89.0,
        "viga_T": 126.0, "viga_M_vano": 41.0, "viga_M_voladizo": 25.0,
        "viga_M_horiz": 134.0, "viga_V": 194.0,
        "pilas_M": [269.0, 728.0, 1031.0], "pilas_N": [123.0, 183.0, 196.0],
        "pilas_V": [122.0, 263.0, 326.0],
        "concreto_m3": 20.9,
    },
    "Tramo 2": {
        "vastago_Mu": 291.1, "vastago_Vu": 173.0,
        "viga_T": 384.0, "viga_M_vano": 78.0, "viga_M_voladizo": 53.0,
        "viga_M_horiz": 252.0, "viga_V": 366.0,
        "pilas_M": [1852.0, 2835.0], "pilas_N": [331.0, 395.0],
        "pilas_V": [485.0, 657.0],
        "concreto_m3": 28.2,
    },
}


def _fila(label: str, propio: float, estudio: float, unidad: str = "") -> None:
    dif = (propio - estudio) / estudio * 100.0 if estudio else 0.0
    print("  %-34s %10.1f %-8s estudio %8.1f   %+6.1f %%"
          % (label, propio, unidad, estudio, dif), flush=True)


def corre(p, drv) -> dict:
    etq = p.info.name.split("— ")[1]
    ref = ESTUDIO[etq]
    t0 = time.time()
    print("\n" + "=" * 78, flush=True)
    print("%s" % p.info.name, flush=True)
    print("=" * 78, flush=True)

    res = build(p)
    m = res.model
    print("Modelo: %(joints)d nudos, %(frames)d frames, %(areas)d shells, "
          "%(springs)d resortes" % m.summary(), flush=True)
    for w in res.warnings:
        print("  AVISO: %s" % w, flush=True)

    sdb = os.path.join(OUT, "%s.sdb" % etq.replace(" ", "_"))
    drv.build_from_model(m, sdb)
    drv.set_beam_sections(m)                 # para que SAP disene la viga como viga
    checks = extract.run_and_verify(drv, p, m)
    print("SAP corrido y resultados leidos (%.1f s)" % (time.time() - t0), flush=True)
    if checks.get("lecturas_fallidas"):
        print("  lecturas fallidas: %s" % checks["lecturas_fallidas"], flush=True)

    # ---- dimensionamiento del refuerzo de las pilas -----------------------
    # La rigidez sale de la seccion bruta, asi que cambiar barras no cambia las
    # solicitaciones: basta con volver a verificar, sin correr SAP otra vez.
    peor = max((v["ratio_PM"] for v in checks.get("pilas") or []), default=0.0)
    print("\nRefuerzo de pilas (D/C de partida %.2f):" % peor, flush=True)
    filas = drv.frame_forces(G_PILAS)
    # El estudio entrega M_y POR PILA por el mecanismo de pila larga de Broms,
    # que pide mas que el modelo elastico sobre resortes. Esa demanda la fija el
    # geotecnista, asi que cada pila se arma para la envolvente de las dos.
    pisos = {i + 1: v for i, v in enumerate(ref["pilas_M"])}
    for linea in sizing.dimensionar_pilas(p, m, filas, pisos=pisos, por_pila=True):
        print("  %s" % linea, flush=True)
    filas_viga = (drv.frame_forces(G_VIGA)
                  if m.group_element_ids(G_VIGA, "Frame") else [])
    checks = extract.verify(p, m, filas, filas_viga, drv.area_forces(G_MURO))
    peor = max((v["ratio_PM"] for v in checks.get("pilas") or []), default=0.0)
    print("  D/C P-M tras dimensionar: %.2f" % peor, flush=True)

    # ---- pila por pila ----------------------------------------------------
    print("\nPila por pila (M_estudio es el M_y de la tabla 29):", flush=True)
    print("  %-5s %7s %8s %9s %10s %10s %9s %7s %6s"
          % ("pila", "L [m]", "cabeza", "punta", "M [kN.m]", "M_estudio",
             "V [kN]", "N [kN]", "D/C"), flush=True)
    for f in checks.get("pilas_resumen") or []:
        est = ref["pilas_M"][f["pila"] - 1] if f["pila"] <= len(ref["pilas_M"]) else 0.0
        print("  %-5d %7.2f %8.2f %9.2f %10.1f %10.1f %9.1f %7.1f %6.2f%s"
              % (f["pila"], f["longitud"], f["z_cabeza"], f["z_punta"],
                 f["Mu_max"], est, f["Vu_max"], f["Pu_max"], f["ratio_PM"],
                 "" if f["ok"] else "  <<<"), flush=True)
        zs = ", ".join(f["zonas"])
        print("        zonas: %s" % zs, flush=True)
    res_chk = checks.get("resumen") or {}
    print("  elementos no conformes: pilas %s, viga %s, muro %s"
          % (res_chk.get("no_conformes_pilas", "?"),
             res_chk.get("no_conformes_viga", "?"),
             "no" if (checks.get("muro") or {}).get("ok", True) else "SI"), flush=True)

    # ---- contraste con el estudio ---------------------------------------
    print("\nContraste con el estudio geotecnico:", flush=True)
    muro = checks.get("muro") or {}
    fr = (muro.get("franjas") or {}).get("franjas") or []
    if fr:
        base = fr[0]
        _fila("vastago, M_u en la base", base["M22_diseno"], ref["vastago_Mu"], "kN.m/m")
        _fila("vastago, V_u en la base", base["V"], ref["vastago_Vu"], "kN/m")

    viga = checks.get("viga_cabezal") or []
    if viga:
        _fila("viga, torsion T_u", max(abs(v["Tu"]) for v in viga), ref["viga_T"], "kN.m")
        _fila("viga, cortante en el apoyo", max(v["Vu"] for v in viga), ref["viga_V"], "kN")
        _fila("viga, momento vertical", max(v["Mu"] for v in viga),
              max(ref["viga_M_vano"], ref["viga_M_voladizo"]), "kN.m")
        _fila("viga, momento horizontal", max(v["Mu_h"] for v in viga),
              ref["viga_M_horiz"], "kN.m")

    for f in checks.get("pilas_resumen") or []:
        i = f["pila"] - 1
        if i < len(ref["pilas_M"]):
            _fila("pila %d, momento" % f["pila"], f["Mu_max"], ref["pilas_M"][i], "kN.m")
            _fila("pila %d, axial" % f["pila"], f["Pu_max"], ref["pilas_N"][i], "kN")

    # ---- despiece y entregables -----------------------------------------
    sch = rebar.build_schedule(p, checks)
    _fila("concreto total", sch["volumen_concreto_m3"], ref["concreto_m3"], "m3")
    print("  %-34s %10.0f kg   (%.0f kg/m3)"
          % ("acero total", sch["peso_total_kg"], sch["cuantia_kg_m3"] or 0.0), flush=True)

    base_nom = os.path.join(OUT, etq.replace(" ", "_"))
    hojas = detailing.laminas(p, checks, sch)
    juego = detailing.lamina(p, checks, sch)
    # El DXF va en METROS a 1:1 (el dibujante mide sobre el); el PDF y el SVG
    # llevan la lamina compuesta, que es papel.
    dxf.write_file(detailing.modelo(p, checks, sch), base_nom + "_planos.dxf")
    pdfout.write_file([sc for _, sc in hojas], base_nom + "_planos.pdf")
    with open(base_nom + "_planos.svg", "w", encoding="utf-8") as fh:
        fh.write(drawing.to_svg(juego))
    # Una imagen por lamina: es lo que se mira de un vistazo y lo que se pega
    # en un correo sin abrir CAD.
    for i, (_, sc) in enumerate(hojas, 1):
        with open("%s_L-0%d.png" % (base_nom, i), "wb") as fh:
            fh.write(raster.to_png(sc, 2400))
    memoria.save_memoria(p, res.report, base_nom + "_memoria.docx", checks, sch,
                         res.warnings)
    report.save_report(p, res.report, base_nom + "_resultados.xlsx", checks,
                       res.warnings, sch)
    with open(base_nom + "_proyecto.json", "w", encoding="utf-8") as fh:
        fh.write(p.model_dump_json(indent=2))

    print("\nEntregables (%d laminas):" % len(hojas), flush=True)
    sufijos = ["_planos.dxf", "_planos.pdf", "_planos.svg", "_memoria.docx",
               "_resultados.xlsx", "_proyecto.json"]
    sufijos += ["_L-0%d.png" % i for i in range(1, len(hojas) + 1)]
    for suf in sufijos:
        f = base_nom + suf
        print("  %-28s %8.0f kB" % (os.path.basename(f), os.path.getsize(f) / 1024.0),
              flush=True)
    return checks


def main(argv: list[str]) -> int:
    os.makedirs(OUT, exist_ok=True)
    cuales = {"tramo_1": [tramo_1], "tramo_2": [tramo_2]}.get(
        argv[1] if len(argv) > 1 else "", [tramo_1, tramo_2])

    drv = oapi.SapDriver(attach=True).open()
    try:
        for fn in cuales:
            corre(fn(), drv)
    finally:
        drv.close(keep_open=True)
    print("\nTodo en %s" % OUT, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

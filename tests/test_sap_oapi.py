"""Prueba de integracion contra SAP2000 por OAPI.

Construye el modelo, lo corre, lee resultados, aplica las verificaciones y
contrasta los cortes de seccion con el calculo cerrado.

    python tests/test_sap_oapi.py            # proyecto parametrico por defecto
    python tests/test_sap_oapi.py dibujado   # corona inclinada + freatico + sobrecarga
    python tests/test_sap_oapi.py avanzado   # ademas caso modal y P-Delta no lineal

Requiere Windows con SAP2000 instalado. Abre SAP (~20 s la primera vez) y lo
deja abierto con el modelo cargado.

Nota: no canalice la salida por `tail`/`head`, que la retiene hasta el final.
Para seguir el progreso: `python -u tests/test_sap_oapi.py > salida.log 2>&1 &`
"""
from __future__ import annotations

import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from app.core.builder import build
from app.core.params import EarthPressure, Seismic, SoilProfile, WallProject
from app.exporters import oapi
from app.results import extract, report
from test_reference import reference_project


def drawn_project() -> WallProject:
    """Caso dificil: corona escalonada, nivel freatico y sobrecarga."""
    p = reference_project()
    p.info.name = "Muro perfil variable"
    p.wall.length = 21.0
    p.wall.crown_profile = [(0.0, 6.0), (7.0, 6.0), (14.0, 3.5), (21.0, 2.0)]
    p.piles.spacing = 3.0
    p.earth = EarthPressure(method="rankine", condition="activo", gamma=17.0,
                            gamma_sat=20.0, phi=30.0, surcharge=12.0)
    p.seismic = Seismic(enabled=True, kh=0.15, method="mononobe")
    p.soil = SoilProfile(layers=p.soil.layers, water_table_z=2.0)
    return p


def main(argv: list[str]) -> int:
    arg = argv[1] if len(argv) > 1 else ""
    drawn = arg.startswith("dib")
    avanzado = arg.startswith("ava")
    proj = drawn_project() if drawn else reference_project()
    if avanzado:
        proj.info.name = "Muro con modal y P-Delta"
        proj.analysis.modal = True
        proj.analysis.modal_modes = 12
        proj.analysis.pdelta = True
    fails: list[str] = []

    def check(label: str, got: float, want: float, tol_pct: float = 0.5) -> None:
        err = abs(got - want) / want * 100.0 if want else abs(got)
        ok = err <= tol_pct
        print("  %-42s SAP %11.2f   teoria %11.2f   %6.3f%%  %s"
              % (label, got, want, err, "OK" if ok else "<<< FALLA"), flush=True)
        if not ok:
            fails.append(label)

    t0 = time.time()
    res = build(proj)
    m = res.model
    print("Modelo neutro: %(joints)d nudos, %(frames)d frames, %(areas)d shells, "
          "%(springs)d resortes" % m.summary(), flush=True)

    drv = oapi.SapDriver(attach=True).open()
    tag = "Test_dibujado" if drawn else ("Test_avanzado" if avanzado else "Test_parametrico")
    sdb = os.path.join(ROOT, "salidas", tag + ".sdb")
    drv.build_from_model(m, sdb)
    print("Cargado en SAP (%.1f s)" % (time.time() - t0), flush=True)

    # Topologia tal como la ve SAP
    print("\nTopologia en SAP: %s nudos, %s frames, %s areas"
          % (drv.model.PointObj.Count(), drv.model.FrameObj.Count(), drv.model.AreaObj.Count()),
          flush=True)

    checks = extract.run_and_verify(drv, proj, m)
    print("Analisis y verificacion listos (%.1f s)" % (time.time() - t0), flush=True)
    print("lecturas fallidas:", checks.get("lecturas_fallidas", "ninguna"), flush=True)
    if checks.get("lecturas_fallidas"):
        fails.append("lectura de resultados")

    # ---- contraste con el calculo cerrado --------------------------------
    print("\nEquilibrio global (combinacion S1 D+H = 1.0 DEAD + 1.0 SUELO):", flush=True)
    cuts = {(c["cut"], c["case"]): c for c in checks.get("section_cuts", [])}
    cut = cuts.get(("CUT_CORTE_MURO_BASE", "S1 D+H"))
    if cut is None:
        print("  <<< FALLA: el corte del muro no devolvio resultados", flush=True)
        fails.append("corte de seccion vacio")
    else:
        w = proj.wall
        if w.is_drawn:
            pts = sorted(w.crown_profile)
            area = sum((z0 + z1) / 2 * (y1 - y0) for (y0, z0), (y1, z1) in zip(pts, pts[1:]))
        else:
            area = w.length * (w.z_top - w.z_base)
        check("peso propio de la pantalla [kN]",
              cut["F3"], area * w.thickness * proj.materials.concrete.gamma)

        if not w.is_drawn and proj.soil.water_table_z is None:
            K = proj.earth.coefficient()
            H, L = w.z_top - w.z_base, w.length
            g = proj.earth.gamma
            check("empuje estatico [kN]", cut["F1"], 0.5 * K * g * H * H * L)
            check("momento en la base [kN-m]", cut["M2"], 0.5 * K * g * H * H * L * H / 3.0)

    # Las reacciones de resorte deben igualar el peso propio (no hay restraints)
    reac = checks.get("reaccion_vertical", {})
    if reac:
        print("\nReaccion vertical por combinacion:", flush=True)
        for k, v in reac.items():
            print("  %-26s %10.2f kN" % (k, v), flush=True)
        base = reac.get("S1 D+H")
        u1 = reac.get("U1 1.2D+1.6H")
        if base and u1:
            check("escalado 1.2D de la reaccion [kN]", u1, 1.2 * base)

    print("\nResumen de verificaciones:", flush=True)
    for k, v in checks["resumen"].items():
        print("  %-30s %s" % (k, v), flush=True)


    # ---- franjas de diseno de la pantalla --------------------------------
    fr = (checks.get("muro") or {}).get("franjas") or {}
    if fr:
        print("\nFranjas de diseno de la pantalla (cara de viga en z = %.2f m, "
              "cara de pila a %.2f m del eje):" % (fr["z_cara_viga"], fr["radio_pila"]), flush=True)
        print("  %-3s %-13s %9s %9s %9s %9s %9s %9s"
              % ("#", "Z [m]", "M22", "M22 dis", "As vert", "M11 eje", "M11 cara", "As h ap"),
              flush=True)
        for f in fr["franjas"]:
            print("  %-3d %5.2f-%-6.2f %9.1f %9.1f %9.0f %9.1f %9.1f %9.0f"
                  % (f["franja"], f["z_ini"], f["z_fin"], f["M22"], f["M22_diseno"],
                     f["vertical"]["As"], f["M11_eje"], f["M11_cara"],
                     f["horizontal_apoyo"]["As"]), flush=True)
        print("  reduccion por cara de apoyo: vertical %s%%, horizontal %s%%"
              % (fr.get("reduccion_cara_vertical_pct"),
                 fr.get("reduccion_cara_horizontal_pct")), flush=True)
    else:
        print("\n<<< FALLA: no se generaron franjas de diseno", flush=True)
        fails.append("franjas de diseno")

    # ---- torsion de la viga cabezal --------------------------------------
    tv = checks.get("torsion_viga")
    if tv:
        print("\nDiseno por torsion de la viga cabezal:", flush=True)
        print("  Tu = %.1f kN-m   umbral = %.1f   Tcr = %.1f   D/C V+T = %.2f"
              % (tv["Tu"], tv["T_umbral"], tv["T_cr"], tv["ratio_VT"]), flush=True)
        print("  estribos %s @ %.0f mm (max %.0f)   (Av+2At)/s = %.0f mm2/m"
              % (tv["estribo"], tv["s_estribo"], tv["s_max"], tv["Avt_s"]), flush=True)
        print("  Al = %.0f mm2 -> %d barras %s en el perimetro"
              % (tv["Al"], tv["n_barras_torsion"], tv["barra_torsion"]), flush=True)
        if tv["s_estribo"] > tv["s_max"]:
            fails.append("separacion de estribos sobre el maximo")
    else:
        print("\nTorsion de la viga cabezal: por debajo del umbral, sin diseno.", flush=True)

    # ---- diseno de concreto corrido por SAP ------------------------------
    ds = checks.get("diseno_sap") or {}
    if ds:
        print("\nDiseno de concreto de SAP2000 (codigo %s):" % ds.get("codigo"), flush=True)
        nd = ds.get("viga_cabezal_no_disponible")
        if nd:
            print("  viga: %s" % nd, flush=True)
        vg = ds.get("viga_cabezal") or []
        if vg:
            peor = max(vg, key=lambda r: r["Al_torsion"])
            print("  viga: %d estaciones   As sup max = %.0f mm2   Al torsion max = %.0f mm2"
                  % (len(vg), max(r["As_sup"] for r in vg), peor["Al_torsion"]), flush=True)
        pl = ds.get("pilas") or []
        if pl:
            peor = max(pl, key=lambda r: r["ratio_PMM"])
            print("  pilas: %d estaciones   D/C P-M-M max = %.3f (frame %s)"
                  % (len(pl), peor["ratio_PMM"], peor["frame"]), flush=True)
        errs = sorted({str(r.get("error")) for r in (vg + pl) if r.get("error")})
        if errs:
            print("  avisos de SAP: %s" % "; ".join(errs), flush=True)
    else:
        print("\n<<< El diseno de concreto de SAP no devolvio resultados.", flush=True)
        fails.append("diseno de concreto de SAP")

    ct = checks.get("comparacion_torsion")
    if ct:
        print("\nContraste de torsion propio vs SAP:", flush=True)
        print("  Al   : propio %8.0f mm2     SAP %8.0f mm2     dif %s%%"
              % (ct["Al_propio"], ct["Al_sap"], ct["dif_Al_pct"]), flush=True)
        print("  At/s : propio %8.0f mm2/m   SAP %8.0f mm2/m   dif %s%%"
              % (ct["At_s_propio"], ct["At_s_sap"], ct["dif_At_s_pct"]), flush=True)
        # Son dos implementaciones distintas de ACI 318 22.7 sobre el mismo
        # modelo: no tienen por que coincidir al decimal, pero una diferencia
        # grande significaria que una de las dos esta mal.
        for etiqueta, dif in (("Al", ct["dif_Al_pct"]), ("At/s", ct["dif_At_s_pct"])):
            if dif is None or abs(dif) > 15.0:
                print("  <<< FALLA: %s se aparta un %s%% de SAP" % (etiqueta, dif),
                      flush=True)
                fails.append("contraste de torsion en %s" % etiqueta)
    elif checks.get("torsion_viga"):
        nd = (checks.get("diseno_sap") or {}).get("viga_cabezal_no_disponible")
        print("\n<<< FALLA: no hay contraste de torsion. %s" % (nd or ""), flush=True)
        fails.append("contraste de torsion ausente")

    # ---- modal y P-Delta -------------------------------------------------
    if avanzado:
        md = checks.get("modal") or {}
        if md:
            print("\nAnalisis modal (%d modos):" % md["n_modos"], flush=True)
            print("  T1 = %.4f s   dominante X: modo %d (T = %.4f s)"
                  % (md["T1"], md["modo_dominante_X"], md["T_dominante_X"]), flush=True)
            print("  masa acumulada  X = %.3f   Y = %.3f"
                  % (md["masa_acumulada_X"], md["masa_acumulada_Y"]), flush=True)
            print("  %-6s %10s %10s %8s %8s" % ("modo", "T [s]", "f [Hz]", "Ux", "Uy"), flush=True)
            for r in md["modos"][:8]:
                print("  %-6d %10.4f %10.3f %8.3f %8.3f"
                      % (r["modo"], r["T"], r["f"], r["Ux"], r["Uy"]), flush=True)
            if md["T1"] <= 0.0:
                fails.append("periodo modal nulo")
        else:
            print("\n<<< FALLA: el caso modal no devolvio resultados", flush=True)
            fails.append("resultados modales")

        try:
            ret = drv.model.LoadCases.GetNameList()
            nombres = [str(x) for x in ret[1]]
        except Exception as exc:
            nombres = []
            print("  (no se pudo listar los casos: %s)" % exc, flush=True)
        tiene = any("PDELTA" in n for n in nombres)
        print("\nCasos en el modelo: %s" % ", ".join(nombres), flush=True)
        print("Caso P-Delta presente: %s" % ("SI" if tiene else "NO"), flush=True)
        if nombres and not tiene:
            fails.append("caso P-Delta ausente")

    xlsx = os.path.join(ROOT, "salidas", tag + "_resultados.xlsx")
    report.save_report(proj, res.report, xlsx, checks, res.warnings)
    print("\nExcel: %s (%d bytes)" % (xlsx, os.path.getsize(xlsx)), flush=True)
    print("TOTAL %.1f s" % (time.time() - t0), flush=True)

    print("\n%s" % ("TODO OK" if not fails else "FALLAS: " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""Pruebas del despiece, la lamina y la memoria, sin SAP.

    python tests/test_despiece.py

Comprueba que las barras salen con longitudes y pesos coherentes, que los tres
formatos de dibujo se generan bien formados, y que la memoria en Word trae los
capitulos esperados.
"""
from __future__ import annotations

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from app.core.builder import build
from app.exporters import drawing, dxf, pdfout
from app.results import design as D
from app.results import detailing, extract, memoria, rebar, report
from test_design import _synthetic_rows
from test_reference import reference_project

FAILS: list[str] = []
OUT = os.path.join(ROOT, "tests", "_out")


def check(label: str, got, want, tol: float = 0.01) -> None:
    if isinstance(want, (int, float)) and not isinstance(want, bool) \
            and isinstance(got, (int, float)) and not isinstance(got, bool):
        err = abs(got - want) / abs(want) * 100.0 if want else abs(got)
        ok = err <= tol * 100.0
        print("  %-52s %12.3f  esperado %12.3f  %s"
              % (label, got, want, "OK" if ok else "<<< FALLA"), flush=True)
    else:
        ok = got == want
        print("  %-52s %-12s  esperado %-12s  %s"
              % (label, got, want, "OK" if ok else "<<< FALLA"), flush=True)
    if not ok:
        FAILS.append(label)


def _caso():
    p = reference_project()
    p.info.engineer = "Ingeniero de prueba"
    p.info.client = "Cliente de prueba"
    res = build(p)
    checks = extract.verify(p, res.model, *_synthetic_rows(p, res.model))
    return p, res, checks


# --------------------------------------------------------------------------
def test_longitudes(p) -> None:
    """Desarrollo, ganchos y traslapos contrastados a mano (ACI 318-19 cap. 25)."""
    print("\n1. Longitudes de desarrollo y ganchos")
    fc, fy = 21000.0, 420000.0
    for bar, k in (("#5", 2.1), ("#8", 1.7)):
        db = D.bar_diam(bar)
        ld = 420.0 / (k * math.sqrt(21.0)) * db / 1000.0
        check("ld de %s [m]" % bar, rebar.ld_traccion(bar, fc, fy), max(ld, 0.300))
        ldh = 420.0 / (23.0 * math.sqrt(21.0)) * db ** 1.5 / 1000.0
        check("ldh de %s [m]" % bar, rebar.ldh_gancho(bar, fc, fy),
              max(ldh, 8 * db / 1000.0, 0.150))
        check("solape clase B de %s [m]" % bar, rebar.solape_clase_b(bar, fc, fy),
              max(1.3 * max(ld, 0.300), 0.30))
    check("extension gancho 90 de #5 [m]", rebar.ext_gancho("#5", 90),
          12 * D.bar_diam("#5") / 1000.0)
    check("extension gancho 135 de #4 [m]", rebar.ext_gancho("#4", 135),
          max(6 * D.bar_diam("#4"), 75.0) / 1000.0)
    check("peso lineal de #8 [kg/m]", rebar.peso_ml("#8"), 510.0 * 1e-6 * 7850.0)

    print("\n   Seleccion de barras")
    check("malla que cubre 1000 mm2/m con #5",
          rebar.as_de_malla("#5", rebar.separacion_malla(1000.0, "#5")) >= 1000.0, True)
    check("separacion acotada por el maximo",
          rebar.separacion_malla(1.0, "#5", s_max=300.0), 300.0)
    check("n barras para 2000 mm2 con #7",
          rebar.n_barras(2000.0, "#7"), math.ceil(2000.0 / D.bar_area("#7")))


# --------------------------------------------------------------------------
def test_planilla(p, checks) -> dict:
    print("\n2. Planilla de aceros")
    sch = rebar.build_schedule(p, checks)
    check("hay marcas", len(sch["marcas"]) > 10, True)
    check("marcas unicas", len({m["marca"] for m in sch["marcas"]}), len(sch["marcas"]))
    check("todas con cantidad positiva",
          all(m["cantidad"] > 0 for m in sch["marcas"]), True)
    check("todas con largo positivo",
          all(m["largo_m"] > 0 for m in sch["marcas"]), True)
    check("ninguna supera la barra comercial",
          all(m["largo_m"] <= rebar.LARGO_COMERCIAL + 1e-6 for m in sch["marcas"]), True)
    check("hay marcas de los tres elementos",
          len({m["elemento"] for m in sch["marcas"]}), 3)

    peso = sum(m["peso_total_kg"] for m in sch["marcas"])
    check("el peso total cuadra con las marcas", sch["peso_total_kg"], peso, 0.001)
    suma_diam = sum(d["peso_kg"] for d in sch["por_diametro"])
    check("el resumen por diametro cuadra", suma_diam, peso, 0.005)
    suma_elem = sum(sch["por_elemento"].values())
    check("el resumen por elemento cuadra", suma_elem, peso, 0.005)
    check("cuantia en rango razonable [kg/m3]",
          40.0 <= sch["cuantia_kg_m3"] <= 250.0, True)

    # volumen de concreto a mano
    w = p.wall
    vol = w.length * (w.z_top - w.z_base) * w.thickness
    vol += p.cap_beam.width * p.cap_beam.depth * w.length
    vol += len(p.pile_y_positions()) * math.pi * p.piles.diameter ** 2 / 4.0 \
        * (p.piles.z_top - p.piles.z_bot)
    check("volumen de concreto [m3]", sch["volumen_concreto_m3"], vol, 0.002)

    # las zonas de pila deben solapar
    sup = next(m for m in sch["marcas"]
               if m["elemento"] == "Pila" and "SUP" in m["posicion"]
               and "longitudinal" in m["posicion"])
    zona_sup = max(p.piles.zones, key=lambda z: max(z.z_from, z.z_to))
    h_sup = abs(zona_sup.z_from - zona_sup.z_to)
    check("el longitudinal de pila supera la altura de su zona",
          sup["largo_m"] > h_sup, True)
    check("la marca superior lleva gancho", sup["forma"], "L")

    print("\n   %-5s %-46s %-4s %7s %6s %9s"
          % ("Marca", "Posicion", "Bar", "Largo", "Cant", "Peso kg"))
    for m in sch["marcas"][:8]:
        print("   %-5s %-46s %-4s %7.2f %6d %9.1f"
              % (m["marca"], m["posicion"][:46], m["diametro"], m["largo_m"],
                 m["cantidad"], m["peso_total_kg"]))
    print("   ... %d marcas en total,  %.0f kg,  %.0f kg/m3"
          % (len(sch["marcas"]), sch["peso_total_kg"], sch["cuantia_kg_m3"]))
    return sch


# --------------------------------------------------------------------------
def test_dibujo(p, checks, sch) -> None:
    print("\n3. Lamina de despiece en DXF, SVG y PDF")
    hojas = detailing.laminas(p, checks, sch)
    # Con una planilla normal el despiece cabe junto a las secciones: dos
    # laminas. Solo si crece hasta no caber se separa en una tercera.
    check("el juego tiene dos laminas", len(hojas), 2, 0.0)
    check("la segunda incluye el despiece", "DESPIECE" in hojas[1][0], True)
    for titulo, sc in hojas:
        x0, y0, x1, y1 = sc.bbox()
        check("%s: tiene geometria" % titulo[:22], len(sc.prims) > 150, True)
        check("%s: cabe en A1 en X" % titulo[:22], x1 <= 1189.0 + 1e-6, True)
        check("%s: cabe en A1 en Y" % titulo[:22], y1 <= 841.0 + 1e-6, True)
        check("%s: no se sale" % titulo[:22], x0 >= -1e-6 and y0 >= -1e-6, True)
        textos = " ".join(q.s for q in sc.prims if isinstance(q, drawing.Text))
        check("%s: lleva numero de lamina" % titulo[:22], "L-0" in textos, True)

    # Con muchas marcas la planilla no cabe con las secciones y se separa sola,
    # en vez de apretar las filas hasta que no se lean.
    import copy
    enorme = copy.deepcopy(sch)
    enorme["marcas"] = [dict(mk, marca="%s_%d" % (mk["marca"], k))
                        for k in range(5) for mk in sch["marcas"]]
    tres = detailing.laminas(p, checks, enorme)
    check("con 5 veces mas marcas se separa en tres", len(tres), 3, 0.0)
    for titulo, sc in tres:
        x0, y0, x1, y1 = sc.bbox()
        check("separada, %s cabe en A1" % titulo[:18],
              x1 <= 1189.0 + 1e-6 and y1 <= 841.0 + 1e-6, True)

    # La lamina "junta" es el juego en fila, que es lo que va al DXF y al SVG
    hoja = detailing.lamina(p, checks, sch)
    check("la junta suma las tres", len(hoja.prims),
          sum(len(sc.prims) for _, sc in hojas), 0.0)
    jx0, jy0, jx1, jy1 = hoja.bbox()
    check("la junta ocupa dos hojas de ancho", jx1 > 1189.0, True)
    check("y una de alto", jy1 <= 841.0 + 1e-6, True)

    capas = {q.layer for q in hoja.prims}
    for c in ("CONCRETO", "REFUERZO", "ESTRIBOS", "COTAS", "TEXTO", "TABLA"):
        check("usa la capa %s" % c, c in capas, True)

    os.makedirs(OUT, exist_ok=True)
    # ---- DXF: va en METROS y a 1:1, no en milimetros de papel -------------
    # La lamina compuesta es papel; el DXF lo abre el dibujante para medir
    # sobre el, asi que lleva las vistas a tamano real.
    mod = detailing.modelo(p, checks, sch)
    mx0, my0, mx1, my1 = mod.bbox()
    check("el DXF cabe en decenas de metros, no en miles",
          mx1 - mx0 < 120.0 and my1 - my0 < 120.0, True)

    # Una pila de diametro conocido tiene que medir eso en el dibujo
    from app.exporters.drawing import Circle
    r_pila = p.piles.diameter / 2.0
    radios = sorted({round(c.r, 3) for c in mod.prims if isinstance(c, Circle)})
    check("hay circulos del radio real de la pila",
          any(abs(r - r_pila) < 0.005 for r in radios), True)

    # Y el muro mide su longitud real de extremo a extremo
    L = p.wall.y_end - p.wall.y_start
    from app.exporters.drawing import Poly
    anchos = [max(q[0] for q in pl.pts) - min(q[0] for q in pl.pts)
              for pl in mod.prims if isinstance(pl, Poly)]
    check("alguna figura mide la longitud del muro",
          any(abs(a - L) < 0.05 for a in anchos), True)

    dxf.write_file(mod, os.path.join(OUT, "modelo_metros.dxf"))
    with open(os.path.join(OUT, "modelo_metros.dxf"), encoding="ascii") as fh:
        lin = [v.strip() for v in fh.read().splitlines()]
    k = lin.index("$EXTMAX")          # tras la variable van 10/x, 20/y, 30/z
    ex, ey = float(lin[k + 2]), float(lin[k + 4])
    check("el EXTMAX del DXF esta en metros", max(abs(ex), abs(ey)) < 120.0, True)
    check("el DXF se declara en metros", lin[lin.index("$INSUNITS") + 2], "6")

    t = dxf.export(hoja)
    lineas = t.split("\r\n")
    check("DXF empieza por el par 0/SECTION", lineas[:2], ["0", "SECTION"])
    check("DXF termina en el par 0/EOF", lineas[-3:-1], ["0", "EOF"])
    check("DXF usa CRLF en todo el archivo",
          t.replace("\r\n", "").count("\n"), 0)
    check("DXF con numero par de lineas", (len(lineas) - 1) % 2, 0)
    for tabla in ("HEADER", "TABLES", "ENTITIES", "LAYER"):
        check("DXF contiene %s" % tabla, tabla in t, True)
    check("DXF es ASCII puro", all(ord(c) < 128 for c in t), True)
    check("DXF equilibra POLYLINE y SEQEND",
          lineas.count("POLYLINE"), lineas.count("SEQEND"))
    check("cada VERTEX cuelga de una POLYLINE",
          lineas.count("VERTEX") >= lineas.count("POLYLINE"), True)
    dxf.write_file(hoja, os.path.join(OUT, "planos.dxf"))

    # ---- SVG -------------------------------------------------------------
    s = drawing.to_svg(hoja)
    check("SVG bien formado", s.startswith("<?xml") and s.rstrip().endswith("</svg>"), True)
    check("SVG en milimetros", 'width="1189.00mm"' in s, True)
    check("SVG sin marcadores sin cerrar", s.count("<svg"), s.count("</svg>"))
    with open(os.path.join(OUT, "planos.svg"), "w", encoding="utf-8") as fh:
        fh.write(s)

    # ---- PDF -------------------------------------------------------------
    b = pdfout.export_multi([sc for _, sc in hojas])
    check("PDF con cabecera correcta", b[:8], b"%PDF-1.4")
    check("PDF termina en EOF", b.rstrip().endswith(b"%%EOF"), True)
    check("PDF trae tabla xref", b.count(b"xref") >= 1, True)
    check("PDF con una pagina por lamina", b.count(b"/Type /Page "), len(hojas))
    check("PDF con tamano razonable", len(b) > 10000, True)
    pdfout.write_file([sc for _, sc in hojas], os.path.join(OUT, "planos.pdf"))
    print("   DXF %d B   SVG %d B   PDF %d B"
          % (len(t), len(s), len(b)))


# --------------------------------------------------------------------------
def test_memoria(p, res, checks, sch) -> None:
    print("\n4. Memoria de calculo en Word")
    path = os.path.join(OUT, "memoria.docx")
    memoria.save_memoria(p, res.report, path, checks, sch, res.warnings)
    check("archivo escrito", os.path.getsize(path) > 20000, True)

    from docx import Document
    d = Document(path)
    titulos = [q.text for q in d.paragraphs if q.style.name.startswith("Heading")]
    for esperado in ("Objeto y alcance", "Datos de partida", "Empujes de tierras",
                     "Modelo estructural", "Verificación de los elementos",
                     "Despiece de refuerzo", "Conclusiones"):
        check("capitulo «%s»" % esperado,
              any(esperado in t for t in titulos), True)
    check("hay tablas", len(d.tables) >= 10, True)
    check("lleva figuras", len(d.inline_shapes) >= 4, True)
    check("lleva indice", any("Indice" in q.text for q in d.paragraphs), True)
    check("lleva anexo de envolventes",
          any("Anexo" in t for t in titulos), True)
    sec = d.sections[0]
    check("encabezado con el nombre del proyecto",
          p.info.name in sec.header.paragraphs[0].text, True)
    check("pie con numeracion", "Pagina" in sec.footer.paragraphs[0].text, True)
    texto = "\n".join(q.text for q in d.paragraphs)
    check("desarrolla la torsion", "22.7" in texto, True)
    check("explica las franjas de diseno", "franjas de diseño" in texto, True)
    check("cita la cara del apoyo", "9.4.2.1" in texto, True)
    print("   %d parrafos, %d tablas, %d titulos"
          % (len(d.paragraphs), len(d.tables), len(titulos)))


# --------------------------------------------------------------------------
def test_excel(p, res, checks, sch) -> None:
    print("\n5. Hoja de despiece en el Excel")
    path = os.path.join(OUT, "resultados.xlsx")
    report.save_report(p, res.report, path, checks, res.warnings, sch)
    from openpyxl import load_workbook
    wb = load_workbook(path)
    check("hoja Despiece presente", "Despiece" in wb.sheetnames, True)
    ws = wb["Despiece"]
    check("una fila por marca", ws.max_row > len(sch["marcas"]), True)
    print("   hojas:", ", ".join(wb.sheetnames))


# --------------------------------------------------------------------------
def test_sin_verificaciones(p, res) -> None:
    """Sin solicitaciones no hay despiece del muro, pero nada revienta."""
    print("\n6. Degradacion sin verificaciones")
    vacio = rebar.build_schedule(p, {})
    check("sin checks no hay marcas de pantalla",
          any(m["elemento"] == "Pantalla" for m in vacio["marcas"]), False)
    check("pero si de pila", any(m["elemento"] == "Pila" for m in vacio["marcas"]), True)
    doc = memoria.build_memoria(p, res.report, None, None, res.warnings)
    check("la memoria sin checks se genera", len(doc.paragraphs) > 20, True)



# --------------------------------------------------------------------------
def test_ajustes(p, checks) -> None:
    """El refuerzo ajustado a mano manda sobre el recomendado, y se comprueba."""
    print("\n7. Ajuste manual del refuerzo")
    from app.core.params import StripOverride
    from app.exporters import dxf as _dxf
    from app.results import detailing as _det

    p.rebar_overrides.muro = []
    p.rebar_overrides.viga = type(p.rebar_overrides.viga)()
    base = rebar.build_schedule(p, checks)
    check("el recomendado cumple entero", base["marcas_insuficientes"], [])
    check("nada marcado como ajustado", base["marcas_ajustadas"], [])
    mv1 = next(m for m in base["marcas"] if m["marca"] == "MV1")
    check("la marca lleva su separacion", mv1["s_mm"] > 0, True)
    check("y la recomendada", mv1["s_rec_mm"], mv1["s_mm"], 0.001)

    # --- ajuste que cumple -------------------------------------------------
    p.rebar_overrides.muro = [StripOverride(franja=1, bar_v="#7", s_v=150.0)]
    sube = rebar.build_schedule(p, checks)
    m = next(x for x in sube["marcas"] if x["marca"] == "MV1")
    check("manda la barra impuesta", m["diametro"], "#7")
    check("manda la separacion impuesta", m["s_mm"], 150.0, 0.001)
    # La recomendacion se recalcula PARA LA BARRA ELEGIDA: con una #7 hace falta
    # menos densidad que con una #5 para la misma area, asi que el paso sugerido
    # crece. Es lo que se quiere mostrar en el control de edicion.
    check("la recomendacion se adapta a la barra elegida",
          m["s_rec_mm"] > mv1["s_rec_mm"], True)
    check("y cubre el area requerida",
          rebar.as_de_malla("#7", m["s_rec_mm"]) >= m["as_req"] * 0.999, True)
    check("queda marcada como ajustada", m["ajustado"], True)
    check("el area colocada es la de la malla impuesta",
          m["as_prov"], rebar.as_de_malla("#7", 150.0), 0.001)
    check("sigue cumpliendo", m["cumple"], True)
    check("y pesa mas", sube["peso_total_kg"] > base["peso_total_kg"], True)

    # --- ajuste insuficiente ----------------------------------------------
    p.rebar_overrides.muro = [StripOverride(franja=1, bar_v="#4", s_v=400.0)]
    baja = rebar.build_schedule(p, checks)
    m = next(x for x in baja["marcas"] if x["marca"] == "MV1")
    check("un ajuste corto no cumple", m["cumple"], False)
    check("y queda listado", "MV1" in baja["marcas_insuficientes"], True)
    check("pero se dibuja igual", m["as_prov"] > 0, True)

    # --- el ajuste llega al dibujo ----------------------------------------
    p.rebar_overrides.muro = []
    a = _dxf.export(_det.lamina(p, checks, rebar.build_schedule(p, checks)))
    p.rebar_overrides.muro = [StripOverride(franja=1, bar_v="#7", s_v=150.0)]
    b = _dxf.export(_det.lamina(p, checks, rebar.build_schedule(p, checks)))
    check("el DXF cambia con el ajuste", a == b, False)
    check("el DXF nombra la barra impuesta", "#7 @ 150" in b, True)
    check("el recomendado no la nombraba", "#7 @ 150" in a, False)
    # Solo se ajusto la franja 1: las otras siguen con el armado recomendado,
    # asi que la #5 tiene que seguir apareciendo, pero menos veces.
    check("quedan menos etiquetas de la barra recomendada",
          b.count("#5 @") < a.count("#5 @"), True)

    # --- la viga ------------------------------------------------------------
    p.rebar_overrides.muro = []
    p.rebar_overrides.viga.n_sup = 4
    p.rebar_overrides.viga.s_tie = 200.0
    v = rebar.build_schedule(p, checks)
    vc1 = next(x for x in v["marcas"] if x["marca"] == "VC1")
    vc3 = next(x for x in v["marcas"] if x["forma"] == "estribo_rect")
    check("la viga acepta el numero de barras", vc1["n_elem"], 4, 0.0)
    check("aflojar la viga se detecta", vc1["cumple"], False)
    check("el estribo impuesto manda", vc3["s_mm"], 200.0, 0.001)
    check("y recuerda el recomendado", vc3["s_rec_mm"] < 200.0, True)

    # --- restablecer --------------------------------------------------------
    p.rebar_overrides.muro = []
    p.rebar_overrides.viga = type(p.rebar_overrides.viga)()
    vuelta = rebar.build_schedule(p, checks)
    check("al restablecer vuelve el recomendado",
          vuelta["peso_total_kg"], base["peso_total_kg"], 0.001)
    check("y no queda nada insuficiente", vuelta["marcas_insuficientes"], [])
    print("   recomendado %.0f kg  |  reforzado %.0f kg  |  aflojado %.0f kg"
          % (base["peso_total_kg"], sube["peso_total_kg"], baja["peso_total_kg"]))


# --------------------------------------------------------------------------
def main() -> int:
    p, res, checks = _caso()
    test_longitudes(p)
    sch = test_planilla(p, checks)
    test_dibujo(p, checks, sch)
    test_memoria(p, res, checks, sch)
    test_excel(p, res, checks, sch)
    test_sin_verificaciones(p, res)
    test_ajustes(p, checks)
    print("\n%s" % ("TODO OK" if not FAILS
                    else "FALLAS (%d): %s" % (len(FAILS), ", ".join(FAILS))))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Backend local del generador de muros de contencion.

Se ejecuta en la maquina del usuario, por lo que conserva acceso al OAPI de
SAP2000 mientras sirve la interfaz al navegador.
"""
from __future__ import annotations

import io
import os
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .core.builder import G_MURO, G_MURO_BASE, G_PILAS, G_VIGA, build
from .core.params import WallProject
from .exporters import drawing, dxf, oapi, pdfout, s2k
from .results import detailing, extract, memoria, rebar, report

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "web", "static")
OUT_DIR = os.path.join(os.path.dirname(BASE_DIR), "salidas")
os.makedirs(OUT_DIR, exist_ok=True)

app = FastAPI(title="Modelador de muros de contencion", version="1.0")


# --------------------------------------------------------------------------
# Modelos de peticion
# --------------------------------------------------------------------------
class DesignRequest(BaseModel):
    """Peticion de despiece o memoria.

    `checks` son las verificaciones que devolvio /api/sap/build con run=True.
    El cliente las conserva y las reenvia, de modo que el servidor no guarda
    estado entre peticiones.
    """

    project: WallProject
    checks: dict | None = None
    # None a proposito: un valor aqui pisaria la barra por defecto que el
    # ingeniero haya fijado en `project.rebar_overrides`, que es la que manda.
    bar_v: str | None = None
    bar_h: str | None = None
    ancho_mm: float = 1189.0
    alto_mm: float = 841.0


class DetalleRequest(DesignRequest):
    """Peticion de una vista de refuerzo concreta."""

    vista: str = "conjunto"
    ancho_mm: float = 900.0
    alto_mm: float = 620.0


class SapRequest(BaseModel):
    project: WallProject
    filename: str = "MuroContencion"
    run: bool = False
    attach: bool = True
    design: bool = True   # lanzar tambien el diseno de concreto de SAP


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _build_or_400(project: WallProject):
    try:
        return build(project)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _geometry_payload(m) -> dict:
    """Geometria compacta para el visor 3D del navegador."""
    pressures: dict[int, float] = {}
    for v in m.pattern_values:
        if v.pattern == "EMPUJE":
            pressures[v.joint] = v.value

    group_of_frame: dict[int, str] = {}
    for g, kind, eid in m.group_members:
        if kind == "Frame" and g in (G_PILAS, G_VIGA):
            group_of_frame[eid] = g

    return {
        "joints": [[j.id, round(j.x, 4), round(j.y, 4), round(j.z, 4)] for j in m.joints],
        "frames": [[f.id, f.i, f.j, group_of_frame.get(f.id, "OTRO")] for f in m.frames],
        "areas": [[a.id, *a.joints] for a in m.areas],
        "springs": [[s.joint, round(s.u1, 1), round(s.u3, 1)] for s in m.springs],
        "pressure": {str(k): v for k, v in pressures.items()},
        "bounds": m.bounds(),
    }


def _safe_name(name: str) -> str:
    keep = "".join(ch for ch in name if ch.isalnum() or ch in " _-.")
    return (keep.strip() or "Modelo").replace(" ", "_")


# SAP2000 se cierra en cuanto se suelta la ultima referencia COM, asi que la
# sesion se conserva entre peticiones: el modelo queda abierto para el usuario
# y la siguiente llamada no paga los ~20 s de arranque.
_DRIVER: oapi.SapDriver | None = None


def _get_driver(attach: bool = True) -> oapi.SapDriver:
    global _DRIVER
    if _DRIVER is not None:
        try:
            _DRIVER.model.GetModelFilename()  # ping: sigue viva?
            return _DRIVER
        except Exception:
            _DRIVER = None
    _DRIVER = oapi.SapDriver(attach=attach).open()
    return _DRIVER


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@app.get("/api/defaults")
def defaults() -> dict:
    """Proyecto por defecto, calcado del modelo de referencia entregado."""
    p = WallProject()
    return p.model_dump()


@app.post("/api/preview")
def preview(project: WallProject) -> dict:
    res = _build_or_400(project)
    return {
        "report": res.report,
        "warnings": res.warnings,
        "geometry": _geometry_payload(res.model),
    }


@app.post("/api/export/s2k")
def export_s2k(project: WallProject) -> Response:
    res = _build_or_400(project)
    name = _safe_name(project.info.name) + ".s2k"
    text = s2k.export(res.model, name)
    return Response(
        content=text.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="%s"' % name},
    )


@app.post("/api/export/excel")
def export_excel(req: DesignRequest) -> Response:
    """Reporte en Excel. Con verificaciones trae ademas el diseno y el despiece.

    Antes recibia solo el proyecto y pasaba checks=None, de modo que el Excel
    que salia de la app nunca llevaba los resultados aunque el modelo estuviera
    corrido y verificado. La ruta por script si los llevaba: dos caminos, dos
    libros distintos.
    """
    res = _build_or_400(req.project)
    sch = None
    if req.checks and req.checks.get("muro"):
        sch = rebar.build_schedule(req.project, req.checks, req.bar_v, req.bar_h)
    wb = report.build_report(req.project, res.report, req.checks, res.warnings, sch)
    buf = io.BytesIO()
    wb.save(buf)
    name = _safe_name(req.project.info.name) + ".xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="%s"' % name},
    )


@app.post("/api/export/json")
def export_json(project: WallProject) -> Response:
    name = _safe_name(project.info.name) + ".json"
    return Response(
        content=project.model_dump_json(indent=2).encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="%s"' % name},
    )


def _despiece_or_400(req: DesignRequest):
    """Construye modelo, planilla y lamina; exige haber corrido el analisis."""
    if not req.checks or not req.checks.get("muro"):
        raise HTTPException(
            status_code=400,
            detail="Primero hay que correr y verificar el modelo en SAP: el despiece "
                   "sale de las solicitaciones reales, no de la geometria.",
        )
    res = _build_or_400(req.project)
    sch = rebar.build_schedule(req.project, req.checks, req.bar_v, req.bar_h)
    hoja = detailing.lamina(req.project, req.checks, sch, req.ancho_mm, req.alto_mm)
    return res, sch, hoja


def _laminas_or_400(req: DesignRequest):
    """El juego de laminas por separado, para el PDF multipagina."""
    if not req.checks or not req.checks.get("muro"):
        raise HTTPException(
            status_code=400,
            detail="Primero hay que correr y verificar el modelo en SAP: el despiece "
                   "sale de las solicitaciones reales, no de la geometria.",
        )
    sch = rebar.build_schedule(req.project, req.checks, req.bar_v, req.bar_h)
    return sch, detailing.laminas(req.project, req.checks, sch,
                                  req.ancho_mm, req.alto_mm)


@app.post("/api/design/despiece")
def design_despiece(req: DesignRequest) -> dict:
    """Planilla de aceros en JSON, para mostrarla en la interfaz."""
    _, sch, _ = _despiece_or_400(req)
    return sch


@app.post("/api/export/despiece.dxf")
def export_dxf(req: DesignRequest) -> Response:
    """DXF en METROS y a escala 1:1, que es lo que necesita el dibujante.

    El PDF y el SVG llevan la lamina compuesta, cuyas coordenadas son
    milimetros de hoja; ahi el muro sale a 1:20 y no se puede medir. En el DXF
    cada vista va a tamano real y solo las tablas se escalan.
    """
    _, sch, _ = _despiece_or_400(req)
    modelo = detailing.modelo(req.project, req.checks, sch)
    name = _safe_name(req.project.info.name) + "_planos.dxf"
    return Response(
        content=dxf.export(modelo).encode("ascii"),
        media_type="application/dxf",
        headers={"Content-Disposition": 'attachment; filename="%s"' % name},
    )


@app.post("/api/export/despiece.svg")
def export_svg(req: DesignRequest) -> Response:
    _, _, hoja = _despiece_or_400(req)
    name = _safe_name(req.project.info.name) + "_planos.svg"
    return Response(
        content=drawing.to_svg(hoja, req.ancho_mm, req.alto_mm).encode("utf-8"),
        media_type="image/svg+xml",
        headers={"Content-Disposition": 'attachment; filename="%s"' % name},
    )


@app.post("/api/export/despiece.pdf")
def export_pdf(req: DesignRequest) -> Response:
    # Multipagina: una lamina por hoja se lee e imprime mucho mejor que las
    # tres en fila, que es como salen en el DXF.
    _, hojas = _laminas_or_400(req)
    name = _safe_name(req.project.info.name) + "_planos.pdf"
    return Response(
        content=pdfout.export_multi([sc for _, sc in hojas],
                                    req.ancho_mm, req.alto_mm),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="%s"' % name},
    )


@app.post("/api/export/memoria")
def export_memoria(req: DesignRequest) -> Response:
    """Memoria de calculo en Word. Sin verificaciones sale la parte de datos."""
    res = _build_or_400(req.project)
    sch = None
    if req.checks and req.checks.get("muro"):
        sch = rebar.build_schedule(req.project, req.checks, req.bar_v, req.bar_h)
    doc = memoria.build_memoria(req.project, res.report, req.checks, sch, res.warnings)
    buf = io.BytesIO()
    doc.save(buf)
    name = _safe_name(req.project.info.name) + "_memoria.docx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="%s"' % name},
    )


# Cada vista es una escena de `detailing`; se sirven como SVG para que la
# interfaz muestre exactamente el mismo dibujo que acaba en el DXF.
_VISTAS = {
    "conjunto": ("Corte transversal del conjunto", "pantalla"),
    "arranque": ("Detalle de arranque de la pantalla", "pantalla"),
    "viga": ("Seccion de la viga cabezal", "viga"),
    "alzado": ("Alzado de la viga cabezal", "viga"),
    "pila": ("Seccion de la pila", "pila"),
    "lamina": ("Juego completo de laminas", None),
    "lamina1": ("L-01  Planta y alzado general", None),
    "lamina2": ("L-02  Secciones, detalles y despiece", None),
    "lamina3": ("L-03  Despiece de refuerzo", None),
    "planta": ("Planta de replanteo", None),
    "alzado_muro": ("Alzado del muro", "pantalla"),
}


@app.post("/api/design/detalle")
def design_detalle(req: DetalleRequest) -> dict:
    """Devuelve una vista del refuerzo en SVG mas su verificacion."""
    if req.vista not in _VISTAS:
        raise HTTPException(status_code=400, detail="Vista desconocida: %s" % req.vista)
    _, sch, _ = _despiece_or_400(req)
    p = req.project
    checks = req.checks or {}

    if req.vista == "lamina":
        escena = detailing.lamina(p, checks, sch)
    elif req.vista.startswith("lamina"):
        hojas = detailing.laminas(p, checks, sch)
        i = int(req.vista[-1]) - 1
        if i >= len(hojas):
            raise HTTPException(
                status_code=400,
                detail="Este proyecto solo tiene %d laminas; el despiece cabe "
                       "junto a las secciones." % len(hojas))
        escena = hojas[i][1]
    elif req.vista == "planta":
        escena = detailing.planta(p, sch)
    elif req.vista == "alzado_muro":
        escena = detailing.alzado_muro(p, checks, sch)
    elif req.vista == "conjunto":
        escena = detailing.corte_conjunto(p, sch)
    elif req.vista == "arranque":
        escena = detailing.detalle_arranque(p, sch, checks)
    elif req.vista == "viga":
        escena = detailing.seccion_viga(p, sch, checks)
    elif req.vista == "alzado":
        escena = detailing.alzado_viga(p, sch, checks)
    else:
        escena = detailing.secciones_pila(p, sch)

    if not escena.prims:
        raise HTTPException(
            status_code=400,
            detail="Esa vista no aplica a este modelo (¿viga cabezal deshabilitada?).")

    # La hoja toma la forma del dibujo. Si se fija el ancho, un corte alto y
    # estrecho —el del conjunto mide 6 m de ancho por 17 de alto— sale como una
    # tira con medio pliego en blanco a los lados.
    x0, y0, x1, y1 = escena.bbox()
    aspecto = max(x1 - x0, 1e-6) / max(y1 - y0, 1e-6)
    lado = 1000.0
    ancho, alto = (lado, lado / aspecto) if aspecto >= 1.0 else (lado * aspecto, lado)
    ancho = min(max(ancho, 180.0), 1600.0)
    alto = min(max(alto, 180.0), 1600.0)

    titulo, elemento = _VISTAS[req.vista]
    marcas = [m for m in sch["marcas"]
              if elemento is None
              or (elemento == "pantalla" and m["elemento"] == "Pantalla")
              or (elemento == "viga" and m["elemento"] == "Viga cabezal")
              or (elemento == "pila" and m["elemento"] == "Pila")]
    return {
        "vista": req.vista,
        "titulo": titulo,
        "svg": drawing.to_svg(escena, ancho, alto, margen_mm=10.0),
        "marcas": marcas,
        "insuficientes": [m["marca"] for m in marcas if not m["cumple"]],
        "ajustadas": [m["marca"] for m in marcas if m["ajustado"]],
        "n_laminas": detailing.n_laminas(sch),
        "peso_total_kg": sch["peso_total_kg"],
        "cuantia_kg_m3": sch["cuantia_kg_m3"],
    }


@app.get("/api/sap/status")
def sap_status() -> dict:
    ok, msg = oapi.is_available()
    return {"available": ok, "message": msg}


@app.post("/api/sap/build")
def sap_build(req: SapRequest) -> dict:
    ok, msg = oapi.is_available()
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    res = _build_or_400(req.project)
    sdb = os.path.join(OUT_DIR, _safe_name(req.filename) + ".sdb")
    out: dict = {"report": res.report, "warnings": list(res.warnings)}

    try:
        driver = _get_driver(attach=req.attach)
    except oapi.OAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        path = driver.build_from_model(res.model, sdb)
        out["sdb"] = path
        out["message"] = "Modelo cargado en SAP2000 y guardado en %s" % path
        if req.run:
            checks = extract.run_and_verify(driver, req.project, res.model,
                                            design=req.design)
            out["checks"] = checks
            out["message"] += ". Analisis corrido y verificaciones completadas."
            base = os.path.join(OUT_DIR, _safe_name(req.filename))
            out["excel"] = base + "_resultados.xlsx"
            sch = None
            try:
                sch = rebar.build_schedule(req.project, checks)
                hoja = detailing.lamina(req.project, checks, sch)
                hojas = detailing.laminas(req.project, checks, sch)
                dxf.write_file(hoja, base + "_planos.dxf")
                pdfout.write_file([sc for _, sc in hojas], base + "_planos.pdf")
                with open(base + "_planos.svg", "w", encoding="utf-8") as fh:
                    fh.write(drawing.to_svg(hoja, 3660.0, 860.0))
                memoria.save_memoria(req.project, res.report, base + "_memoria.docx",
                                     checks, sch, res.warnings)
                out["despiece"] = {
                    "dxf": base + "_planos.dxf",
                    "pdf": base + "_planos.pdf",
                    "svg": base + "_planos.svg",
                    "laminas": [t for t, _ in hojas],
                    "memoria": base + "_memoria.docx",
                    "resumen": {k: sch[k] for k in
                                ("peso_total_kg", "volumen_concreto_m3",
                                 "cuantia_kg_m3", "por_elemento")},
                }
                out["message"] += " Despiece y memoria generados."
            except Exception as exc:  # el despiece no debe tumbar el analisis
                out["despiece_error"] = str(exc)
            report.save_report(req.project, res.report, base + "_resultados.xlsx",
                               checks, res.warnings, sch)
    except oapi.OAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - depende de SAP
        raise HTTPException(
            status_code=500, detail="%s\n%s" % (exc, traceback.format_exc(limit=5))
        ) from exc

    return out


@app.get("/api/salidas/{filename}")
def download_output(filename: str) -> FileResponse:
    path = os.path.join(OUT_DIR, os.path.basename(filename))
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(path, filename=os.path.basename(path))


# --------------------------------------------------------------------------
# Interfaz
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    path = os.path.join(STATIC_DIR, "index.html")
    with open(path, encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


class _NoCacheStatic(StaticFiles):
    """Sirve los estaticos sin cache: la app es local y se edita en caliente."""

    def is_not_modified(self, response_headers, request_headers) -> bool:  # noqa: D102
        return False

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


app.mount("/static", _NoCacheStatic(directory=STATIC_DIR), name="static")


@app.exception_handler(ValueError)
def value_error_handler(request, exc: ValueError) -> JSONResponse:  # pragma: no cover
    return JSONResponse(status_code=400, content={"detail": str(exc)})

"""Post-proceso de resultados de SAP y verificacion de los elementos.

Al importar el .s2k, SAP conserva las etiquetas de nudos, frames y areas del
archivo, de modo que los identificadores del modelo neutro coinciden con los
nombres de objeto en SAP y se pueden cruzar directamente.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core import model as M
from ..core.builder import G_APOYOS, G_MURO, G_PILAS, G_VIGA
from ..core.params import WallProject
from . import design as D


@dataclass
class Envelope:
    """Extremos de una magnitud sobre un conjunto de resultados."""

    min: float = float("inf")
    max: float = float("-inf")
    min_case: str = ""
    max_case: str = ""

    def feed(self, value: float, case: str) -> None:
        if value < self.min:
            self.min, self.min_case = value, case
        if value > self.max:
            self.max, self.max_case = value, case

    @property
    def abs_max(self) -> float:
        lo = abs(self.min) if self.min != float("inf") else 0.0
        hi = abs(self.max) if self.max != float("-inf") else 0.0
        return max(lo, hi)

    @property
    def abs_case(self) -> str:
        lo = abs(self.min) if self.min != float("inf") else 0.0
        hi = abs(self.max) if self.max != float("-inf") else 0.0
        return self.min_case if lo >= hi else self.max_case

    def as_dict(self) -> dict:
        return {
            "min": None if self.min == float("inf") else round(self.min, 2),
            "max": None if self.max == float("-inf") else round(self.max, 2),
            "abs": round(self.abs_max, 2),
            "caso": self.abs_case,
        }


@dataclass
class ElementForces:
    label: str
    z: float | None = None
    y: float | None = None
    P: Envelope = field(default_factory=Envelope)
    V2: Envelope = field(default_factory=Envelope)
    V3: Envelope = field(default_factory=Envelope)
    T: Envelope = field(default_factory=Envelope)
    M2: Envelope = field(default_factory=Envelope)
    M3: Envelope = field(default_factory=Envelope)

    def as_dict(self) -> dict:
        return {
            "elemento": self.label, "z": self.z, "y": self.y,
            "P": self.P.as_dict(), "V2": self.V2.as_dict(), "V3": self.V3.as_dict(),
            "T": self.T.as_dict(), "M2": self.M2.as_dict(), "M3": self.M3.as_dict(),
        }


# --------------------------------------------------------------------------
# Envolventes de frames
# --------------------------------------------------------------------------
def frame_envelopes(rows: list[dict], model: M.StructuralModel) -> dict[str, ElementForces]:
    """Agrupa filas crudas de FrameForce por objeto y devuelve envolventes."""
    out: dict[str, ElementForces] = {}
    for r in rows:
        label = str(r["obj"])
        ef = out.get(label)
        if ef is None:
            ef = ElementForces(label=label)
            fid = _safe_int(label)
            if fid is not None and 1 <= fid <= len(model.frames):
                fr = model.frames[fid - 1]
                ji, jj = model.get_joint(fr.i), model.get_joint(fr.j)
                ef.z = round(0.5 * (ji.z + jj.z), 3)
                ef.y = round(0.5 * (ji.y + jj.y), 3)
            out[label] = ef
        case = str(r["case"])
        ef.P.feed(r["P"], case)
        ef.V2.feed(r["V2"], case)
        ef.V3.feed(r["V3"], case)
        ef.T.feed(r.get("T", 0.0), case)
        ef.M2.feed(r["M2"], case)
        ef.M3.feed(r["M3"], case)
    return out


SHELL_KEYS = ("M11", "M22", "M12", "F11", "F22", "V13", "V23", "VMax")


def area_envelopes(rows: list[dict], model: M.StructuralModel) -> dict[str, dict]:
    """Envolventes de shell por area, en unidades por metro.

    SAP devuelve una fila por nudo de esquina. Los valores de esquina sobre un
    apoyo puntual son singularidades numericas: crecen al refinar la malla y no
    representan una solicitacion de diseno. Por eso se promedian los nudos de
    cada elemento antes de envolver, y el pico crudo se guarda aparte para
    poder senalarlo.
    """
    # 1) media sobre los nudos de esquina, por elemento y caso
    acc: dict[tuple[str, str], dict] = {}
    peaks: dict[str, dict[str, float]] = {}
    for r in rows:
        label, case = str(r["obj"]), str(r["case"])
        a = acc.setdefault((label, case), {"n": 0, **{k: 0.0 for k in SHELL_KEYS}})
        a["n"] += 1
        pk = peaks.setdefault(label, {k: 0.0 for k in SHELL_KEYS})
        for k in SHELL_KEYS:
            v = r.get(k, 0.0) or 0.0
            a[k] += v
            pk[k] = max(pk[k], abs(v))

    # 2) envolvente sobre casos, por elemento
    out: dict[str, dict] = {}
    for (label, case), a in acc.items():
        rec = out.get(label)
        if rec is None:
            rec = {k: Envelope() for k in SHELL_KEYS}
            rec["peak"] = peaks.get(label, {})
            rec["z"] = rec["y"] = None
            aid = _safe_int(label)
            if aid is not None and 1 <= aid <= len(model.areas):
                js = [model.get_joint(j) for j in model.areas[aid - 1].joints]
                rec["z"] = round(sum(j.z for j in js) / len(js), 3)
                rec["y"] = round(sum(j.y for j in js) / len(js), 3)
            out[label] = rec
        n = max(a["n"], 1)
        for k in SHELL_KEYS:
            rec[k].feed(a[k] / n, case)
    return out


def _safe_int(s: str) -> int | None:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Franjas de diseno de la pantalla
# --------------------------------------------------------------------------
def _interp(xs: list[float], ys: list[float], x: float) -> float:
    """Interpolacion lineal con extremos acotados (no extrapola)."""
    if not xs:
        return 0.0
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            dx = xs[i] - xs[i - 1]
            t = (x - xs[i - 1]) / dx if abs(dx) > 1e-12 else 0.0
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def wall_grid(model: M.StructuralModel, wall_env: dict[str, dict]) -> list[list[dict]]:
    """Reconstruye la malla mapeada de la pantalla a partir de la geometria.

    Devuelve una lista de columnas ordenadas en Y; cada columna es la lista de
    sus shells ordenados de abajo arriba. La malla del muro es mapeada (mismo
    numero de filas en toda la longitud), de modo que el indice de fila es
    comparable entre columnas aunque la corona sea inclinada o escalonada.
    """
    cols: dict[float, list[dict]] = {}
    for aid in model.group_element_ids(G_MURO, "Area"):
        env = wall_env.get(str(aid))
        if env is None:
            continue
        js = [model.get_joint(j) for j in model.areas[aid - 1].joints]
        ys = [j.y for j in js]
        zs = [j.z for j in js]
        cell = {
            "id": aid, "env": env,
            "y": round(sum(ys) / len(ys), 6), "z": sum(zs) / len(zs),
            "y_lo": min(ys), "y_hi": max(ys), "z_lo": min(zs), "z_hi": max(zs),
        }
        cols.setdefault(cell["y"], []).append(cell)
    out = [sorted(v, key=lambda c: c["z"]) for _, v in sorted(cols.items())]
    return [c for c in out if c]


def wall_design_strips(project: WallProject, model: M.StructuralModel,
                       wall_env: dict[str, dict], n_strips: int = 3) -> dict:
    """Diseno de la pantalla por franjas, con el momento en la cara del apoyo.

    Mejora el promediado global por dos vias:

    * **Franjas.** La altura se parte en bandas de filas de shells. Cada banda
      se arma con su propia solicitacion, en vez de extender a todo el muro el
      maximo absoluto: el acero vertical decrece hacia la corona, como el
      momento del voladizo.
    * **Cara del apoyo.** ACI 318 9.4.2.1 permite disenar con el momento en la
      cara del apoyo y no en su eje. En vertical la cara es el borde superior
      de la viga cabezal (z_base + h_viga/2); en horizontal, el borde de la
      pila (y_pila +/- D/2). Sobre el eje el momento del modelo de barras esta
      inflado por la singularidad del apoyo puntual.
    """
    grid = wall_grid(model, wall_env)
    if not grid:
        return {}

    nz = max(len(c) for c in grid)
    n_strips = max(1, min(n_strips, nz))
    fc = project.materials.concrete.fc
    fy = project.materials.rebar.fy
    t = project.wall.thickness
    cover = 0.05

    # Estacion de diseno: la de mayor altura de vastago, que es la que gobierna
    ys_borde = [c[0]["y_lo"] for c in grid] + [c[-1]["y_hi"] for c in grid]
    y_dis = max(ys_borde, key=lambda y: project.wall.crown_at(y) - project.wall.base_at(y))
    z_base_dis = project.wall.base_at(y_dis)
    z_crown_dis = project.wall.crown_at(y_dis)

    pile_ys = project.pile_y_positions()
    r_pile = project.piles.diameter / 2.0
    z_base = project.wall.z_base
    z_face = z_base + (project.cap_beam.depth / 2.0 if project.cap_beam.enabled else 0.0)

    # Reparto de filas en franjas: bandas contiguas de altura lo mas pareja posible
    bounds: list[tuple[int, int]] = []
    for s in range(n_strips):
        k0 = s * nz // n_strips
        k1 = (s + 1) * nz // n_strips
        if k1 > k0:
            bounds.append((k0, k1))

    # Curva M22(z) por columna, para poder cortar en la cara de la viga cabezal
    col_z = [[c["z"] for c in col] for col in grid]
    col_m22 = [[col[k]["env"]["M22"].abs_max for k in range(len(col))] for col in grid]

    franjas = []
    for si, (k0, k1) in enumerate(bounds, start=1):
        cells = [col[k] for col in grid for k in range(k0, min(k1, len(col)))]
        if not cells:
            continue
        # Las cotas de la franja se dan en la SECCION DE DISENO, la de mayor
        # altura, y se calculan de la geometria. Tomarlas como minimo y maximo
        # de los shells de la franja da rangos solapados en cuanto la corona o
        # la base van en pendiente, porque cada columna corta a distinta cota.
        z_ini = z_base_dis + (z_crown_dis - z_base_dis) * k0 / nz
        z_fin = z_base_dis + (z_crown_dis - z_base_dis) * k1 / nz

        # Con vastago acartelado cada franja tiene su espesor. Se toma el del pie
        # de la franja porque ahi es donde actua su momento de diseno: el momento
        # crece hacia abajo, y hacia abajo el muro engorda.
        t = project.wall.thickness_at_frac(k0 / nz) if project.wall.is_tapered \
            else project.wall.thickness

        # ---- vertical: M22 -----------------------------------------------
        m22 = max(c["env"]["M22"].abs_max for c in cells)
        es_base = si == 1
        m22_dis = m22
        cara_aplicada = False
        if es_base:
            # El momento de la franja inferior se reevalua en la cara de la viga.
            # Si la cara cae dentro del primer shell, su promedio ya representa
            # la franja y reducir mas seria inventar precision que la malla no da.
            vals = []
            for zs, ms in zip(col_z, col_m22):
                if not zs:
                    continue
                if z_face > zs[0] + 1e-9:
                    vals.append(_interp(zs, ms, z_face))
                    cara_aplicada = True
                else:
                    vals.append(ms[0])
            if vals:
                m22_dis = max(vals)
        fv = D.flexure_rect(m22_dis, 1.0, t, fc, fy, cover, "#5", is_slab=True)

        # ---- horizontal: M11 a lo largo de Y ------------------------------
        ys, m11_neg, m11_pos = [], [], []
        for col in grid:
            rows = col[k0:min(k1, len(col))]
            if not rows:
                continue
            ys.append(col[0]["y"])
            # Promedio en la franja: eso es exactamente la franja de diseno
            neg = sum(min(r["env"]["M11"].min, 0.0) for r in rows) / len(rows)
            pos = sum(max(r["env"]["M11"].max, 0.0) for r in rows) / len(rows)
            m11_neg.append(neg)
            m11_pos.append(pos)

        m11_eje = m11_cara = m11_vano = 0.0
        if ys:
            y_lo, y_hi = ys[0], ys[-1]
            for yp in pile_ys:
                if not (y_lo - 1e-9 <= yp <= y_hi + 1e-9):
                    continue
                m11_eje = max(m11_eje, abs(_interp(ys, m11_neg, yp)))
                for yf in (yp - r_pile, yp + r_pile):
                    if y_lo - 1e-9 <= yf <= y_hi + 1e-9:
                        m11_cara = max(m11_cara, abs(_interp(ys, m11_neg, yf)))
            lejos = [p for y, p in zip(ys, m11_pos)
                     if all(abs(y - yp) > r_pile for yp in pile_ys)]
            m11_vano = max(lejos) if lejos else max(m11_pos, default=0.0)
        m11_dis = m11_cara if m11_cara > 0.0 else m11_eje

        fh_neg = D.flexure_rect(m11_dis, 1.0, t, fc, fy, cover, "#5", is_slab=True)
        fh_pos = D.flexure_rect(m11_vano, 1.0, t, fc, fy, cover, "#5", is_slab=True)

        # ---- cortante transversal de la franja ----------------------------
        vmax = max(c["env"]["VMax"].abs_max for c in cells)
        sv = D.shear_check(vmax, 1.0, fv.d, fc, fy)

        def _arm(f):
            return {"As_req": f.As_req, "As_min": f.As_min, "As": f.As_prov,
                    "phiMn": f.phiMn, "ratio": f.ratio, "ok": f.ok,
                    "gobierna": "As minimo" if f.As_min >= f.As_req else "flexion",
                    "nota": f.note}

        franjas.append({
            "franja": si, "filas": [k0 + 1, k1], "n_shells": len(cells),
            "z_ini": round(z_ini, 3), "z_fin": round(z_fin, 3),
            "espesor": round(t, 3),
            "M22": round(m22, 2), "M22_diseno": round(m22_dis, 2),
            "cara_aplicada": cara_aplicada,
            "vertical": _arm(fv),
            "M11_eje": round(m11_eje, 2), "M11_cara": round(m11_cara, 2),
            "M11_vano": round(m11_vano, 2),
            "horizontal_apoyo": _arm(fh_neg), "horizontal_vano": _arm(fh_pos),
            "V": round(vmax, 2),
            "cortante": {"Vu": sv.Vu, "phiVc": sv.phiVc, "ratio": sv.ratio, "ok": sv.ok},
        })

    if not franjas:
        return {}

    reduccion_v = None
    base = franjas[0]
    if base["M22"] > 1e-9:
        reduccion_v = round(100.0 * (1.0 - base["M22_diseno"] / base["M22"]), 1)
    reduccion_h = None
    if base["M11_eje"] > 1e-9 and base["M11_cara"] > 1e-9:
        reduccion_h = round(100.0 * (1.0 - base["M11_cara"] / base["M11_eje"]), 1)

    return {
        "n_franjas": len(franjas),
        "n_filas": nz,
        "z_cara_viga": round(z_face, 3),
        "radio_pila": round(r_pile, 3),
        "reduccion_cara_vertical_pct": reduccion_v,
        "reduccion_cara_horizontal_pct": reduccion_h,
        "franjas": franjas,
        "As_vertical_max": max(f["vertical"]["As"] for f in franjas),
        "As_horizontal_max": max(max(f["horizontal_apoyo"]["As"], f["horizontal_vano"]["As"])
                                 for f in franjas),
        "nota": ("Cada franja se arma con su propia solicitacion. El momento vertical de "
                 "la franja inferior se toma en la cara de la viga cabezal y el horizontal "
                 "en la cara de la pila (ACI 318 9.4.2.1); los valores en el eje del apoyo "
                 "quedan como referencia."),
    }


# --------------------------------------------------------------------------
# Verificacion completa
# --------------------------------------------------------------------------
def verify(project: WallProject, model: M.StructuralModel,
           pile_rows: list[dict], beam_rows: list[dict], wall_rows: list[dict]) -> dict:
    """Corre las verificaciones ACI sobre las envolventes extraidas."""
    fc = project.materials.concrete.fc
    fy = project.materials.rebar.fy

    out: dict = {"pilas": [], "viga_cabezal": [], "muro": {}, "resumen": {},
                 "interaccion": {}, "envolventes": {"pilas": [], "viga_cabezal": []}}

    # ---- pilas -----------------------------------------------------------
    pile_env = frame_envelopes(pile_rows, model)
    pile_group_ids = {str(i) for i in model.group_element_ids(G_PILAS, "Frame")}
    idx_de = pile_index_map(model)
    worst_pile = None
    for label, ef in sorted(pile_env.items(), key=lambda kv: _safe_int(kv[0]) or 0):
        if pile_group_ids and label not in pile_group_ids:
            continue
        n_pila = idx_de.get(label, 1)
        zone = _zone_for_z(project, ef.z if ef.z is not None else project.piles.z_top,
                           n_pila)
        col = D.CircularColumn(
            D=project.piles.diameter, cover=zone.rebar.cover,
            num_bars=zone.rebar.num_bars, bar_size=zone.rebar.bar_size,
            tie_size=zone.rebar.tie_size, fc=fc, fy=fy,
        )
        # P en SAP es positivo en traccion para frames; se invierte a compresion positiva
        Pu = -ef.P.min if ef.P.min != float("inf") else 0.0
        Mu = max(ef.M2.abs_max, ef.M3.abs_max)
        Vu = max(ef.V2.abs_max, ef.V3.abs_max)
        chk = D.check_circular_column(col, Pu, Mu)
        shr = D.shear_circular(Vu, col, zone.rebar.tie_spacing)
        rec = {
            "elemento": label, "pila": n_pila, "z": ef.z, "y": ef.y,
            "seccion": zone.name,
            "Pu": chk.Pu, "Mu": chk.Mu, "phiMn": chk.phiMn, "ratio_PM": chk.ratio,
            "Vu": shr.Vu, "phiVn": shr.phiVn, "ratio_V": shr.ratio,
            "rho": chk.rho, "ok": chk.ok and shr.ok, "nota": shr.note,
        }
        out["pilas"].append(rec)
        out["envolventes"]["pilas"].append(ef.as_dict())
        # La curva de interaccion depende solo de la seccion, asi que se guarda
        # una por zona y no una por elemento: son 24 puntos, no 24 por pila.
        dia = out["interaccion"].setdefault(
            zone.name, {"D": project.piles.diameter, "num_bars": zone.rebar.num_bars,
                        "bar_size": zone.rebar.bar_size, "curva": chk.diagram,
                        "demanda": []})
        dia["demanda"].append([chk.Pu, chk.Mu, chk.ratio, label, ef.z, n_pila])
        if worst_pile is None or max(chk.ratio, shr.ratio) > worst_pile:
            worst_pile = max(chk.ratio, shr.ratio)

    # ---- viga cabezal ----------------------------------------------------
    beam_env = frame_envelopes(beam_rows, model)
    beam_ids = {str(i) for i in model.group_element_ids(G_VIGA, "Frame")}
    cb = project.cap_beam
    worst_beam = None
    for label, ef in sorted(beam_env.items(), key=lambda kv: _safe_int(kv[0]) or 0):
        if beam_ids and label not in beam_ids:
            continue
        # La viga cabezal flecta en los DOS planos y cada uno ve una seccion
        # distinta: el momento vertical (M2) trabaja contra el canto, y el
        # horizontal (M3), el que transfiere el empuje a las pilas, trabaja
        # contra el ancho. Disenar los dos con la misma orientacion —como se
        # hacia antes— arma el horizontal contra el canto y pide mucho mas acero
        # del necesario, ademas de mezclar dos armados que van en caras distintas.
        # Viga horizontal en SAP: el eje local 2 es el vertical y el 3 el
        # transversal horizontal. Por tanto M3 flecta en el plano vertical
        # (peso propio y reaccion del muro) y M2 en planta, que es el momento
        # con el que la viga lleva el empuje hasta las pilas.
        Mu_v, Mu_h = ef.M3.abs_max, ef.M2.abs_max
        Vu = max(ef.V2.abs_max, ef.V3.abs_max)
        flex = D.flexure_rect(Mu_v, cb.width, cb.depth, fc, fy,
                              cb.rebar.cover, cb.rebar.bar_size)
        flex_h = D.flexure_rect(Mu_h, cb.depth, cb.width, fc, fy,
                                cb.rebar.cover, cb.rebar.bar_size)
        Mu = max(Mu_v, Mu_h)
        Av_s = 2.0 * D.bar_area(cb.rebar.tie_size) / cb.rebar.tie_spacing
        shr = D.shear_check(Vu, cb.width, flex.d, fc, fy, Av_s_prov=Av_s)
        # La torsion de la viga cabezal es de EQUILIBRIO: nace del voladizo de la
        # pantalla y no tiene camino alterno, asi que no se redistribuye (22.7.5).
        tor = D.torsion_design(
            ef.T.abs_max, Vu, cb.width, cb.depth, flex.d, fc, fy, cb.rebar.cover,
            tie_size=cb.rebar.tie_size, long_bar_size=cb.rebar.bar_size,
            Av_s_req=shr.Av_s_req, compatibility=False,
        )
        rec = {
            "elemento": label, "y": ef.y,
            "Mu": flex.Mu, "As_req": flex.As_req, "As_min": flex.As_min,
            "phiMn": flex.phiMn, "ratio_M": flex.ratio,
            "Mu_h": flex_h.Mu, "As_req_h": flex_h.As_req, "As_min_h": flex_h.As_min,
            "phiMn_h": flex_h.phiMn, "ratio_M_h": flex_h.ratio,
            "Vu": shr.Vu, "Av_s_req": shr.Av_s_req, "phiVn": shr.phiVn, "ratio_V": shr.ratio,
            "Tu": tor.Tu, "T_umbral": tor.T_threshold, "T_cr": tor.T_cr,
            "Aoh": tor.Aoh, "ph": tor.ph, "Ao": tor.Ao,
            "torsion_significativa": tor.significant,
            "At_s": tor.At_s, "Avt_s_req": tor.Avt_s_req, "Avt_s_min": tor.Avt_s_min,
            "Avt_s": tor.Avt_s, "Al": tor.Al, "Al_min": tor.Al_min, "Al_adopt": tor.Al_adopt,
            "s_estribo": tor.s_req, "s_max": tor.s_max,
            "n_barras_torsion": tor.n_long_bars, "barra_torsion": tor.long_bar_size,
            "estribo": tor.tie_size, "ratio_VT": tor.stress_ratio, "seccion_VT_ok": tor.section_ok,
            "ok": flex.ok and flex_h.ok and shr.ok and tor.section_ok,
            "nota": " ".join(x for x in (flex.note, flex_h.note, shr.note, tor.note) if x),
        }
        out["viga_cabezal"].append(rec)
        out["envolventes"]["viga_cabezal"].append(ef.as_dict())
        ratios = [flex.ratio, shr.ratio, tor.stress_ratio]
        if worst_beam is None or max(ratios) > worst_beam:
            worst_beam = max(ratios)

    # ---- muro ------------------------------------------------------------
    wall_env = area_envelopes(wall_rows, model)
    if wall_env:
        m11 = max(v["M11"].abs_max for v in wall_env.values())
        m22 = max(v["M22"].abs_max for v in wall_env.values())
        crit11 = max(wall_env.items(), key=lambda kv: kv[1]["M11"].abs_max)
        crit22 = max(wall_env.items(), key=lambda kv: kv[1]["M22"].abs_max)
        pk11 = max(v["peak"].get("M11", 0.0) for v in wall_env.values())
        pk22 = max(v["peak"].get("M22", 0.0) for v in wall_env.values())
        t = project.wall.thickness
        cover_wall = 0.05
        f11 = D.flexure_rect(m11, 1.0, t, fc, fy, cover_wall, "#5", is_slab=True)
        f22 = D.flexure_rect(m22, 1.0, t, fc, fy, cover_wall, "#5", is_slab=True)
        # Cortante transversal del shell (V13/V23), no las fuerzas de membrana
        vmax = max(v["VMax"].abs_max for v in wall_env.values())
        pkv = max(v["peak"].get("VMax", 0.0) for v in wall_env.values())
        shr = D.shear_check(vmax, 1.0, f11.d, fc, fy)
        out["muro"] = {
            "M11_max": round(m11, 2), "area_M11": crit11[0],
            "M22_max": round(m22, 2), "area_M22": crit22[0],
            "pico_M11": round(pk11, 2), "pico_M22": round(pk22, 2), "pico_V": round(pkv, 2),
            "horizontal": {"As_req": f11.As_req, "As_min": f11.As_min, "As": f11.As_prov,
                           "phiMn": f11.phiMn, "ratio": f11.ratio, "ok": f11.ok,
                           "gobierna": "As minimo" if f11.As_min >= f11.As_req else "flexion"},
            "vertical": {"As_req": f22.As_req, "As_min": f22.As_min, "As": f22.As_prov,
                         "phiMn": f22.phiMn, "ratio": f22.ratio, "ok": f22.ok,
                         "gobierna": "As minimo" if f22.As_min >= f22.As_req else "flexion"},
            "cortante": {"Vu": shr.Vu, "phiVc": shr.phiVc, "ratio": shr.ratio, "ok": shr.ok},
            "nota": ("Valores promediados por elemento. Los picos nodales sobre los apoyos "
                     "son singularidades de malla y no deben usarse como solicitacion de diseno."),
        }
        # Valor por elemento, para poder pintar el mapa de solicitaciones en la
        # interfaz sin volver a pedirle nada a SAP.
        out["muro"]["elementos"] = [
            {"id": _safe_int(k), "y": v["z"] and v["y"], "z": v["z"],
             "M11": round(v["M11"].abs_max, 2), "M22": round(v["M22"].abs_max, 2),
             "M11_min": round(v["M11"].min, 2) if v["M11"].min != float("inf") else 0.0,
             "M11_max": round(v["M11"].max, 2) if v["M11"].max != float("-inf") else 0.0,
             "V": round(v["VMax"].abs_max, 2)}
            for k, v in sorted(wall_env.items(), key=lambda kv: _safe_int(kv[0]) or 0)
            if _safe_int(k) is not None
        ]

        franjas = wall_design_strips(project, model, wall_env,
                                     project.mesh.wall_design_strips)
        if franjas:
            out["muro"]["franjas"] = franjas

    # ---- una ficha por pila ----------------------------------------------
    # Las pilas de un mismo muro no son intercambiables: distinta longitud,
    # distinta cabeza y distinta demanda. Agrupar solo por zona escondia eso.
    out["pilas_resumen"] = pilas_por_pila(project, model, out["pilas"])

    # En el muro la flexion se *disena* (se calcula el acero necesario), asi que su
    # relacion D/C vale 1.00 por construccion cuando manda As_req y no es un
    # chequeo. El unico D/C con significado es el de cortante, que no lleva
    # refuerzo transversal.
    muro_checks = (
        [out["muro"][k] for k in ("horizontal", "vertical", "cortante")] if out["muro"] else []
    )
    out["resumen"] = {
        "ratio_max_pilas": round(worst_pile, 3) if worst_pile is not None else None,
        "ratio_max_viga": round(worst_beam, 3) if worst_beam is not None else None,
        "ratio_cortante_muro": out["muro"]["cortante"]["ratio"] if out["muro"] else None,
        "no_conformes_pilas": sum(1 for r in out["pilas"] if not r["ok"]),
        "no_conformes_viga": sum(1 for r in out["viga_cabezal"] if not r["ok"]),
        "no_conformes_muro": sum(1 for c in muro_checks if not c["ok"]),
        "torsion_viga_significativa": any(
            r.get("torsion_significativa") for r in out["viga_cabezal"]
        ),
    }

    # Envolvente del diseno por torsion: el estribo y el longitudinal que
    # gobiernan toda la viga, que es lo que acaba en el plano.
    tor_recs = [r for r in out["viga_cabezal"] if r.get("torsion_significativa")]
    if tor_recs:
        crit = max(tor_recs, key=lambda r: r["Tu"])
        out["torsion_viga"] = {
            "elemento_critico": crit["elemento"], "y": crit["y"],
            "Tu": crit["Tu"], "T_umbral": crit["T_umbral"], "T_cr": crit["T_cr"],
            "Aoh": crit["Aoh"], "ph": crit["ph"], "Ao": crit["Ao"],
            "At_s": max(r["At_s"] for r in tor_recs),
            "Avt_s": max(r["Avt_s"] for r in tor_recs),
            "Avt_s_min": crit["Avt_s_min"],
            "Al": max(r["Al_adopt"] for r in tor_recs),
            "estribo": crit["estribo"],
            "s_estribo": min(r["s_estribo"] for r in tor_recs),
            "s_max": crit["s_max"],
            "barra_torsion": crit["barra_torsion"],
            "n_barras_torsion": max(r["n_barras_torsion"] for r in tor_recs),
            "ratio_VT": max(r["ratio_VT"] for r in tor_recs),
            "seccion_ok": all(r["seccion_VT_ok"] for r in tor_recs),
            "n_elementos": len(tor_recs),
            "nota": crit["nota"],
        }
    out["resumen"]["elementos_no_conformes"] = (
        out["resumen"]["no_conformes_pilas"]
        + out["resumen"]["no_conformes_viga"]
        + out["resumen"]["no_conformes_muro"]
    )
    return out



def pilas_por_pila(project: WallProject, model: M.StructuralModel,
                   recs: list[dict]) -> list[dict]:
    """Una ficha por pila: geometria, solicitaciones y el D/C que gobierna.

    Es lo que hace falta para mirar pila por pila en vez de quedarse con el
    maximo del grupo, que en un muro de altura variable no representa a
    ninguna: la primera pila puede pedir la mitad de acero que la ultima.
    """
    ys = project.pile_y_positions()
    cabezas = project.piles.z_tops(project.wall, ys)
    por_pila: dict[int, list[dict]] = {}
    for r in recs:
        por_pila.setdefault(r.get("pila") or 1, []).append(r)

    fichas = []
    for n in sorted(por_pila):
        grupo = por_pila[n]
        i = n - 1
        z_top = cabezas[i] if i < len(cabezas) else project.piles.z_top
        z_bot = project.piles.z_bot_of(i)
        crit_pm = max(grupo, key=lambda r: r["ratio_PM"])
        crit_v = max(grupo, key=lambda r: r["ratio_V"])
        # Cota del momento maximo: donde hay que garantizar el armado superior
        crit_m = max(grupo, key=lambda r: abs(r["Mu"]))
        fichas.append({
            "pila": n,
            "y": round(ys[i], 3) if i < len(ys) else None,
            "z_cabeza": round(z_top, 3),
            "z_punta": round(z_bot, 3),
            "longitud": round(z_top - z_bot, 3),
            "diametro": project.piles.diameter,
            "n_elementos": len(grupo),
            "zonas": [z.name for z in project.piles.zones_of(n)],
            "Pu_max": round(max(r["Pu"] for r in grupo), 2),
            "Mu_max": round(max(abs(r["Mu"]) for r in grupo), 2),
            "z_Mu_max": crit_m["z"],
            "Vu_max": round(max(abs(r["Vu"]) for r in grupo), 2),
            "ratio_PM": round(crit_pm["ratio_PM"], 3),
            "ratio_V": round(crit_v["ratio_V"], 3),
            "seccion_critica": crit_pm["seccion"],
            "z_critica": crit_pm["z"],
            "rho": crit_pm["rho"],
            "ok": all(r["ok"] for r in grupo),
        })
    return fichas

def _zone_for_z(project: WallProject, z: float, n: int = 1):
    """Zona que arma la cota z de la pila n (desde 1)."""
    return project.piles.zone_at(n, z)


def pile_index_map(model: M.StructuralModel) -> dict[str, int]:
    """Elemento de frame -> numero de pila, leido de los grupos PILA_xx.

    El constructor mete los frames de cada pila en su grupo, asi que no hace
    falta adivinar por coordenadas: la pertenencia ya esta en el modelo.
    """
    out: dict[str, int] = {}
    for g, kind, eid in model.group_members:
        if kind == "Frame" and g.startswith("PILA_"):
            try:
                out[str(eid)] = int(g.split("_")[1])
            except (IndexError, ValueError):
                continue
    return out


# --------------------------------------------------------------------------
# Orquestacion contra SAP
# --------------------------------------------------------------------------
def _read_modal(driver, case: str, combos: list[str]) -> dict:
    """Periodos y masa participante del caso modal.

    Hay que seleccionar el caso modal solo, porque la salida de resultados es
    global al modelo; despues se restaura la seleccion de combinaciones.
    """
    driver.select_output([case], envelopes=False)
    try:
        periodos = driver.modal_periods()
        try:
            masas = {r["modo"]: r for r in driver.modal_mass_ratios()}
        except Exception:
            masas = {}
    finally:
        driver.select_output(combos)

    modos = []
    for r in periodos:
        mm = masas.get(r["modo"], {})
        modos.append({
            "modo": r["modo"], "T": round(r["T"], 4), "f": round(r["f"], 4),
            "Ux": round(mm.get("Ux", 0.0), 4), "Uy": round(mm.get("Uy", 0.0), 4),
            "Uz": round(mm.get("Uz", 0.0), 4),
            "SumUx": round(mm.get("SumUx", 0.0), 4),
            "SumUy": round(mm.get("SumUy", 0.0), 4),
            "SumUz": round(mm.get("SumUz", 0.0), 4),
        })
    if not modos:
        return {}
    dom_x = max(modos, key=lambda r: r["Ux"])
    dom_y = max(modos, key=lambda r: r["Uy"])
    ult = modos[-1]
    return {
        "caso": case, "n_modos": len(modos),
        "T1": modos[0]["T"],
        "modo_dominante_X": dom_x["modo"], "T_dominante_X": dom_x["T"],
        "modo_dominante_Y": dom_y["modo"], "T_dominante_Y": dom_y["T"],
        "masa_acumulada_X": ult["SumUx"], "masa_acumulada_Y": ult["SumUy"],
        "modos": modos,
        "nota": ("La masa proviene del peso propio de los elementos. Si la masa "
                 "acumulada no llega a 0.90 en la direccion de interes, amplie el "
                 "numero de modos."),
    }


# SAP devuelve las areas de acero en las unidades activas (kN, m): m2 para areas
# y m2/m para las cuantias por unidad de longitud. Se pasan a mm2 y mm2/m.
_M2_A_MM2 = 1.0e6


def _read_sap_design(driver, model: M.StructuralModel) -> dict:
    """Corre el diseno de concreto de SAP y devuelve su resumen.

    Sirve de contraste independiente: el acero por torsion que calcula
    `design.torsion_design` deberia quedar del mismo orden que el TLArea/TTArea
    que reporta SAP para la viga cabezal.
    """
    out: dict = {"codigo": driver.run_concrete_design()}

    vigas = model.group_element_ids(G_VIGA, "Frame")
    if vigas:
        vig = driver.design_results_beam(vigas)
        if not vig:
            # No deberia pasar: `SapDriver.set_beam_sections` marca la seccion
            # como de viga antes de disenar. Si pasa, SAP la habra tratado como
            # columna y no habra torsion que contrastar.
            out["viga_cabezal_no_disponible"] = (
                "SAP no devolvio diseno de viga para la viga cabezal, asi que no "
                "hay refuerzo por torsion con el que contrastar. Revise que la "
                "seccion este marcada como seccion de viga."
            )
        out["viga_cabezal"] = [
            {"frame": r["frame"], "x": round(r["x"], 3),
             "As_sup": round(r["As_sup"] * _M2_A_MM2, 1),
             "As_inf": round(r["As_inf"] * _M2_A_MM2, 1),
             "Av_s": round(r["Av_s"] * _M2_A_MM2, 1),
             "Al_torsion": round(r["Al_torsion"] * _M2_A_MM2, 1),
             "At_s_torsion": round(r["At_s_torsion"] * _M2_A_MM2, 1),
             "error": r["error"], "aviso": r["aviso"]}
            for r in vig
        ]
    pilas = model.group_element_ids(G_PILAS, "Frame")
    if pilas:
        col = driver.design_results_column(pilas)
        out["pilas"] = [
            {"frame": r["frame"], "x": round(r["x"], 3),
             "As_PMM": round(r["As_PMM"] * _M2_A_MM2, 1),
             "ratio_PMM": round(r["ratio_PMM"], 3),
             "Av_s_mayor": round(r["Av_s_mayor"] * _M2_A_MM2, 1),
             "error": r["error"], "aviso": r["aviso"]}
            for r in col
        ]
    return out


def _compare_torsion(propio: dict | None, sap: dict | None) -> dict | None:
    """Contrasta el diseno por torsion propio con el que reporta SAP.

    Devuelve None si SAP no diseno la viga como viga: en ese caso no hay
    TLArea/TTArea y el motivo queda en `diseno_sap.viga_cabezal_no_disponible`.
    """
    if not propio or not sap or not sap.get("viga_cabezal"):
        return None
    filas = sap["viga_cabezal"]
    al_sap = max((r["Al_torsion"] for r in filas), default=0.0)
    at_sap = max((r["At_s_torsion"] for r in filas), default=0.0)
    al_pro = propio.get("Al", 0.0)
    at_pro = propio.get("At_s", 0.0)

    def dif(a, b):
        return round(100.0 * (a - b) / b, 1) if b else None

    return {
        "codigo_sap": sap.get("codigo"),
        "Al_propio": al_pro, "Al_sap": al_sap, "dif_Al_pct": dif(al_pro, al_sap),
        "At_s_propio": at_pro, "At_s_sap": at_sap, "dif_At_s_pct": dif(at_pro, at_sap),
        "nota": ("Al es el longitudinal total por torsion en mm2 y At/s el transversal "
                 "por rama en mm2/m. Diferencias moderadas son esperables: SAP disena "
                 "estacion a estacion con sus propias combinaciones y aqui se toma la "
                 "envolvente del elemento."),
    }

def run_and_verify(driver, project: WallProject, model: M.StructuralModel,
                   combos: list[str] | None = None, run: bool = True,
                   design: bool = True) -> dict:
    """Corre el analisis y devuelve envolventes y verificaciones.

    Con run=False se reutilizan los resultados ya presentes en el modelo.
    Con design=True se lanza ademas el diseno de concreto de SAP y se contrasta
    con el calculo propio.
    """
    if run:
        driver.run_analysis()
    combo_names = combos or [c.name for c in model.combos] or [c.name for c in model.load_cases]
    driver.select_output(combo_names)

    # Cada lector se aisla: la firma de las funciones de resultados cambia entre
    # versiones del OAPI, y un fallo en uno no debe tirar el resto del reporte.
    problems: list[str] = []

    def safe(label, fn, default):
        try:
            return fn()
        except Exception as exc:
            problems.append("%s: %s" % (label, exc))
            return default

    pile_rows = safe("fuerzas en pilas", lambda: driver.frame_forces(G_PILAS), [])
    beam_rows = (
        safe("fuerzas en viga cabezal", lambda: driver.frame_forces(G_VIGA), [])
        if model.group_element_ids(G_VIGA, "Frame") else []
    )
    wall_rows = safe("fuerzas en el muro", lambda: driver.area_forces(G_MURO), [])
    cuts = safe("section cuts", driver.section_cut_forces, [])
    reactions = safe("reacciones", lambda: driver.joint_reactions(G_APOYOS), [])

    checks = verify(project, model, pile_rows, beam_rows, wall_rows)
    checks["section_cuts"] = cuts
    checks["combos_evaluadas"] = combo_names
    if reactions:
        # Una suma unica mezclaria todas las combinaciones; se agrupa por caso.
        por_caso: dict[str, float] = {}
        for r in reactions:
            por_caso[r["case"]] = por_caso.get(r["case"], 0.0) + r["F3"]
        checks["reaccion_vertical"] = {k: round(v, 2) for k, v in sorted(por_caso.items())}

    if model.modal_cases:
        modal = safe("resultados modales",
                     lambda: _read_modal(driver, model.modal_cases[0].name, combo_names), {})
        if modal:
            checks["modal"] = modal

    if design:
        sap_design = safe("diseno de concreto de SAP",
                          lambda: _read_sap_design(driver, model), {})
        if sap_design:
            checks["diseno_sap"] = sap_design
            cmp_tor = _compare_torsion(checks.get("torsion_viga"), sap_design)
            if cmp_tor:
                checks["comparacion_torsion"] = cmp_tor

    if problems:
        checks["lecturas_fallidas"] = problems
    return checks

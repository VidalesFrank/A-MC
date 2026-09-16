"""Generador: WallProject (parametros) -> StructuralModel (modelo neutro).

Convenio geometrico
-------------------
El modelo es plano en X: el eje de pilas, la viga cabezal y la pantalla estan
todos en X = 0. El muro se desarrolla en Y (longitud) y Z (altura, positiva
hacia arriba, cotas absolutas).

Los shells se generan con el orden de nudos inferior-izq, inferior-der,
superior-der, superior-izq, con lo que el eje local 3 apunta a +X y la cara
"Top" mira al trasdos. Una presion positiva sobre la cara Top empuja hacia -X,
que es el sentido del empuje del relleno.
"""
from __future__ import annotations

import math

from . import model as M
from .params import WallProject
from .soil import PressureProfile, lateral_spring, tip_spring

# Nombres canonicos
PAT_DEAD = "DEAD"
PAT_SUELO = "SUELO"
PAT_SOBRECARGA = "SOBRECARGA"
PAT_AGUA = "AGUA"
PAT_SISMO = "SISMO_SUELO"

JP_EMPUJE = "EMPUJE"
JP_AGUA = "PRESION_AGUA"
JP_SISMO = "EMPUJE_DIN"

G_PILAS = "PILAS"
G_VIGA = "VIGA_CABEZAL"
G_MURO = "MURO"
G_MURO_BASE = "MURO_BASE"
G_APOYOS = "APOYOS"
G_CORTE_MURO = "CORTE_MURO_BASE"
G_CORTE_PILAS = "CORTE_PILAS_CABEZA"


class BuildResult:
    def __init__(self, model: M.StructuralModel, warnings: list[str], report: dict) -> None:
        self.model = model
        self.warnings = warnings
        self.report = report


def build(project: WallProject) -> BuildResult:
    p = project
    warnings: list[str] = []
    m = M.StructuralModel(p.info.name)

    _validate(p, warnings)

    press = PressureProfile(p)

    _materials_and_sections(p, m)
    y_grid, pile_ys = _y_grid(p)
    _grid_lines(p, m, pile_ys)

    wall_cols = _build_wall(p, m, y_grid)
    _build_piles(p, m, pile_ys, warnings)
    _build_cap_beam(p, m, pile_ys, warnings)
    _springs(p, m, pile_ys)
    _loads(p, m, press, wall_cols)
    _combos(p, m)
    _analysis_cases(p, m, warnings)
    _section_cuts(p, m, wall_cols, pile_ys)

    report = _report(p, m, press)
    m.meta = {"warnings": warnings, "report": report}
    return BuildResult(m, warnings, report)


# --------------------------------------------------------------------------
# Validacion
# --------------------------------------------------------------------------
def _validate(p: WallProject, warnings: list[str]) -> None:
    sigue_base = bool(p.wall.base_profile)
    if not sigue_base:
        if p.cap_beam.enabled and abs((p.cap_beam.z or 0.0) - p.wall.z_base) > 1e-6:
            warnings.append(
                "La viga cabezal esta en Z=%.3f y la base del muro en Z=%.3f: los shells no se conectaran a la viga."
                % (p.cap_beam.z, p.wall.z_base)
            )
        if abs(p.piles.z_top - p.wall.z_base) > 1e-6:
            warnings.append(
                "La cabeza de pila (Z=%.3f) no coincide con la base del muro (Z=%.3f)."
                % (p.piles.z_top, p.wall.z_base)
            )
    cover = [l for l in p.soil.layers]
    if cover:
        zmin = min(l.z_bot for l in cover)
        if zmin > p.piles.z_bot_min + 1e-6:
            warnings.append(
                "Los estratos solo llegan a Z=%.2f y la punta de pila esta en Z=%.2f: "
                "se usaran valores de balasto por defecto en el tramo sin definir."
                % (zmin, p.piles.z_bot_min)
            )
    if p.wall.is_drawn:
        ys = [pt[0] for pt in p.wall.crown_profile]
        if len(set(ys)) != len(ys):
            warnings.append("El perfil de corona tiene abscisas Y repetidas; se interpolara con la ultima.")


# --------------------------------------------------------------------------
# Materiales y secciones
# --------------------------------------------------------------------------
def _materials_and_sections(p: WallProject, m: M.StructuralModel) -> None:
    c = p.materials.concrete
    r = p.materials.rebar
    m.concrete.append(
        M.ConcreteMaterial(c.name, c.fc, c.E_calc, c.nu, c.G, c.gamma, c.mass_density, c.alpha)
    )
    m.rebar.append(M.RebarMaterial(r.name, r.fy, r.fu, r.E, r.gamma, r.mass_density, r.alpha))

    for z in p.piles.zones:
        m.circle_sections.append(
            M.CircleSection(
                name=z.name,
                material=c.name,
                diameter=p.piles.diameter,
                cover=z.rebar.cover,
                num_bars=z.rebar.num_bars,
                bar_size=z.rebar.bar_size,
                tie_size=z.rebar.tie_size,
                tie_spacing=z.rebar.tie_spacing,
            )
        )

    if p.cap_beam.enabled:
        cb = p.cap_beam
        m.rect_sections.append(
            M.RectSection(
                name=cb.name,
                material=c.name,
                depth=cb.depth,
                width=cb.width,
                cover=cb.rebar.cover,
                num_bars_3=cb.rebar.num_bars_3,
                num_bars_2=cb.rebar.num_bars_2,
                bar_size=cb.rebar.bar_size,
                tie_size=cb.rebar.tie_size,
                tie_spacing=cb.rebar.tie_spacing,
            )
        )

    # Con vastago acartelado hace falta una seccion por fila de la malla: SAP no
    # admite espesor variable dentro de un shell, de modo que el acartelamiento
    # se representa escalonado, cada fila con su espesor medio.
    for nombre, esp in _wall_sections(p):
        m.shell_sections.append(
            M.ShellSection(
                name=nombre,
                material=c.name,
                thickness=esp,
                shell_type=p.wall.shell_type,
                rebar_material=r.name,
            )
        )


def _wall_rows(p: WallProject) -> int:
    """Numero de filas de shell en altura, comun a todas las columnas."""
    w = p.wall
    ys = _y_grid(p)[0]
    h_max = max([w.crown_at(y) - w.base_at(y) for y in ys] or [0.0])
    if h_max <= 1e-9:
        return 0
    return max(1, int(math.ceil(h_max / p.mesh.wall_target_dz - 1e-9)))


def _wall_sections(p: WallProject) -> list[tuple[str, float]]:
    """(nombre, espesor) de cada fila, de abajo arriba. Una sola si no hay acartelamiento."""
    if not p.wall.is_tapered:
        return [(p.wall.name, p.wall.thickness)]
    nz = _wall_rows(p)
    out = []
    for k in range(nz):
        esp = p.wall.thickness_at_frac((k + 0.5) / nz)
        out.append(("%s_%02d" % (p.wall.name, k + 1), round(esp, 4)))
    return out


# --------------------------------------------------------------------------
# Mallado en Y
# --------------------------------------------------------------------------
def _y_grid(p: WallProject) -> tuple[list[float], list[float]]:
    """Devuelve (abscisas de todos los nudos en Y, abscisas de pilas)."""
    pile_ys = p.pile_y_positions()
    n = max(p.mesh.wall_div_per_bay, 1)

    # El muro puede volar por fuera de las pilas extremas. Esos voladizos son
    # parte de la pantalla y tienen que mallarse, o el muro saldria corto.
    est = list(pile_ys)
    y0, y1 = p.wall.y_start, p.wall.y_end
    if y0 < est[0] - 1e-9:
        est.insert(0, y0)
    if y1 > est[-1] + 1e-9:
        est.append(y1)

    vanos = [b - a for a, b in zip(pile_ys, pile_ys[1:])]
    ref = sum(vanos) / len(vanos) if vanos else (est[-1] - est[0])

    grid: list[float] = []
    for a, b in zip(est, est[1:]):
        # Elementos de tamano parecido en todo el muro: el voladizo se divide en
        # proporcion a su longitud, no en el mismo numero de partes que un vano.
        nd = max(1, int(round(n * (b - a) / ref))) if ref > 1e-9 else n
        for k in range(nd):
            grid.append(a + (b - a) * k / nd)
    grid.append(est[-1])
    return grid, pile_ys


def _grid_lines(p: WallProject, m: M.StructuralModel, pile_ys: list[float]) -> None:
    half = (p.cap_beam.width if p.cap_beam.enabled else p.wall.thickness) / 2.0
    m.grid_lines.append(M.GridLine("X", "A", -half))
    m.grid_lines.append(M.GridLine("X", "B", 0.0))
    m.grid_lines.append(M.GridLine("X", "C", half))
    for i, y in enumerate(pile_ys, start=1):
        m.grid_lines.append(M.GridLine("Y", str(i), y))
    zs = sorted({p.piles.z_bot_min, p.wall.z_base, p.wall.z_top}
                | {l.z_top for l in p.soil.layers})
    for i, z in enumerate(zs, start=1):
        m.grid_lines.append(M.GridLine("Z", "Z%d" % i, z))


# --------------------------------------------------------------------------
# Pantalla
# --------------------------------------------------------------------------
class WallColumn:
    """Franja vertical de shells entre dos abscisas Y consecutivas."""

    def __init__(self, y_left: float, y_right: float) -> None:
        self.y_left = y_left
        self.y_right = y_right
        self.areas: list[int] = []

    @property
    def y_mid(self) -> float:
        return 0.5 * (self.y_left + self.y_right)


def _build_wall(p: WallProject, m: M.StructuralModel, y_grid: list[float]) -> list[WallColumn]:
    """Malla mapeada: todas las columnas se dividen en el mismo numero de filas,
    de modo que los nudos coinciden aunque la corona sea inclinada o escalonada."""
    w = p.wall
    heights = [w.crown_at(y) - w.base_at(y) for y in y_grid]
    h_max = max(heights) if heights else 0.0
    if h_max <= 1e-9:
        return []
    nz = max(1, int(math.ceil(h_max / p.mesh.wall_target_dz - 1e-9)))
    secs = _wall_sections(p)

    # Nudos por abscisa
    node_cols: list[list[int]] = []
    for y in y_grid:
        zb, zt = w.base_at(y), w.crown_at(y)
        col = [m.add_joint(0.0, y, zb + (zt - zb) * k / nz) for k in range(nz + 1)]
        node_cols.append(col)

    columns: list[WallColumn] = []
    for ci in range(len(y_grid) - 1):
        left, right = node_cols[ci], node_cols[ci + 1]
        col = WallColumn(y_grid[ci], y_grid[ci + 1])
        # Columna degenerada (muro de altura nula en ambos extremos)
        if heights[ci] <= 1e-9 and heights[ci + 1] <= 1e-9:
            columns.append(col)
            continue
        for k in range(nz):
            sec = secs[k][0] if k < len(secs) else secs[-1][0]
            aid = m.add_area([left[k], right[k], right[k + 1], left[k + 1]], sec, G_MURO)
            col.areas.append(aid)
            if k == 0:
                m.add_to_group(G_MURO_BASE, "Area", aid)
        columns.append(col)
    return columns


# --------------------------------------------------------------------------
# Pilas
# --------------------------------------------------------------------------
def _pile_section_at(p: WallProject, z: float, n: int = 1) -> str:
    """Seccion de la pila n (desde 1) a la cota z."""
    return p.piles.zone_at(n, z).name


def _pile_levels(p: WallProject, i: int = 0, z_top: float | None = None) -> list[float]:
    zt = p.piles.z_top if z_top is None else z_top
    zb = p.piles.z_bot_of(i)
    L = zt - zb
    n = max(1, int(round(L / p.mesh.pile_segment)))
    return [zt - L * k / n for k in range(n + 1)]


def _build_piles(p: WallProject, m: M.StructuralModel, pile_ys: list[float], warnings: list[str]) -> None:
    tops = p.piles.z_tops(p.wall, pile_ys)
    for idx, y in enumerate(pile_ys, start=1):
        levels = _pile_levels(p, idx - 1, tops[idx - 1])
        gname = "PILA_%02d" % idx
        nodes = [m.add_joint(0.0, y, z) for z in levels]
        for k in range(len(levels) - 1):
            zmid = 0.5 * (levels[k] + levels[k + 1])
            sec = _pile_section_at(p, zmid, idx)
            fid = m.add_frame(nodes[k + 1], nodes[k], sec, group=G_PILAS)
            m.add_to_group(gname, "Frame", fid)


# --------------------------------------------------------------------------
# Viga cabezal
# --------------------------------------------------------------------------
def _build_cap_beam(p: WallProject, m: M.StructuralModel, pile_ys: list[float], warnings: list[str]) -> None:
    if not p.cap_beam.enabled:
        return
    ys = list(pile_ys)
    if p.cap_beam.overhangs:
        # La viga llega hasta los extremos del muro. Con las pilas en los
        # extremos no anade nada; con voladizo, es el tramo que arma el arranque.
        y0, y1 = p.wall.y_start, p.wall.y_end
        if y0 < ys[0] - 1e-9:
            ys.insert(0, y0)
        if y1 > ys[-1] + 1e-9:
            ys.append(y1)
    # Con base del muro inclinada la viga se desplanta en el fondo de la
    # excavacion y va en pendiente; si no, queda horizontal como siempre.
    def _z(y: float) -> float:
        return p.wall.base_at(y) if p.wall.base_profile else (p.cap_beam.z or 0.0)

    for a, b in zip(ys, ys[1:]):
        ja = m.add_joint(0.0, a, _z(a))
        jb = m.add_joint(0.0, b, _z(b))
        m.add_frame(ja, jb, p.cap_beam.name, auto_mesh_at_joints=True, group=G_VIGA)


# --------------------------------------------------------------------------
# Resortes de balasto
# --------------------------------------------------------------------------
def _springs(p: WallProject, m: M.StructuralModel, pile_ys: list[float]) -> None:
    D = p.piles.diameter
    tops = p.piles.z_tops(p.wall, pile_ys)
    for i, y in enumerate(pile_ys):
        levels = _pile_levels(p, i, tops[i])
        for k, z in enumerate(levels):
            if k == 0 and p.piles.skip_head_spring:
                continue
            above = levels[k - 1] - z if k > 0 else 0.0
            below = z - levels[k + 1] if k < len(levels) - 1 else 0.0
            trib = 0.5 * (above + below)
            if p.soil.nh:
                # Matlock y Reese: el modulo crece con la profundidad bajo la
                # cabeza de esta pila, no bajo una cota comun.
                ks_h = p.soil.nh * max(tops[i] - z, 0.0) / D
            else:
                ks_h = p.soil.ks_h_at(z)
            kl = lateral_spring(ks_h, D, trib)
            kv = 0.0
            es_punta = k == len(levels) - 1
            if es_punta and not p.piles.tip_restraint:
                kv = (
                    p.piles.tip_spring_kv
                    if p.piles.tip_spring_kv is not None
                    else tip_spring(p.soil.ks_v_at(z), D)
                )
            jid = m.add_joint(0.0, y, z)
            if es_punta and p.piles.tip_restraint:
                # Solo el apoyo vertical de punta se modela rigido. El fuste no
                # lleva ninguna restriccion: su unica rigidez es el balasto, que
                # es lo que representa el resorte lateral.
                m.restraints.append(M.Restraint(joint=jid, u3=True))
            m.springs.append(M.Spring(joint=jid, u1=kl, u2=kl, u3=kv))
            # Grupo de apoyos: permite leer reacciones y contrastarlas con el peso propio
            m.add_to_group(G_APOYOS, "Joint", jid)


# --------------------------------------------------------------------------
# Cargas
# --------------------------------------------------------------------------
def _loads(p: WallProject, m: M.StructuralModel, press: PressureProfile, columns: list[WallColumn]) -> None:
    m.add_load_pattern(PAT_DEAD, "Dead", 1.0)
    m.add_load_pattern(PAT_SUELO, "Other", 0.0)
    m.load_cases.append(M.LoadCase(PAT_DEAD, PAT_DEAD, 1.0, "Dead"))
    m.load_cases.append(M.LoadCase(PAT_SUELO, PAT_SUELO, 1.0))
    m.add_joint_pattern(JP_EMPUJE)

    use_surcharge = abs(p.earth.surcharge) > 1e-9
    use_water = p.soil.water_table_z is not None and p.soil.water_table_z > p.wall.z_base + 1e-9
    use_seismic = p.seismic.enabled and press.dK > 0.0

    if use_surcharge:
        m.add_load_pattern(PAT_SOBRECARGA, "Other", 0.0)
        m.load_cases.append(M.LoadCase(PAT_SOBRECARGA, PAT_SOBRECARGA, 1.0))
    if use_water:
        m.add_load_pattern(PAT_AGUA, "Other", 0.0)
        m.load_cases.append(M.LoadCase(PAT_AGUA, PAT_AGUA, 1.0))
        m.add_joint_pattern(JP_AGUA)
    if use_seismic:
        m.add_load_pattern(PAT_SISMO, "Other", 0.0)
        caso = M.LoadCase(PAT_SISMO, PAT_SISMO, 1.0)
        if p.seismic.include_inertia and abs(p.seismic.kh) > 1e-9:
            # Inercia del propio muro: una aceleracion +UX genera fuerzas hacia
            # -X, el mismo sentido en que empuja el relleno.
            caso.accels.append(("UX", p.seismic.kh))
        m.load_cases.append(caso)
        m.add_joint_pattern(JP_SISMO)

    # Valores de joint pattern: presion real en kPa nodo a nodo
    wall_joint_ids = sorted({j for c in columns for a in c.areas for j in m.areas[a - 1].joints})
    for jid in wall_joint_ids:
        jt = m.get_joint(jid)
        zc = p.wall.crown_at(jt.y)
        zb = p.wall.base_at(jt.y)
        res = press.at(jt.z, zc, zb)
        m.pattern_values.append(M.JointPatternValue(jid, JP_EMPUJE, round(res.soil, 6)))
        if use_water:
            m.pattern_values.append(M.JointPatternValue(jid, JP_AGUA, round(res.water, 6)))
        if use_seismic:
            m.pattern_values.append(M.JointPatternValue(jid, JP_SISMO, round(res.seismic, 6)))

    # Presion superficial unitaria modulada por el patron
    for col in columns:
        for aid in col.areas:
            m.surface_pressures.append(M.SurfacePressure(aid, PAT_SUELO, "Top", 1.0, JP_EMPUJE))
            if use_water:
                m.surface_pressures.append(M.SurfacePressure(aid, PAT_AGUA, "Top", 1.0, JP_AGUA))
            if use_seismic:
                m.surface_pressures.append(M.SurfacePressure(aid, PAT_SISMO, "Top", 1.0, JP_SISMO))
            if use_surcharge:
                q = press.K * p.earth.surcharge
                m.surface_pressures.append(M.SurfacePressure(aid, PAT_SOBRECARGA, "Top", round(q, 6), None))


def _combos(p: WallProject, m: M.StructuralModel) -> None:
    available = {lp.name for lp in m.load_patterns}
    for combo in p.combos:
        factors = [(f.pattern, f.factor) for f in combo.factors if f.pattern in available]
        if not factors:
            continue
        m.combos.append(M.Combo(combo.name, factors, combo.design))


def _analysis_cases(p: WallProject, m: M.StructuralModel, warnings: list[str]) -> None:
    """Casos modal y no lineal (P-Delta), ambos opcionales.

    La masa sale del peso propio a traves de la fuente de masa por elementos que
    ya define el exportador, asi que el modal no necesita cargas adicionales.
    """
    a = p.analysis
    if a.modal:
        m.modal_cases.append(M.ModalCase(name="MODAL", max_modes=a.modal_modes))

    if a.pdelta:
        available = {lp.name for lp in m.load_patterns}
        factors = [(f.pattern, f.factor) for f in a.pdelta_factors if f.pattern in available]
        if not factors:
            warnings.append(
                "Caso P-Delta omitido: ninguno de sus patrones existe en el modelo."
            )
            return
        head, rest = factors[0], factors[1:]
        m.load_cases.append(M.LoadCase(
            name=a.pdelta_case, pattern=head[0], scale=head[1],
            case_type="NonStatic", geo_nonlin="P-Delta", extra_loads=rest,
        ))
def _section_cuts(p: WallProject, m: M.StructuralModel, columns: list[WallColumn],
                  pile_ys: list[float]) -> None:
    """Cortes de seccion por grupo.

    SAP calcula la resultante de un corte definido por grupo como las fuerzas
    que cruzan los nudos del grupo hacia los elementos que quedan fuera. Por eso
    el grupo debe contener los elementos de un lado del corte Y los nudos del
    plano de corte: con solo los elementos, el corte devuelve cero.
    """
    # Corte en la base de la pantalla: entrega el empuje total que el muro
    # transmite a la viga cabezal y las pilas.
    wall_areas = m.group_element_ids(G_MURO, "Area")
    if wall_areas:
        for aid in wall_areas:
            m.add_to_group(G_CORTE_MURO, "Area", aid)
        for jid in _joints_at_z(m, p.wall.z_base):
            m.add_to_group(G_CORTE_MURO, "Joint", jid)
        m.section_cuts.append(M.SectionCut("CUT_" + G_CORTE_MURO, G_CORTE_MURO))

    # Corte en la cabeza de las pilas: fuerza que las pilas entregan al cabezal.
    pile_frames = m.group_element_ids(G_PILAS, "Frame")
    if pile_frames:
        for fid in pile_frames:
            m.add_to_group(G_CORTE_PILAS, "Frame", fid)
        for y in pile_ys:
            jid = m.joint_at(0.0, y, p.piles.z_top)
            if jid is not None:
                m.add_to_group(G_CORTE_PILAS, "Joint", jid)
        m.section_cuts.append(M.SectionCut("CUT_" + G_CORTE_PILAS, G_CORTE_PILAS))


def _joints_at_z(m: M.StructuralModel, z: float, tol: float = 1e-6) -> list[int]:
    return [j.id for j in m.joints if abs(j.z - z) < tol]


# --------------------------------------------------------------------------
# Reporte
# --------------------------------------------------------------------------
def _report(p: WallProject, m: M.StructuralModel, press: PressureProfile) -> dict:
    H = p.wall.z_top - p.wall.z_base
    if p.wall.is_drawn:
        ys = [pt[0] for pt in p.wall.crown_profile]
        H = max(p.wall.crown_at(y) - p.wall.base_at(y) for y in ys)
    res = press.resultants(H)
    pile_ys = p.pile_y_positions()
    spacing = (pile_ys[1] - pile_ys[0]) if len(pile_ys) > 1 else 0.0

    # Diagrama de presiones en la seccion de mayor altura
    z_base_ref = p.wall.z_base
    if p.wall.is_drawn:
        y_crit = max(
            (pt[0] for pt in p.wall.crown_profile),
            key=lambda y: p.wall.crown_at(y) - p.wall.base_at(y),
        )
        z_base_ref = p.wall.base_at(y_crit)
    z_top_ref = z_base_ref + H
    diagrama = []
    n_div = 24
    for i in range(n_div + 1):
        z = z_base_ref + H * i / n_div
        r = press.at(z, z_top_ref, z_base_ref)
        diagrama.append({
            "z": round(z, 4),
            "suelo": round(r.soil, 3),
            "sobrecarga": round(r.surcharge, 3),
            "sismo": round(r.seismic, 3),
            "agua": round(r.water, 3),
            "total": round(r.total, 3),
        })

    return {
        "diagrama": diagrama,
        "geometria": {
            "altura_muro": round(H, 3),
            "longitud_muro": round(p.wall.y_end - p.wall.y_start, 3),
            "espesor_muro": p.wall.thickness,
            "n_pilas": len(pile_ys),
            "separacion_pilas": round(spacing, 3),
            "diametro_pila": p.piles.diameter,
            "longitud_pila": round(p.piles.length, 3),
        },
        "empujes": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in res.items()},
        "presiones_kPa": {
            "suelo_base": round(press.at(p.wall.z_base, p.wall.z_base + H, p.wall.z_base).soil, 3),
            "sismo_corona": round(press.at(p.wall.z_base + H, p.wall.z_base + H, p.wall.z_base).seismic, 3),
            "sobrecarga": round(press.K * p.earth.surcharge, 3),
        },
        "modelo": m.summary(),
        "balasto": [
            {
                "estrato": l.name,
                "z_top": l.z_top,
                "z_bot": l.z_bot,
                "ks_h": l.ks_h,
                "ks_v": l.ks_v,
                "k_lat_nodal": round(lateral_spring(l.ks_h, p.piles.diameter, p.mesh.pile_segment), 1),
            }
            for l in p.soil.layers
        ],
    }

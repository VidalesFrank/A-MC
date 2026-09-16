"""Modelo estructural neutro.

Representacion intermedia independiente del formato de salida: los exportadores
(.s2k y OAPI) consumen esta estructura. Unidades kN, m.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TOL = 1e-6


# --------------------------------------------------------------------------
# Entidades
# --------------------------------------------------------------------------
@dataclass
class Joint:
    id: int
    x: float
    y: float
    z: float


@dataclass
class Frame:
    id: int
    i: int
    j: int
    section: str
    auto_mesh_at_joints: bool = False
    group: str | None = None


@dataclass
class Area:
    id: int
    joints: list[int]
    section: str
    group: str | None = None


@dataclass
class Spring:
    joint: int
    u1: float = 0.0
    u2: float = 0.0
    u3: float = 0.0
    r1: float = 0.0
    r2: float = 0.0
    r3: float = 0.0


@dataclass
class Restraint:
    joint: int
    u1: bool = False
    u2: bool = False
    u3: bool = False
    r1: bool = False
    r2: bool = False
    r3: bool = False


@dataclass
class JointPatternValue:
    joint: int
    pattern: str
    value: float


@dataclass
class SurfacePressure:
    area: int
    load_pattern: str
    face: str
    pressure: float
    joint_pattern: str | None = None


@dataclass
class LoadPattern:
    name: str
    design_type: str = "Other"
    self_weight: float = 0.0


@dataclass
class LoadCase:
    name: str
    pattern: str
    scale: float = 1.0
    design_type: str = "Other"
    case_type: str = "LinStatic"      # LinStatic | NonStatic
    geo_nonlin: str = "None"          # None | P-Delta | P-Delta plus Large Displacements
    extra_loads: list[tuple[str, float]] = field(default_factory=list)
    # Aceleraciones de cuerpo rigido: ("UX", factor). Es como se introduce la
    # fuerza de inercia del propio muro, k_h*W, sin inventar cargas nodales.
    accels: list[tuple[str, float]] = field(default_factory=list)

    @property
    def loads(self) -> list[tuple[str, float]]:
        """Todos los patrones del caso, empezando por el principal."""
        return [(self.pattern, self.scale)] + list(self.extra_loads)


@dataclass
class ModalCase:
    """Caso modal por vectores propios."""

    name: str = "MODAL"
    max_modes: int = 12
    min_modes: int = 1
    mode_type: str = "Eigen"          # Eigen | Ritz


@dataclass
class Combo:
    name: str
    factors: list[tuple[str, float]]
    design: str = "None"


@dataclass
class ConcreteMaterial:
    name: str
    fc: float
    E: float
    nu: float
    G: float
    gamma: float
    mass: float
    alpha: float


@dataclass
class RebarMaterial:
    name: str
    fy: float
    fu: float
    E: float
    gamma: float
    mass: float
    alpha: float


@dataclass
class CircleSection:
    name: str
    material: str
    diameter: float
    cover: float
    num_bars: int
    bar_size: str
    tie_size: str
    tie_spacing: float


@dataclass
class RectSection:
    name: str
    material: str
    depth: float
    width: float
    cover: float
    num_bars_3: int
    num_bars_2: int
    bar_size: str
    tie_size: str
    tie_spacing: float
    # Una seccion rectangular de concreto se define en SAP como VIGA o como
    # COLUMNA, y eso decide como la disena: viga da flexion, cortante y torsion;
    # columna da interaccion P-M-M y nunca mira la torsion. La viga cabezal es
    # una viga, asi que este es el valor por defecto.
    is_beam: bool = True


@dataclass
class ShellSection:
    name: str
    material: str
    thickness: float
    shell_type: str = "Shell-Thick"
    rebar_material: str | None = None


@dataclass
class Group:
    name: str


@dataclass
class SectionCut:
    name: str
    group: str


@dataclass
class GridLine:
    axis: str
    grid_id: str
    coord: float


# --------------------------------------------------------------------------
# Contenedor
# --------------------------------------------------------------------------
class StructuralModel:
    """Contenedor del modelo con numeracion automatica y fusion de nudos."""

    def __init__(self, name: str = "Modelo") -> None:
        self.name = name
        self.joints: list[Joint] = []
        self.frames: list[Frame] = []
        self.areas: list[Area] = []
        self.springs: list[Spring] = []
        self.restraints: list[Restraint] = []
        self.joint_patterns: list[str] = []
        self.pattern_values: list[JointPatternValue] = []
        self.surface_pressures: list[SurfacePressure] = []
        self.load_patterns: list[LoadPattern] = []
        self.load_cases: list[LoadCase] = []
        self.modal_cases: list[ModalCase] = []
        self.combos: list[Combo] = []
        self.concrete: list[ConcreteMaterial] = []
        self.rebar: list[RebarMaterial] = []
        self.circle_sections: list[CircleSection] = []
        self.rect_sections: list[RectSection] = []
        self.shell_sections: list[ShellSection] = []
        self.groups: list[Group] = []
        self.group_members: list[tuple[str, str, int]] = []  # (grupo, tipo, id)
        self.section_cuts: list[SectionCut] = []
        self.grid_lines: list[GridLine] = []
        self.meta: dict = {}

        self._joint_index: dict[tuple[int, int, int], int] = {}
        self._next_joint = 1
        self._next_frame = 1
        self._next_area = 1

    # -- nudos -------------------------------------------------------------
    @staticmethod
    def _key(x: float, y: float, z: float) -> tuple[int, int, int]:
        return (round(x / TOL), round(y / TOL), round(z / TOL))

    def add_joint(self, x: float, y: float, z: float) -> int:
        """Devuelve el id del nudo, reutilizandolo si ya existe en esa posicion."""
        key = self._key(x, y, z)
        existing = self._joint_index.get(key)
        if existing is not None:
            return existing
        jid = self._next_joint
        self._next_joint += 1
        self.joints.append(Joint(jid, x, y, z))
        self._joint_index[key] = jid
        return jid

    def joint_at(self, x: float, y: float, z: float) -> int | None:
        return self._joint_index.get(self._key(x, y, z))

    def get_joint(self, jid: int) -> Joint:
        return self.joints[jid - 1]

    # -- elementos ---------------------------------------------------------
    def add_frame(self, i: int, j: int, section: str, auto_mesh_at_joints: bool = False,
                  group: str | None = None) -> int:
        fid = self._next_frame
        self._next_frame += 1
        self.frames.append(Frame(fid, i, j, section, auto_mesh_at_joints, group))
        if group:
            self.add_to_group(group, "Frame", fid)
        return fid

    def add_area(self, joints: list[int], section: str, group: str | None = None) -> int:
        aid = self._next_area
        self._next_area += 1
        self.areas.append(Area(aid, joints, section, group))
        if group:
            self.add_to_group(group, "Area", aid)
        return aid

    # -- grupos ------------------------------------------------------------
    def add_group(self, name: str) -> None:
        if not any(g.name == name for g in self.groups):
            self.groups.append(Group(name))

    def add_to_group(self, group: str, kind: str, eid: int) -> None:
        self.add_group(group)
        self.group_members.append((group, kind, eid))

    def group_element_ids(self, group: str, kind: str) -> list[int]:
        return [eid for g, k, eid in self.group_members if g == group and k == kind]

    # -- cargas ------------------------------------------------------------
    def add_load_pattern(self, name: str, design_type: str = "Other", self_weight: float = 0.0) -> None:
        if not any(p.name == name for p in self.load_patterns):
            self.load_patterns.append(LoadPattern(name, design_type, self_weight))

    def add_joint_pattern(self, name: str) -> None:
        if name not in self.joint_patterns:
            self.joint_patterns.append(name)

    # -- resumen -----------------------------------------------------------
    def summary(self) -> dict:
        return {
            "joints": len(self.joints),
            "frames": len(self.frames),
            "areas": len(self.areas),
            "springs": len(self.springs),
            "load_patterns": [p.name for p in self.load_patterns],
            "combos": [c.name for c in self.combos],
            "load_cases": [c.name for c in self.load_cases] + [c.name for c in self.modal_cases],
            "groups": [g.name for g in self.groups],
        }

    def bounds(self) -> dict:
        if not self.joints:
            return {}
        xs = [j.x for j in self.joints]
        ys = [j.y for j in self.joints]
        zs = [j.z for j in self.joints]
        return {
            "x": [min(xs), max(xs)],
            "y": [min(ys), max(ys)],
            "z": [min(zs), max(zs)],
        }

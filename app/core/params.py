"""Esquema de entrada del generador de muros de contencion.

Unidades internas: kN, m, grados. Cotas Z absolutas con el mismo datum que el
modelo de SAP (Z=0 tipicamente en el arranque del muro / cabeza de pila).
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# --------------------------------------------------------------------------
# Materiales
# --------------------------------------------------------------------------
class Concrete(BaseModel):
    name: str = "f'c_21 MPa"
    fc: float = Field(21000.0, description="f'c en kPa")
    E: float | None = Field(None, description="Modulo elastico en kPa; None => 4700*sqrt(f'c[MPa])")
    nu: float = 0.20
    gamma: float = Field(24.0, description="Peso especifico en kN/m3")
    alpha: float = 9.9e-6

    @property
    def E_calc(self) -> float:
        if self.E is not None:
            return self.E
        fc_mpa = self.fc / 1000.0
        return 4700.0 * math.sqrt(fc_mpa) * 1000.0

    @property
    def G(self) -> float:
        return self.E_calc / (2.0 * (1.0 + self.nu))

    @property
    def mass_density(self) -> float:
        return self.gamma / 9.80665


class Rebar(BaseModel):
    name: str = "420 MPa"
    fy: float = Field(420000.0, description="fy en kPa")
    fu: float = 560000.0
    E: float = 200_000_000.0
    gamma: float = 76.9728639
    alpha: float = 1.17e-5

    @property
    def mass_density(self) -> float:
        return self.gamma / 9.80665


class Materials(BaseModel):
    concrete: Concrete = Concrete()
    rebar: Rebar = Rebar()


# --------------------------------------------------------------------------
# Suelo
# --------------------------------------------------------------------------
class SoilLayer(BaseModel):
    """Estrato de suelo. z_top > z_bot, en cotas absolutas del modelo."""

    name: str = "Estrato"
    z_top: float
    z_bot: float
    gamma: float = Field(18.0, description="Peso especifico humedo kN/m3")
    gamma_sat: float = Field(20.0, description="Peso especifico saturado kN/m3")
    phi: float = Field(30.0, description="Angulo de friccion interna en grados")
    cohesion: float = Field(0.0, description="Cohesion en kPa")
    ks_h: float = Field(20000.0, description="Modulo de balasto horizontal kN/m3")
    ks_v: float = Field(50000.0, description="Modulo de balasto vertical kN/m3 (punta / zapata)")

    @model_validator(mode="after")
    def _check_order(self):
        if self.z_bot >= self.z_top:
            raise ValueError(
                "Estrato '%s': z_bot (%s) debe ser menor que z_top (%s)" % (self.name, self.z_bot, self.z_top)
            )
        return self

    def contains(self, z: float) -> bool:
        return self.z_bot - 1e-9 <= z <= self.z_top + 1e-9


class SoilProfile(BaseModel):
    layers: list[SoilLayer] = Field(default_factory=list)
    water_table_z: float | None = Field(None, description="Cota del nivel freatico; None = sin agua")
    gamma_w: float = 9.81
    nh: float | None = Field(
        None,
        description=("Modulo de reaccion horizontal n_h [kN/m3] de Matlock y "
                     "Reese. Cuando se da, el balasto lateral crece con la "
                     "profundidad bajo la cabeza de CADA pila, ks_h = nh*z/D, y "
                     "manda sobre el ks_h de los estratos. Es como lo entrega un "
                     "estudio geotecnico para pilas."),
    )

    def layer_at(self, z: float) -> SoilLayer | None:
        for lay in self.layers:
            if lay.contains(z):
                return lay
        return None

    def ks_h_at(self, z: float, default: float = 20000.0) -> float:
        lay = self.layer_at(z)
        return lay.ks_h if lay else default

    def ks_v_at(self, z: float, default: float = 50000.0) -> float:
        lay = self.layer_at(z)
        return lay.ks_v if lay else default


# --------------------------------------------------------------------------
# Empujes
# --------------------------------------------------------------------------
class EarthPressure(BaseModel):
    """Empuje estatico del relleno retenido sobre la pantalla."""

    method: Literal["rankine", "coulomb", "usuario"] = "rankine"
    condition: Literal["activo", "reposo", "pasivo"] = "activo"
    K_user: float | None = Field(None, description="Coeficiente impuesto cuando method='usuario'")
    gamma: float = Field(17.0, description="Peso especifico del relleno kN/m3")
    gamma_sat: float = Field(20.0, description="Peso especifico saturado del relleno kN/m3")
    phi: float = Field(30.0, description="Angulo de friccion del relleno en grados")
    beta: float = Field(0.0, description="Inclinacion del terreno tras el muro (grados)")
    delta: float = Field(0.0, description="Friccion muro-suelo para Coulomb (grados)")
    theta: float = Field(0.0, description="Inclinacion del paramento respecto a la vertical (grados)")
    surcharge: float = Field(0.0, description="Sobrecarga uniforme en corona, kPa")

    def coefficient(self) -> float:
        """Coeficiente de empuje K segun el metodo y la condicion elegidos."""
        if self.method == "usuario":
            if self.K_user is None:
                raise ValueError("method='usuario' requiere K_user")
            return self.K_user

        phi = math.radians(self.phi)

        if self.condition == "reposo":
            k0 = 1.0 - math.sin(phi)
            if abs(self.beta) > 1e-9:
                k0 *= 1.0 + math.sin(math.radians(self.beta))
            return k0

        if self.method == "rankine":
            beta = math.radians(self.beta)
            if abs(self.beta) < 1e-9:
                if self.condition == "activo":
                    return math.tan(math.pi / 4.0 - phi / 2.0) ** 2
                return math.tan(math.pi / 4.0 + phi / 2.0) ** 2
            cb, cp = math.cos(beta), math.cos(phi)
            rad = math.sqrt(max(cb * cb - cp * cp, 0.0))
            if self.condition == "activo":
                return cb * (cb - rad) / (cb + rad)
            return cb * (cb + rad) / (cb - rad)

        # Coulomb
        beta = math.radians(self.beta)
        delta = math.radians(self.delta)
        theta = math.radians(self.theta)
        if self.condition == "activo":
            num = math.cos(phi - theta) ** 2
            root = math.sqrt(
                max(
                    (math.sin(phi + delta) * math.sin(phi - beta))
                    / max(math.cos(theta + delta) * math.cos(theta - beta), 1e-12),
                    0.0,
                )
            )
            den = math.cos(theta) ** 2 * math.cos(theta + delta) * (1.0 + root) ** 2
            return num / den
        num = math.cos(phi + theta) ** 2
        root = math.sqrt(
            max(
                (math.sin(phi + delta) * math.sin(phi + beta))
                / max(math.cos(theta + delta) * math.cos(theta - beta), 1e-12),
                0.0,
            )
        )
        den = math.cos(theta) ** 2 * math.cos(theta - delta) * (1.0 - root) ** 2
        return num / den


class Seismic(BaseModel):
    """Incremento sismico del empuje (Mononobe-Okabe)."""

    enabled: bool = True
    kh: float = Field(0.15, description="Coeficiente sismico horizontal")
    kv: float = Field(0.0, description="Coeficiente sismico vertical")
    method: Literal["mononobe", "usuario"] = "mononobe"
    dK_user: float | None = Field(None, description="Incremento dKae impuesto cuando method='usuario'")
    distribution: Literal["triangular_invertida", "uniforme", "triangular"] = "triangular_invertida"
    include_inertia: bool = Field(
        False,
        description=("Anade la fuerza de inercia del propio muro, k_h*W, como "
                     "aceleracion UX en el caso sismico. Viene apagado para no "
                     "alterar los modelos ya validados sin el."),
    )

    def delta_K(self, ep: EarthPressure) -> float:
        """Incremento dKae = Kae - Ka."""
        if not self.enabled:
            return 0.0
        if self.method == "usuario":
            if self.dK_user is None:
                raise ValueError("method='usuario' requiere dK_user")
            return self.dK_user

        phi = math.radians(ep.phi)
        beta = math.radians(ep.beta)
        delta = math.radians(ep.delta)
        theta = math.radians(ep.theta)
        psi = math.atan(self.kh / max(1.0 - self.kv, 1e-9))

        if phi - beta - psi < 0:
            raise ValueError(
                "Mononobe-Okabe no converge: phi (%.1f deg) debe superar beta+psi (%.1f deg). "
                "Reduzca kh o la inclinacion del terreno." % (ep.phi, math.degrees(beta + psi))
            )

        num = math.cos(phi - theta - psi) ** 2
        root = math.sqrt(
            max(
                (math.sin(phi + delta) * math.sin(phi - beta - psi))
                / max(math.cos(delta + theta + psi) * math.cos(theta - beta), 1e-12),
                0.0,
            )
        )
        den = (
            math.cos(psi)
            * math.cos(theta) ** 2
            * math.cos(delta + theta + psi)
            * (1.0 + root) ** 2
        )
        kae = num / den
        ka = ep.coefficient()
        return max(kae - ka, 0.0)


# --------------------------------------------------------------------------
# Geometria
# --------------------------------------------------------------------------
class RebarCircular(BaseModel):
    cover: float = 0.075
    num_bars: int = 20
    bar_size: str = "#8"
    tie_size: str = "#4"
    tie_spacing: float = 0.15


class RebarRect(BaseModel):
    cover: float = 0.040
    num_bars_3: int = 7
    num_bars_2: int = 3
    bar_size: str = "#7"
    tie_size: str = "#4"
    tie_spacing: float = 0.15


class PileZone(BaseModel):
    """Tramo de pila con seccion propia (permite variar el refuerzo con la profundidad)."""

    name: str = "P_1.20"
    z_from: float = Field(..., description="Cota superior del tramo")
    z_to: float = Field(..., description="Cota inferior del tramo")
    rebar: RebarCircular = RebarCircular()
    piles: list[int] | None = Field(
        None,
        description=("Pilas a las que aplica, numeradas desde 1 de izquierda a "
                     "derecha. None = a todas. Una zona con pilas fijadas manda "
                     "sobre la general que ocupe la misma cota, de modo que se "
                     "puede armar cada pila para su propia demanda."),
    )

    @property
    def z_hi(self) -> float:
        return max(self.z_from, self.z_to)

    @property
    def z_lo(self) -> float:
        return min(self.z_from, self.z_to)

    def applies_to(self, n: int) -> bool:
        """n es el numero de pila, desde 1."""
        return not self.piles or n in self.piles


class PileGeometry(BaseModel):
    diameter: float = 1.20
    spacing: float = 2.80
    count: int | None = Field(None, description="Numero de pilas; None => derivado de la longitud del muro")
    y_positions: list[float] | None = Field(None, description="Posiciones explicitas; anula spacing/count")
    z_top: float = 0.0
    z_bot: float = -10.0
    z_bots: list[float] | None = Field(
        None,
        description=("Cota de punta de cada pila, de izquierda a derecha. None "
                     "=> todas terminan en z_bot. Permite la longitud creciente "
                     "que pide un corte de altura variable."),
    )
    tip_restraint: bool = Field(
        True,
        description=("Restringe el desplazamiento vertical (U3) en el nudo de punta "
                     "en lugar de ponerle el resorte kv. El resto de nudos de la "
                     "pila conserva solo el balasto lateral."),
    )
    segment_length: float = 1.0
    zones: list[PileZone] = Field(default_factory=list)
    tip_spring_kv: float | None = Field(None, description="Rigidez de punta kN/m; None => derivada de ks_v")
    skip_head_spring: bool = Field(True, description="Omitir resorte lateral en la cabeza (suelo excavado al frente)")

    @property
    def length(self) -> float:
        return self.z_top - self.z_bot

    def z_bot_of(self, i: int) -> float:
        """Cota de punta de la pila i (base 0)."""
        if self.z_bots and i < len(self.z_bots):
            return self.z_bots[i]
        return self.z_bot

    def z_tops(self, wall: "WallGeometry", ys: list[float]) -> list[float]:
        """Cota de cabeza de cada pila.

        Con base del muro inclinada la viga cabezal se desplanta en el fondo de
        la excavacion y arrastra las cabezas con ella, que es lo que pasa en un
        corte de profundidad variable.
        """
        if wall.base_profile:
            return [wall.base_at(y) for y in ys]
        return [self.z_top] * len(ys)

    @property
    def z_bot_min(self) -> float:
        """La punta mas profunda del grupo."""
        return min([self.z_bot] + list(self.z_bots or []))

    def zones_of(self, n: int) -> list["PileZone"]:
        """Zonas que arman la pila n (desde 1), de arriba abajo.

        Donde una zona propia de la pila se superpone con una general, la propia
        manda: asi se puede empezar con un armado comun y afinar solo las pilas
        que lo necesiten.
        """
        propias = [z for z in self.zones if z.piles and n in z.piles]
        generales = [z for z in self.zones if not z.piles]
        tapadas = [g for g in generales
                   if not any(pz.z_lo < g.z_hi - 1e-9 and pz.z_hi > g.z_lo + 1e-9
                              for pz in propias)]
        return sorted(propias + tapadas, key=lambda z: -z.z_hi)

    def zone_at(self, n: int, z: float) -> "PileZone":
        """Zona que arma la cota z de la pila n (desde 1)."""
        zonas = self.zones_of(n) or self.zones
        for zz in zonas:
            if zz.z_lo - 1e-9 <= z <= zz.z_hi + 1e-9:
                return zz
        return min(zonas, key=lambda zz: abs(z - 0.5 * (zz.z_hi + zz.z_lo)))

    @property
    def per_pile_zones(self) -> bool:
        """True si hay armados distintos entre pilas."""
        return any(z.piles for z in self.zones)


class CapBeamGeometry(BaseModel):
    enabled: bool = True
    width: float = 1.40
    depth: float = 0.60
    overhangs: bool = Field(
        True,
        description=("Prolonga la viga hasta los extremos del muro cuando las "
                     "pilas no llegan a ellos. Con las pilas en los extremos no "
                     "cambia nada."),
    )
    z: float | None = Field(None, description="Cota del eje; None = z_top de las pilas")
    name: str = "VC_1.40x0.60"
    rebar: RebarRect = RebarRect()


class WallGeometry(BaseModel):
    thickness: float = Field(0.70, description="Espesor en el arranque (el mayor)")
    thickness_top: float | None = Field(
        None,
        description=("Espesor en la corona. None => espesor constante. El "
                     "vastago se acartela linealmente entre los dos valores."),
    )
    length: float = Field(14.0, description="Longitud del muro en Y (modo parametrico)")
    z_base: float = 0.0
    z_top: float = 6.0
    name: str = "M_0.70"
    shell_type: Literal["Shell-Thick", "Shell-Thin"] = "Shell-Thick"
    crown_profile: list[tuple[float, float]] | None = Field(
        None, description="Modo dibujo: [(y, z_corona), ...] de izquierda a derecha"
    )
    base_profile: list[tuple[float, float]] | None = Field(
        None, description="Modo dibujo: [(y, z_base), ...]; None = z_base constante"
    )

    @property
    def is_drawn(self) -> bool:
        return bool(self.crown_profile) and len(self.crown_profile) >= 2

    @property
    def is_tapered(self) -> bool:
        return (self.thickness_top is not None
                and abs(self.thickness_top - self.thickness) > 1e-6)

    def thickness_at_frac(self, f: float) -> float:
        """Espesor a la fraccion f de la altura, 0 en el arranque y 1 en la corona.

        El acartelamiento se mide sobre la altura local del vastago, no sobre una
        cota absoluta: en un corte de altura variable cada seccion va de su
        espesor de corona al de arranque.
        """
        if not self.is_tapered:
            return self.thickness
        f = min(max(f, 0.0), 1.0)
        return self.thickness + (self.thickness_top - self.thickness) * f

    @property
    def thickness_mean(self) -> float:
        if not self.is_tapered:
            return self.thickness
        return 0.5 * (self.thickness + self.thickness_top)

    @property
    def y_start(self) -> float:
        if self.is_drawn:
            return min(p[0] for p in self.crown_profile)
        return 0.0

    @property
    def y_end(self) -> float:
        if self.is_drawn:
            return max(p[0] for p in self.crown_profile)
        return self.length

    def crown_at(self, y: float) -> float:
        """Cota de corona interpolada en la abscisa y."""
        if not self.is_drawn:
            return self.z_top
        return _interp(self.crown_profile, y)

    def base_at(self, y: float) -> float:
        if not self.base_profile:
            return self.z_base
        return _interp(self.base_profile, y)


def _interp(profile, y: float) -> float:
    pts = sorted(profile, key=lambda p: p[0])
    if y <= pts[0][0]:
        return pts[0][1]
    if y >= pts[-1][0]:
        return pts[-1][1]
    for (y0, z0), (y1, z1) in zip(pts, pts[1:]):
        if y0 <= y <= y1:
            if abs(y1 - y0) < 1e-12:
                return z1
            t = (y - y0) / (y1 - y0)
            return z0 + t * (z1 - z0)
    return pts[-1][1]


class MeshParams(BaseModel):
    wall_div_per_bay: int = Field(3, ge=1, description="Divisiones de shell en Y por vano entre pilas")
    wall_target_dz: float = Field(1.0, gt=0, description="Altura objetivo de shell en Z")
    pile_segment: float = Field(1.0, gt=0, description="Longitud de segmento de pila")
    wall_design_strips: int = Field(3, ge=1, le=10, description="Franjas de diseno en altura de la pantalla")


# --------------------------------------------------------------------------
# Casos y combinaciones
# --------------------------------------------------------------------------
class ComboFactor(BaseModel):
    pattern: str
    factor: float


class LoadCombo(BaseModel):
    name: str
    factors: list[ComboFactor]
    design: Literal["None", "Strength", "Service"] = "None"


def default_combos() -> list[LoadCombo]:
    """Combinaciones por defecto, NSR-10 B.2.4 / ACI 318 5.3.

    La sobrecarga en corona va con el mismo factor que el empuje: es empuje
    lateral, no carga gravitatoria. Los patrones que el modelo no genera se
    descartan solos al armar las combinaciones, de modo que un proyecto sin
    sobrecarga sale igual que antes.
    """
    return [
        LoadCombo(
            name="S1 D+H",
            factors=[ComboFactor(pattern="DEAD", factor=1.0),
                     ComboFactor(pattern="SUELO", factor=1.0),
                     ComboFactor(pattern="SOBRECARGA", factor=1.0)],
        ),
        LoadCombo(
            name="S2 D+H+S",
            factors=[
                ComboFactor(pattern="DEAD", factor=1.0),
                ComboFactor(pattern="SUELO", factor=1.0),
                ComboFactor(pattern="SOBRECARGA", factor=1.0),
                ComboFactor(pattern="SISMO_SUELO", factor=1.0),
            ],
        ),
        LoadCombo(
            name="U1 1.2D+1.6H",
            factors=[ComboFactor(pattern="DEAD", factor=1.2),
                     ComboFactor(pattern="SUELO", factor=1.6),
                     ComboFactor(pattern="SOBRECARGA", factor=1.6)],
            design="Strength",
        ),
        LoadCombo(
            name="U2 1.2D+1.6H+1.0S",
            factors=[
                ComboFactor(pattern="DEAD", factor=1.2),
                ComboFactor(pattern="SUELO", factor=1.6),
                ComboFactor(pattern="SOBRECARGA", factor=1.6),
                ComboFactor(pattern="SISMO_SUELO", factor=1.0),
            ],
            design="Strength",
        ),
        LoadCombo(
            name="U3 0.9D+1.6H",
            factors=[ComboFactor(pattern="DEAD", factor=0.9),
                     ComboFactor(pattern="SUELO", factor=1.6),
                     ComboFactor(pattern="SOBRECARGA", factor=1.6)],
            design="Strength",
        ),
    ]


class AnalysisOptions(BaseModel):
    """Casos de analisis mas alla del estatico lineal.

    Vienen desactivados: con ambos en False el .s2k sale identico al del camino
    lineal ya validado contra SAP, y solo se anaden tablas cuando se piden.
    """

    modal: bool = Field(False, description="Caso modal por vectores propios")
    modal_modes: int = Field(12, ge=1, le=100, description="Numero maximo de modos")
    pdelta: bool = Field(False, description="Caso estatico no lineal con P-Delta")
    pdelta_case: str = Field("PDELTA", description="Nombre del caso no lineal")
    pdelta_factors: list[ComboFactor] = Field(
        default_factory=lambda: [ComboFactor(pattern="DEAD", factor=1.2),
                                 ComboFactor(pattern="SUELO", factor=1.6)],
        description="Patrones y factores de la carga sostenida para P-Delta",
    )


# --------------------------------------------------------------------------
# Ajustes del refuerzo
# --------------------------------------------------------------------------
class StripOverride(BaseModel):
    """Refuerzo impuesto en una franja de la pantalla.

    Los campos en None siguen el valor recomendado por el calculo; los que se
    fijan mandan sobre el, y el despiece marca si el area colocada cubre la
    requerida.
    """

    franja: int
    bar_v: str | None = Field(None, description="Barra vertical, p.ej. #5")
    s_v: float | None = Field(None, gt=0, description="Separacion vertical [mm]")
    bar_h: str | None = Field(None, description="Barra horizontal")
    s_h: float | None = Field(None, gt=0, description="Separacion horizontal [mm]")


class BeamRebarOverride(BaseModel):
    """Refuerzo impuesto en la viga cabezal."""

    bar_size: str | None = None
    n_sup: int | None = Field(None, ge=2)
    n_inf: int | None = Field(None, ge=2)
    tie_size: str | None = None
    s_tie: float | None = Field(None, gt=0, description="Separacion de estribos [mm]")
    bar_torsion: str | None = None
    n_torsion: int | None = Field(None, ge=4)


class RebarOverrides(BaseModel):
    """Lo que el ingeniero ajusta a mano sobre el refuerzo recomendado.

    Vive dentro del proyecto a proposito: asi se guarda con «Guardar datos» y
    llega solo a la lamina, al Excel y a la memoria, sin que haya dos versiones
    del despiece circulando.
    """

    bar_v: str = Field("#5", description="Barra vertical por defecto de la pantalla")
    bar_h: str = Field("#5", description="Barra horizontal por defecto de la pantalla")
    muro: list[StripOverride] = Field(default_factory=list)
    viga: BeamRebarOverride = Field(default_factory=BeamRebarOverride)

    def franja(self, i: int) -> StripOverride | None:
        for o in self.muro:
            if o.franja == i:
                return o
        return None


# --------------------------------------------------------------------------
# Entrada completa
# --------------------------------------------------------------------------
class ProjectInfo(BaseModel):
    name: str = "Muro de contencion"
    engineer: str = ""
    license: str = Field(
        "",
        description=("Matricula profesional del ingeniero responsable, tal como "
                     "debe aparecer junto a su firma (p. ej. 05202-123456). Un "
                     "plano estructural firmado la lleva; vacio deja el guion."),
    )
    client: str = ""
    notes: str = ""


class WallProject(BaseModel):
    """Definicion completa de un modelo de muro de contencion sobre pilas."""

    info: ProjectInfo = ProjectInfo()
    materials: Materials = Materials()
    wall: WallGeometry = WallGeometry()
    piles: PileGeometry = PileGeometry()
    cap_beam: CapBeamGeometry = CapBeamGeometry()
    soil: SoilProfile = SoilProfile()
    earth: EarthPressure = EarthPressure()
    seismic: Seismic = Seismic()
    mesh: MeshParams = MeshParams()
    analysis: AnalysisOptions = AnalysisOptions()
    rebar_overrides: RebarOverrides = Field(default_factory=RebarOverrides)
    combos: list[LoadCombo] = Field(default_factory=default_combos)

    @model_validator(mode="after")
    def _defaults(self):
        if not self.soil.layers:
            zt, zb = self.piles.z_top, self.piles.z_bot_min
            h = (zt - zb) / 3.0
            self.soil.layers = [
                SoilLayer(name="Estrato 1", z_top=zt, z_bot=zt - h, ks_h=20000.0, ks_v=40000.0, phi=28.0),
                SoilLayer(name="Estrato 2", z_top=zt - h, z_bot=zt - 2 * h, ks_h=35000.0, ks_v=70000.0, phi=32.0),
                SoilLayer(name="Estrato 3", z_top=zt - 2 * h, z_bot=zb, ks_h=60000.0, ks_v=100000.0, phi=36.0),
            ]
        if not self.piles.zones:
            zt, zb = self.piles.z_top, self.piles.z_bot_min
            zmid = zb + 0.4 * (zt - zb)
            d = self.piles.diameter
            self.piles.zones = [
                PileZone(name="P_%.2f_SUP" % d, z_from=zt, z_to=zmid, rebar=RebarCircular(num_bars=20, bar_size="#8")),
                PileZone(name="P_%.2f_INF" % d, z_from=zmid, z_to=zb, rebar=RebarCircular(num_bars=20, bar_size="#6")),
            ]
        if self.cap_beam.z is None:
            self.cap_beam.z = self.piles.z_top
        return self

    def pile_y_positions(self) -> list[float]:
        if self.piles.y_positions:
            return sorted(self.piles.y_positions)
        y0, y1 = self.wall.y_start, self.wall.y_end
        if self.piles.count is not None and self.piles.count >= 2:
            n = self.piles.count
            step = (y1 - y0) / (n - 1)
            return [y0 + i * step for i in range(n)]
        n_bays = max(int(round((y1 - y0) / self.piles.spacing)), 1)
        step = (y1 - y0) / n_bays
        return [y0 + i * step for i in range(n_bays + 1)]

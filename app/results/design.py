"""Verificaciones de concreto reforzado segun ACI 318 (unidades kN, m, kPa).

Cubre lo que el modelo produce:
  * pantalla: flexion por metro de ancho y cortante en una direccion
  * viga cabezal: flexion rectangular y cortante con estribos
  * pilas: diagrama de interaccion P-M circular por compatibilidad de
    deformaciones, y cortante segun 22.5

Las formulas se escriben en MPa/mm internamente y se devuelven en kN, m.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

ES = 200000.0  # MPa
EPS_CU = 0.003

BAR_AREA_MM2 = {
    "#3": 71.0, "#4": 129.0, "#5": 199.0, "#6": 284.0, "#7": 387.0,
    "#8": 510.0, "#9": 645.0, "#10": 819.0, "#11": 1006.0, "#14": 1452.0, "#18": 2581.0,
}
BAR_DIAM_MM = {
    "#3": 9.5, "#4": 12.7, "#5": 15.9, "#6": 19.1, "#7": 22.2,
    "#8": 25.4, "#9": 28.7, "#10": 32.3, "#11": 35.8, "#14": 43.0, "#18": 57.3,
}


def bar_area(size: str) -> float:
    return BAR_AREA_MM2.get(size, 510.0)


def bar_diam(size: str) -> float:
    return BAR_DIAM_MM.get(size, 25.4)


def beta1(fc_mpa: float) -> float:
    if fc_mpa <= 28.0:
        return 0.85
    return max(0.65, 0.85 - 0.05 * (fc_mpa - 28.0) / 7.0)


def phi_flexure(eps_t: float, fy_mpa: float, spiral: bool = False) -> float:
    """Factor de reduccion por deformacion neta de traccion (ACI 21.2.2)."""
    eps_y = fy_mpa / ES
    phi_c = 0.75 if spiral else 0.65
    if eps_t <= eps_y:
        return phi_c
    if eps_t >= 0.005:
        return 0.90
    return phi_c + (0.90 - phi_c) * (eps_t - eps_y) / (0.005 - eps_y)


# --------------------------------------------------------------------------
# Flexion en seccion rectangular / franja de muro
# --------------------------------------------------------------------------
@dataclass
class FlexureCheck:
    Mu: float           # kN*m
    b: float            # m
    h: float            # m
    d: float            # m
    As_req: float       # mm2
    As_min: float       # mm2
    As_max: float       # mm2, tope por eps_t >= 0.004 (limite de sobre-refuerzo)
    As_prov: float      # mm2
    rho: float
    phiMn: float        # kN*m
    ratio: float
    ok: bool
    limitada_por_seccion: bool = False  # el canto, no el acero, es lo que falla
    note: str = ""


def flexure_rect(Mu: float, b: float, h: float, fc: float, fy: float,
                 cover: float, bar_size: str = "#5",
                 As_prov: float | None = None, is_slab: bool = False) -> FlexureCheck:
    """Diseno a flexion de una seccion rectangular b x h.

    Mu en kN*m (para muros, por metro de ancho con b = 1.0).
    fc y fy en kPa; b, h, cover en m.
    """
    fc_m = fc / 1000.0
    fy_m = fy / 1000.0
    b_mm = b * 1000.0
    h_mm = h * 1000.0
    d_mm = h_mm - cover * 1000.0 - bar_diam(bar_size) / 2.0
    Mu_abs = abs(Mu)
    Mu_nmm = Mu_abs * 1e6  # kN*m -> N*mm

    # Tope de armado: ACI 318 exige eps_t >= 0.004 en elementos a flexion, lo que
    # acota la cuantia y con ella la maxima capacidad utilizable de la seccion.
    rho_max = 0.85 * fc_m / fy_m * beta1(fc_m) * (EPS_CU / (EPS_CU + 0.004))
    As_max = rho_max * b_mm * d_mm
    a_max = As_max * fy_m / (0.85 * fc_m * b_mm)
    phiMn_max = phi_flexure(0.004, fy_m) * As_max * fy_m * (d_mm - a_max / 2.0) / 1e6

    note = ""
    insuficiente = False
    rho = 0.0
    phi = 0.90
    # El area requerida y phi son interdependientes: si la seccion queda en
    # transicion, phi baja y hace falta mas acero. Se itera hasta converger.
    for _ in range(12):
        Rn = Mu_nmm / (phi * b_mm * d_mm * d_mm)  # MPa
        disc = 1.0 - 2.0 * Rn / (0.85 * fc_m)
        if disc < 0.0:
            insuficiente = True
            break
        rho_new = 0.85 * fc_m / fy_m * (1.0 - math.sqrt(disc))
        a_i = rho_new * fy_m * d_mm / (0.85 * fc_m)
        c_i = a_i / beta1(fc_m)
        eps_i = EPS_CU * (d_mm - c_i) / c_i if c_i > 0 else 0.01
        phi_new = phi_flexure(eps_i, fy_m)
        converged = abs(phi_new - phi) < 1e-4 and abs(rho_new - rho) < 1e-9
        rho, phi = rho_new, phi_new
        if converged:
            break

    if not insuficiente and rho > rho_max:
        insuficiente = True

    if is_slab:
        As_min = 0.0018 * b_mm * h_mm
    else:
        As_min = max(0.25 * math.sqrt(fc_m) / fy_m, 1.4 / fy_m) * b_mm * d_mm

    if insuficiente:
        # No existe un "As requerido": ningun armado permitido equilibra Mu. Se
        # informa el tope (As_max) y la capacidad que se alcanza con el, de modo
        # que el D/C mida el deficit real de seccion en vez de un numero vacio.
        note = ("La seccion no da de si a flexion: con el maximo armado permitido "
                "(eps_t = 0.004) solo alcanza phiMn = %.1f kN-m frente a Mu = %.1f kN-m. "
                "Aumente el canto o f'c." % (phiMn_max, Mu_abs))
        As_req = As_max
        As = As_prov if As_prov is not None else As_max
    else:
        As_req = rho * b_mm * d_mm
        As = As_prov if As_prov is not None else max(As_req, As_min)

    # Capacidad real del acero colocado
    a = As * fy_m / (0.85 * fc_m * b_mm)
    c = a / beta1(fc_m)
    eps_t = EPS_CU * (d_mm - c) / c if c > 0 else 0.005
    phi_real = phi_flexure(eps_t, fy_m)
    Mn = As * fy_m * (d_mm - a / 2.0)
    phiMn = phi_real * Mn / 1e6  # N*mm -> kN*m

    ratio = Mu_abs / phiMn if phiMn > 0 else float("inf")

    # Si el acero se disena aqui (no venia impuesto), phiMn iguala a Mu por
    # construccion y comparar contra 1.0 solo mide ruido de coma flotante: lo
    # unico que puede fallar es que la seccion no de de si.
    ok = (not insuficiente) if As_prov is None else (ratio <= 1.001 and not insuficiente)

    return FlexureCheck(
        Mu=round(Mu_abs, 2), b=b, h=h, d=round(d_mm / 1000.0, 4),
        As_req=round(As_req, 1), As_min=round(As_min, 1), As_max=round(As_max, 1),
        As_prov=round(As, 1), rho=round(As / (b_mm * d_mm), 5), phiMn=round(phiMn, 2),
        ratio=round(ratio, 3), ok=ok, limitada_por_seccion=insuficiente, note=note,
    )


# --------------------------------------------------------------------------
# Cortante
# --------------------------------------------------------------------------
@dataclass
class ShearCheck:
    Vu: float
    phiVc: float
    phiVn: float
    Av_s_req: float     # mm2/m
    ratio: float
    ok: bool
    note: str = ""


def shear_check(Vu: float, bw: float, d: float, fc: float, fy: float,
                Av_s_prov: float = 0.0, lam: float = 1.0) -> ShearCheck:
    """Cortante en una direccion. Vu en kN; bw, d en m; Av_s en mm2/m."""
    fc_m = fc / 1000.0
    fy_m = fy / 1000.0
    bw_mm = bw * 1000.0
    d_mm = d * 1000.0
    phi = 0.75

    Vc = 0.17 * lam * math.sqrt(fc_m) * bw_mm * d_mm / 1000.0  # kN
    phiVc = phi * Vc
    Vu_abs = abs(Vu)

    Vs_max = 0.66 * math.sqrt(fc_m) * bw_mm * d_mm / 1000.0
    note = ""
    Av_s_req = 0.0
    if Vu_abs > phiVc:
        Vs_req = Vu_abs / phi - Vc
        if Vs_req > Vs_max:
            note = "Vs supera el limite 0.66*sqrt(f'c)*bw*d: ampliar la seccion."
        Av_s_req = Vs_req * 1000.0 / (fy_m * d_mm) * 1000.0  # mm2/m

    Vs_prov = Av_s_prov / 1000.0 * fy_m * d_mm / 1000.0 if Av_s_prov else 0.0
    phiVn = phi * (Vc + min(Vs_prov, Vs_max))
    ratio = Vu_abs / phiVn if phiVn > 0 else float("inf")
    return ShearCheck(
        Vu=round(Vu_abs, 2), phiVc=round(phiVc, 2), phiVn=round(phiVn, 2),
        Av_s_req=round(Av_s_req, 1), ratio=round(ratio, 3),
        ok=ratio <= 1.0 and not note, note=note,
    )


# --------------------------------------------------------------------------
# Interaccion P-M en seccion circular
# --------------------------------------------------------------------------
@dataclass
class CircularColumn:
    D: float            # m
    cover: float        # m (al estribo)
    num_bars: int
    bar_size: str
    tie_size: str = "#4"
    fc: float = 21000.0  # kPa
    fy: float = 420000.0  # kPa
    spiral: bool = False

    @property
    def R_mm(self) -> float:
        return self.D * 1000.0 / 2.0

    @property
    def Ab(self) -> float:
        return bar_area(self.bar_size)

    @property
    def Ast(self) -> float:
        return self.num_bars * self.Ab

    @property
    def Ag(self) -> float:
        return math.pi * (self.D * 1000.0) ** 2 / 4.0

    @property
    def rho(self) -> float:
        return self.Ast / self.Ag

    def bar_positions(self) -> list[float]:
        """Distancia de cada barra a la fibra extrema en compresion, en mm."""
        rs = self.R_mm - self.cover * 1000.0 - bar_diam(self.tie_size) - bar_diam(self.bar_size) / 2.0
        return [
            self.R_mm - rs * math.cos(2.0 * math.pi * i / self.num_bars)
            for i in range(self.num_bars)
        ]

    # -- diagrama ----------------------------------------------------------
    def _segment(self, a: float) -> tuple[float, float]:
        """Area (mm2) y centroide respecto al centro (mm) del segmento circular de altura a."""
        R = self.R_mm
        a = max(0.0, min(a, 2.0 * R))
        if a <= 0.0:
            return 0.0, 0.0
        if a >= 2.0 * R:
            return math.pi * R * R, 0.0
        alpha = math.acos((R - a) / R)
        area = R * R * (alpha - math.sin(alpha) * math.cos(alpha))
        if area <= 0.0:
            return 0.0, 0.0
        ybar = (2.0 * R ** 3 * math.sin(alpha) ** 3) / (3.0 * area)
        return area, ybar

    def point_at_c(self, c: float) -> tuple[float, float, float]:
        """(phiPn [kN], phiMn [kN*m], eps_t) para una profundidad de eje neutro c en mm."""
        fc_m = self.fc / 1000.0
        fy_m = self.fy / 1000.0
        b1 = beta1(fc_m)
        a = b1 * c
        Aseg, ybar = self._segment(a)
        Cc = 0.85 * fc_m * Aseg  # N

        Pn = Cc
        Mn = Cc * ybar  # N*mm, respecto al centro
        eps_t = -1.0
        for d_i in self.bar_positions():
            eps = EPS_CU * (c - d_i) / c if c > 0 else -0.01
            fs = max(-fy_m, min(fy_m, ES * eps))
            if d_i <= a:  # la barra cae dentro del bloque comprimido
                fs -= 0.85 * fc_m
            F = fs * self.Ab  # N
            Pn += F
            Mn += F * (self.R_mm - d_i)
            eps_t = max(eps_t, -eps)

        eps_t = max(eps_t, 0.0)
        phi = phi_flexure(eps_t, fy_m, self.spiral)
        Po = 0.85 * fc_m * (self.Ag - self.Ast) + fy_m * self.Ast  # N
        Pmax = (0.85 if self.spiral else 0.80) * phi * Po / 1000.0  # kN
        phiPn = min(phi * Pn / 1000.0, Pmax)
        phiMn = phi * Mn / 1e6
        return phiPn, phiMn, eps_t

    def interaction(self, n: int = 40) -> list[tuple[float, float]]:
        """Diagrama (phiPn, phiMn) desde flexion pura hasta compresion maxima."""
        R = self.R_mm
        pts: list[tuple[float, float]] = []
        for i in range(1, n + 1):
            c = 2.2 * R * i / n
            p, mcap, _ = self.point_at_c(c)
            pts.append((p, mcap))
        # Traccion pura
        fy_m = self.fy / 1000.0
        pts.append((-0.90 * fy_m * self.Ast / 1000.0, 0.0))
        return sorted(pts, key=lambda t: t[0])

    def capacity_at_P(self, Pu: float) -> float:
        """phiMn disponible para una carga axial Pu (kN, compresion positiva)."""
        pts = self.interaction()
        if Pu <= pts[0][0]:
            return pts[0][1]
        if Pu >= pts[-1][0]:
            return pts[-1][1]
        for (p0, m0), (p1, m1) in zip(pts, pts[1:]):
            if p0 <= Pu <= p1:
                if abs(p1 - p0) < 1e-9:
                    return max(m0, m1)
                t = (Pu - p0) / (p1 - p0)
                return m0 + t * (m1 - m0)
        return pts[-1][1]


@dataclass
class ColumnCheck:
    Pu: float
    Mu: float
    phiMn: float
    ratio: float
    ok: bool
    rho: float
    diagram: list[tuple[float, float]] = field(default_factory=list)


def check_circular_column(col: CircularColumn, Pu: float, Mu: float) -> ColumnCheck:
    phiMn = col.capacity_at_P(Pu)
    ratio = abs(Mu) / phiMn if phiMn > 0 else float("inf")
    return ColumnCheck(
        Pu=round(Pu, 2), Mu=round(abs(Mu), 2), phiMn=round(phiMn, 2),
        ratio=round(ratio, 3), ok=ratio <= 1.0, rho=round(col.rho, 5),
        diagram=[(round(p, 1), round(mm, 1)) for p, mm in col.interaction(24)],
    )


@dataclass
class TorsionCheck:
    """Resultado del diseno por torsion de una seccion rectangular solida.

    Las areas de acero se devuelven en mm2 (o mm2/m para las cuantias por
    unidad de longitud) y los torsores en kN*m.
    """

    Tu: float           # kN*m, torsor mayorado
    T_threshold: float  # kN*m, umbral de 22.7.4 (phi*Tth)
    T_cr: float = 0.0   # kN*m, torsor de agrietamiento (22.7.5)
    significant: bool = False  # Tu > umbral -> hay que disenar
    Aoh: float = 0.0    # mm2, area encerrada por el eje del estribo cerrado
    ph: float = 0.0     # mm, perimetro del eje del estribo cerrado
    Ao: float = 0.0     # mm2, 0.85*Aoh
    At_s: float = 0.0   # mm2/m por RAMA, solo torsion (22.7.6.1a)
    Av_s: float = 0.0   # mm2/m totales por cortante (dos ramas)
    Avt_s_req: float = 0.0   # mm2/m, (Av + 2*At)/s requerido
    Avt_s_min: float = 0.0   # mm2/m, minimo de 9.6.4.2
    Avt_s: float = 0.0       # mm2/m, el que gobierna
    Al: float = 0.0     # mm2, longitudinal por torsion (22.7.6.1b)
    Al_min: float = 0.0  # mm2, minimo de 9.6.4.3
    Al_adopt: float = 0.0  # mm2, el que gobierna
    s_max: float = 0.0  # mm, min(ph/8, 300) segun 9.7.6.3.3
    s_req: float = 0.0  # mm, separacion que satisface area y limites
    tie_size: str = ""
    n_long_bars: int = 0
    long_bar_size: str = ""
    stress_ratio: float = 0.0  # D/C del limite de seccion 22.7.7.1
    section_ok: bool = True
    redistributed: bool = False
    note: str = ""


def torsion_threshold(Tu: float, b: float, h: float, fc: float, lam: float = 1.0) -> TorsionCheck:
    """Solo el umbral de 22.7.4 y el torsor de agrietamiento, sin disenar."""
    fc_m = fc / 1000.0
    acp = b * 1000.0 * h * 1000.0      # mm2
    pcp = 2.0 * (b + h) * 1000.0       # mm
    t_thr = 0.75 * 0.083 * lam * math.sqrt(fc_m) * acp * acp / pcp / 1e6  # kN*m
    t_cr = 0.33 * lam * math.sqrt(fc_m) * acp * acp / pcp / 1e6           # kN*m
    sig = abs(Tu) > t_thr
    return TorsionCheck(
        Tu=round(abs(Tu), 2), T_threshold=round(t_thr, 2), T_cr=round(t_cr, 2),
        significant=sig,
        note=("Torsion significativa: requiere estribos cerrados y refuerzo longitudinal "
              "por torsion segun ACI 318 22.7." if sig else ""),
    )


def torsion_design(Tu: float, Vu: float, b: float, h: float, d: float,
                   fc: float, fy: float, cover: float,
                   tie_size: str = "#4", long_bar_size: str = "#5",
                   Av_s_req: float = 0.0, fyt: float | None = None,
                   lam: float = 1.0, compatibility: bool = False,
                   theta_deg: float = 45.0) -> TorsionCheck:
    """Diseno por torsion de una seccion rectangular solida (ACI 318-19 22.7).

    Entradas en kN, m, kPa. `Av_s_req` es el acero transversal que ya pide el
    cortante, en mm2/m contando las dos ramas; se suma al de torsion porque los
    estribos son los mismos. `compatibility=True` habilita la redistribucion de
    22.7.5 (la torsion de compatibilidad puede reducirse a phi*Tcr); en la viga
    cabezal de un muro la torsion es de **equilibrio** -- nace del voladizo de
    la pantalla y no tiene camino alterno --, asi que el valor por defecto es
    False.

    Devuelve el acero transversal por rama (At/s), el total combinado
    (Av + 2*At)/s con su minimo, el longitudinal Al con el suyo, y la
    separacion de estribos que cumple area y limites geometricos.
    """
    chk = torsion_threshold(Tu, b, h, fc, lam)
    chk.Av_s = round(Av_s_req, 1)
    chk.tie_size = tie_size
    chk.long_bar_size = long_bar_size

    fc_m = fc / 1000.0
    fy_m = fy / 1000.0
    fyt_m = (fyt / 1000.0) if fyt else fy_m
    b_mm, h_mm, d_mm = b * 1000.0, h * 1000.0, d * 1000.0
    cover_mm = cover * 1000.0
    db_tie = bar_diam(tie_size)
    phi = 0.75
    cot = 1.0 / math.tan(math.radians(theta_deg))

    # Geometria del estribo cerrado: Aoh se mide al EJE del estribo.
    x1 = b_mm - 2.0 * cover_mm - db_tie
    y1 = h_mm - 2.0 * cover_mm - db_tie
    if x1 <= 0.0 or y1 <= 0.0:
        chk.note = "El recubrimiento consume la seccion: revise el cover y el diametro del estribo."
        chk.section_ok = False
        return chk
    Aoh = x1 * y1
    ph = 2.0 * (x1 + y1)
    Ao = 0.85 * Aoh
    chk.Aoh, chk.ph, chk.Ao = round(Aoh, 0), round(ph, 0), round(Ao, 0)

    # Limite geometrico de separacion (9.7.6.3.3), se disene o no por torsion.
    chk.s_max = round(min(ph / 8.0, 300.0), 0)

    if not chk.significant:
        chk.note = ("Torsion despreciable (Tu <= umbral de 22.7.4): no requiere "
                    "refuerzo adicional por torsion.")
        return chk

    Tu_abs = abs(Tu)
    if compatibility and Tu_abs > phi * chk.T_cr:
        Tu_abs = phi * chk.T_cr
        chk.redistributed = True
    Tu_nmm = Tu_abs * 1e6
    Vu_n = abs(Vu) * 1000.0

    # ---- limite de la seccion (22.7.7.1a, seccion solida) ----------------
    Vc = 0.17 * lam * math.sqrt(fc_m) * b_mm * d_mm  # N
    demand = math.sqrt((Vu_n / (b_mm * d_mm)) ** 2
                       + (Tu_nmm * ph / (1.7 * Aoh * Aoh)) ** 2)
    capacity = phi * (Vc / (b_mm * d_mm) + 0.66 * math.sqrt(fc_m))
    chk.stress_ratio = round(demand / capacity, 3) if capacity > 0 else float("inf")
    chk.section_ok = chk.stress_ratio <= 1.0

    # ---- acero transversal por torsion (22.7.6.1a) -----------------------
    At_s = Tu_nmm / (phi * 2.0 * Ao * fyt_m * cot)       # mm2/mm por rama
    chk.At_s = round(At_s * 1000.0, 1)

    avt_req = Av_s_req + 2.0 * At_s * 1000.0             # mm2/m: dos ramas + torsion
    avt_min = max(0.062 * math.sqrt(fc_m) * b_mm / fyt_m,
                  0.35 * b_mm / fyt_m) * 1000.0          # mm2/m (9.6.4.2)
    avt = max(avt_req, avt_min)
    chk.Avt_s_req = round(avt_req, 1)
    chk.Avt_s_min = round(avt_min, 1)
    chk.Avt_s = round(avt, 1)

    # ---- acero longitudinal (22.7.6.1b y 9.6.4.3) ------------------------
    Al = At_s * ph * (fyt_m / fy_m) * cot * cot          # mm2
    At_s_for_min = max(At_s, 0.175 * b_mm / fyt_m)       # 9.6.4.3 acota At/s
    acp = b_mm * h_mm
    Al_min = max(0.42 * math.sqrt(fc_m) * acp / fy_m
                 - At_s_for_min * ph * (fyt_m / fy_m), 0.0)
    Al_use = max(Al, Al_min)
    chk.Al = round(Al, 1)
    chk.Al_min = round(Al_min, 1)
    chk.Al_adopt = round(Al_use, 1)

    # ---- separacion de estribos y barras longitudinales ------------------
    # Estribo cerrado de dos ramas: el area disponible por metro es 2*Ab/s.
    s_area = 2.0 * bar_area(tie_size) * 1000.0 / avt if avt > 0 else chk.s_max
    s_req = math.floor(min(s_area, chk.s_max) / 10.0) * 10.0   # a multiplo de 10 mm
    chk.s_req = max(s_req, 50.0)

    # 9.7.5.1: barras repartidas en el perimetro a no mas de 300 mm, una en
    # cada esquina, y diametro no menor que 0.042*s ni que una #3.
    ab = bar_area(long_bar_size)
    n_area = math.ceil(Al_use / ab) if ab > 0 else 0
    n_perim = math.ceil(ph / 300.0)
    chk.n_long_bars = int(max(4, n_perim, n_area))

    notes = []
    if not chk.section_ok:
        notes.append("La seccion no admite la combinacion V+T (22.7.7.1, D/C = %.2f): "
                     "amplie el ancho o el canto." % chk.stress_ratio)
    if chk.redistributed:
        notes.append("Torsion de compatibilidad redistribuida a phi*Tcr = %.1f kN-m (22.7.5)."
                     % (phi * chk.T_cr))
    if avt_min > avt_req:
        notes.append("Gobierna el estribo minimo de 9.6.4.2.")
    if Al_min > Al:
        notes.append("Gobierna el longitudinal minimo de 9.6.4.3.")
    db_min = max(0.042 * chk.s_req, bar_diam("#3"))
    if bar_diam(long_bar_size) < db_min:
        notes.append("La barra longitudinal por torsion debe ser de al menos %.1f mm (9.7.5.1)."
                     % db_min)
    notes.append("Estribos CERRADOS %s @ %.0f mm (%.0f mm2/m incluyendo el cortante) mas "
                 "%d barras %s repartidas en el perimetro (Al = %.0f mm2), adicionales "
                 "al refuerzo por flexion."
                 % (tie_size, chk.s_req, avt, chk.n_long_bars, long_bar_size, Al_use))
    chk.note = " ".join(notes)
    return chk


def shear_circular(Vu: float, col: CircularColumn, tie_spacing: float, legs: int = 2) -> ShearCheck:
    """Cortante en pila circular: bw = D, d = 0.8D (ACI 22.5.2.2)."""
    d = 0.8 * col.D
    Av_s = legs * bar_area(col.tie_size) / tie_spacing  # mm2/m
    return shear_check(Vu, col.D, d, col.fc, col.fy, Av_s_prov=Av_s)

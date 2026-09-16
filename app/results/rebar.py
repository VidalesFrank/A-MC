"""Despiece: de las areas de acero requeridas a barras reales.

Toma las verificaciones de `extract.verify` y produce la planilla de aceros de
cada elemento —marca, diametro, forma, dimensiones de doblado, longitud,
cantidad y peso—, que es lo que necesita el dibujante y lo que va a la memoria.

Longitudes de desarrollo, ganchos y traslapos segun ACI 318-19 capitulo 25.
Unidades de entrada kN, m, kPa; las dimensiones de doblado salen en mm y las
longitudes de barra en m.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..core.params import WallProject
from . import design as D

DENSIDAD_ACERO = 7850.0     # kg/m3
LARGO_COMERCIAL = 12.0      # m, largo de barra de fabrica
SOLAPE_MIN = 0.30           # m

# Diametro interior de doblado (ACI 25.3.1), en multiplos de db
_DOBLADO = {"#3": 6, "#4": 6, "#5": 6, "#6": 6, "#7": 6, "#8": 6,
            "#9": 8, "#10": 8, "#11": 8, "#14": 10, "#18": 10}


def peso_ml(bar_size: str) -> float:
    """Peso por metro lineal de la barra, en kg/m."""
    return D.bar_area(bar_size) * 1e-6 * DENSIDAD_ACERO


def diam_doblado(bar_size: str) -> float:
    """Diametro interior de doblado en mm (ACI 25.3.1)."""
    return _DOBLADO.get(bar_size, 8) * D.bar_diam(bar_size)


# --------------------------------------------------------------------------
# Longitudes de desarrollo y ganchos (ACI 318-19, 25.4)
# --------------------------------------------------------------------------
def ld_traccion(bar_size: str, fc: float, fy: float, lam: float = 1.0,
                psi_t: float = 1.0, psi_e: float = 1.0) -> float:
    """Longitud de desarrollo en traccion, en m (25.4.2.3, caso simplificado).

    Se usa la forma simplificada de la tabla 25.4.2.3 asumiendo separacion y
    recubrimiento adecuados, que es lo que dan las mallas y los armados de este
    modelo. Para barras #7 y mayores el denominador baja de 2.1 a 1.7.
    """
    db = D.bar_diam(bar_size)
    fc_m, fy_m = fc / 1000.0, fy / 1000.0
    k = 2.1 if int(bar_size.lstrip("#")) <= 6 else 1.7
    ld = fy_m * psi_t * psi_e / (k * lam * math.sqrt(fc_m)) * db
    return max(ld, 300.0) / 1000.0


def ldh_gancho(bar_size: str, fc: float, fy: float, lam: float = 1.0,
               psi_e: float = 1.0, psi_r: float = 1.0, psi_o: float = 1.0) -> float:
    """Longitud de desarrollo de un gancho estandar, en m (25.4.3.1)."""
    db = D.bar_diam(bar_size)
    fc_m, fy_m = fc / 1000.0, fy / 1000.0
    ldh = (fy_m * psi_e * psi_r * psi_o / (23.0 * lam * math.sqrt(fc_m))) * db ** 1.5
    return max(ldh, 8.0 * db, 150.0) / 1000.0


def solape_clase_b(bar_size: str, fc: float, fy: float) -> float:
    """Traslapo por solape clase B, en m (25.5.2.1)."""
    return max(1.3 * ld_traccion(bar_size, fc, fy), SOLAPE_MIN)


def ext_gancho(bar_size: str, grados: int = 90) -> float:
    """Extension recta del gancho estandar, en m (25.3.1 / 25.3.2)."""
    db = D.bar_diam(bar_size)
    if grados == 180:
        return max(4.0 * db, 65.0) / 1000.0
    if grados == 135:
        return max(6.0 * db, 75.0) / 1000.0
    return 12.0 * db / 1000.0


# --------------------------------------------------------------------------
# Seleccion de barras
# --------------------------------------------------------------------------
def n_barras(As: float, bar_size: str, n_min: int = 2) -> int:
    """Numero de barras para cubrir As [mm2]."""
    ab = D.bar_area(bar_size)
    return int(max(n_min, math.ceil(As / ab - 1e-9))) if ab > 0 else n_min


def separacion_malla(As_por_m: float, bar_size: str, s_max: float = 450.0,
                     s_min: float = 75.0, modulo: float = 25.0) -> float:
    """Separacion de malla en mm para cubrir As [mm2/m] con esa barra.

    Se redondea hacia abajo al modulo para que el area colocada nunca quede por
    debajo de la requerida, y se acota por el maximo normativo.
    """
    ab = D.bar_area(bar_size)
    if As_por_m <= 0.0:
        return s_max
    s = 1000.0 * ab / As_por_m
    s = math.floor(min(s, s_max) / modulo) * modulo
    return max(s, s_min)


def as_de_malla(bar_size: str, s_mm: float) -> float:
    """Area realmente colocada por metro con esa barra a esa separacion."""
    return 1000.0 * D.bar_area(bar_size) / s_mm if s_mm > 0 else 0.0


def _piezas(largo_total: float, bar_size: str, fc: float, fy: float) -> tuple[int, float]:
    """Trocea una corrida larga en barras comerciales con solape clase B.

    Devuelve (numero de piezas, largo de cada pieza) tratando todas las piezas
    como iguales, que es como se pide en obra.
    """
    if largo_total <= LARGO_COMERCIAL:
        return 1, largo_total
    lap = solape_clase_b(bar_size, fc, fy)
    n = int(math.ceil((largo_total - lap) / (LARGO_COMERCIAL - lap)))
    largo = (largo_total + (n - 1) * lap) / n
    return n, largo


# --------------------------------------------------------------------------
# Marca de despiece
# --------------------------------------------------------------------------
@dataclass
class Marca:
    """Una linea de la planilla de aceros."""

    marca: str
    elemento: str
    posicion: str
    bar_size: str
    forma: str          # recta | L | U | estribo_rect | estribo_circ
    dims: list[float] = field(default_factory=list)   # tramos rectos en mm
    largo: float = 0.0  # m por pieza
    cantidad: int = 0
    nota: str = ""
    # Lo que pide el calculo frente a lo que se coloca. Cuando el ingeniero
    # ajusta el armado a mano hay que poder ver si el ajuste sigue cubriendo la
    # demanda, no solo que el dibujo cambie.
    as_req: float = 0.0
    as_prov: float = 0.0
    unidad: str = ""            # mm2 | mm2/m
    ajustado: bool = False      # el valor viene de un override, no del calculo
    # Lo que la interfaz necesita para poner el valor actual en el control de
    # edicion sin tener que parsear la nota
    s_mm: float = 0.0           # separacion de malla o de estribos
    s_rec_mm: float = 0.0       # la que recomienda el calculo
    n_elem: int = 0             # barras por seccion (longitudinal), no piezas
    franja: int = 0             # franja del muro a la que pertenece

    @property
    def cumple(self) -> bool:
        return self.as_req <= 0.0 or self.as_prov >= self.as_req * 0.999

    @property
    def db(self) -> float:
        return D.bar_diam(self.bar_size)

    @property
    def peso_unitario(self) -> float:
        return self.largo * peso_ml(self.bar_size)

    @property
    def peso_total(self) -> float:
        return self.peso_unitario * self.cantidad

    @property
    def largo_total(self) -> float:
        return self.largo * self.cantidad

    def as_dict(self) -> dict:
        return {
            "marca": self.marca, "elemento": self.elemento, "posicion": self.posicion,
            "diametro": self.bar_size, "db_mm": round(self.db, 1), "forma": self.forma,
            "dims_mm": [round(d, 0) for d in self.dims],
            "largo_m": round(self.largo, 3), "cantidad": self.cantidad,
            "largo_total_m": round(self.largo_total, 2),
            "peso_unitario_kg": round(self.peso_unitario, 2),
            "peso_total_kg": round(self.peso_total, 1),
            "as_req": round(self.as_req, 1), "as_prov": round(self.as_prov, 1),
            "unidad": self.unidad, "ajustado": self.ajustado, "cumple": self.cumple,
            "s_mm": round(self.s_mm, 0), "s_rec_mm": round(self.s_rec_mm, 0),
            "n_elem": self.n_elem, "franja": self.franja,
            "nota": self.nota,
        }


class _Numerador:
    """Marcas correlativas por prefijo de elemento: P1, P2, VC1, M1..."""

    def __init__(self) -> None:
        self._n: dict[str, int] = {}

    def __call__(self, prefijo: str) -> str:
        self._n[prefijo] = self._n.get(prefijo, 0) + 1
        return "%s%d" % (prefijo, self._n[prefijo])


# --------------------------------------------------------------------------
# Pilas
# --------------------------------------------------------------------------
def despiece_pilas(p: WallProject, checks: dict, num: _Numerador) -> list[Marca]:
    """Longitudinal por zona y zuncho/estribo circular, pila a pila.

    Cada pila se recorre por separado: su cabeza, su punta y sus zonas. Los
    tramos que salen identicos se juntan en una sola marca, de modo que un
    grupo de pilas iguales sigue dando una marca y no cinco, pero una pila con
    armado propio queda separada y rotulada.

    El longitudinal de la zona superior entra en la viga cabezal con gancho
    estandar; entre zonas se solapa clase B, salvo cuando el tramo ya termina
    en la punta.
    """
    fc = p.materials.concrete.fc
    fy = p.materials.rebar.fy
    ys = p.pile_y_positions()
    cabezas = p.piles.z_tops(p.wall, ys)
    out: list[Marca] = []

    # ---- tramos reales de cada pila --------------------------------------
    grupos: dict[tuple, list[int]] = {}
    for i in range(len(ys)):
        n = i + 1
        z_top, z_bot = cabezas[i], p.piles.z_bot_of(i)
        tramos = []
        for zona in p.piles.zones_of(n):
            hi = min(zona.z_hi, z_top)
            lo = max(zona.z_lo, z_bot)
            if hi - lo > 1e-6:
                tramos.append((zona, hi, lo))
        for j, (zona, hi, lo) in enumerate(tramos):
            clave = (
                zona.name, round(hi, 3), round(lo, 3),
                zona.rebar.bar_size, zona.rebar.num_bars, zona.rebar.cover,
                zona.rebar.tie_size, zona.rebar.tie_spacing,
                j == 0,                                  # arranca en la viga
                abs(lo - z_bot) < 1e-6,                  # termina en la punta
            )
            grupos.setdefault(clave, []).append(n)

    # ---- una marca por tramo distinto ------------------------------------
    todas = len(ys)
    for clave in sorted(grupos, key=lambda c: (-c[1], c[0])):
        (nombre, z_hi, z_lo, bar, n_barras, rec,
         tie, s_tie, es_superior, llega_punta) = clave
        pilas = sorted(grupos[clave])
        h = z_hi - z_lo
        lap = solape_clase_b(bar, fc, fy)

        pos = "Zona %s (z %.2f a %.2f)" % (nombre, z_hi, z_lo)
        if len(pilas) < todas:
            pos += " — pilas %s" % ", ".join(str(v) for v in pilas)

        # La barra baja hasta solapar clase B con la zona de abajo, salvo
        # cuando este tramo ya termina en la punta de la pila.
        tramo = h if llega_punta else h + lap
        notas = ["hasta la punta de la pila" if llega_punta else
                 "baja %.0f mm en solape clase B con la zona inferior" % (lap * 1000.0)]

        if es_superior:
            # La longitud de corte lleva la EXTENSION geometrica del gancho, no
            # su longitud de desarrollo: ldh es una comprobacion de anclaje.
            ext = ext_gancho(bar, 90)
            ldh = ldh_gancho(bar, fc, fy)
            largo = tramo + ext
            forma, dims = "L", [tramo * 1000.0, ext * 1000.0]
            notas.insert(0, "gancho 90 en la viga cabezal, extension %.0f mm "
                            "(ldh requerida %.0f mm)" % (ext * 1000.0, ldh * 1000.0))
        else:
            largo = tramo
            forma, dims = "recta", [largo * 1000.0]

        npz, largo_pieza = _piezas(largo, bar, fc, fy)
        if npz > 1:
            forma, dims = "recta", [largo_pieza * 1000.0]
            notas.append("%d piezas por barra" % npz)
        out.append(Marca(
            marca=num("P"), elemento="Pila", posicion=pos + " — longitudinal",
            bar_size=bar, forma=forma, dims=dims,
            largo=largo_pieza, cantidad=n_barras * len(pilas) * npz,
            as_prov=n_barras * D.bar_area(bar), unidad="mm2",
            n_elem=n_barras,
            nota=("%d%s por pila.  " % (n_barras, bar)) + "; ".join(notas).capitalize(),
        ))

        # Estribo/zuncho circular
        d_estribo = p.piles.diameter - 2.0 * rec - D.bar_diam(tie) / 1000.0
        perim = math.pi * d_estribo
        gan = 2.0 * ext_gancho(tie, 135)
        n_est = int(math.floor(h / s_tie)) + 1
        out.append(Marca(
            marca=num("P"), elemento="Pila", posicion=pos + " — estribo circular",
            bar_size=tie, forma="estribo_circ",
            dims=[d_estribo * 1000.0, ext_gancho(tie, 135) * 1000.0],
            largo=perim + gan, cantidad=n_est * len(pilas),
            s_mm=s_tie * 1000.0, s_rec_mm=s_tie * 1000.0,
            nota="Ø%.2f m @ %.0f mm, ganchos 135 de %.0f mm"
                 % (d_estribo, s_tie * 1000.0, ext_gancho(tie, 135) * 1000.0),
        ))
    return out


# --------------------------------------------------------------------------
# Viga cabezal
# --------------------------------------------------------------------------
def despiece_viga(p: WallProject, checks: dict, num: _Numerador) -> list[Marca]:
    """Longitudinal superior e inferior, estribos cerrados y acero por torsion.

    Los campos de `p.rebar_overrides.viga` que no sean None mandan sobre el
    valor calculado, y la marca queda con `ajustado=True`.
    """
    if not p.cap_beam.enabled:
        return []
    ov = p.rebar_overrides.viga
    fc = p.materials.concrete.fc
    fy = p.materials.rebar.fy
    cb = p.cap_beam
    L = p.wall.length
    recs = checks.get("viga_cabezal") or []
    tor = checks.get("torsion_viga") or {}
    out: list[Marca] = []

    bar = ov.bar_size or cb.rebar.bar_size
    As_sup = max((r["As_req"] for r in recs), default=0.0)
    As_min = max((r["As_min"] for r in recs), default=0.0)
    As = max(As_sup, As_min)

    ext = ext_gancho(bar, 90)
    ldh = ldh_gancho(bar, fc, fy)
    tramo = L - 2.0 * cb.rebar.cover          # de cara a cara del concreto
    largo_total = tramo + 2.0 * ext           # mas los dos ganchos de extremo
    npz, largo_pieza = _piezas(largo_total, bar, fc, fy)

    for cara in ("superior", "inferior"):
        n_calc = n_barras(As, bar, n_min=2)
        n_ov = ov.n_sup if cara == "superior" else ov.n_inf
        n = n_ov or n_calc
        recta = npz > 1
        out.append(Marca(
            marca=num("VC"), elemento="Viga cabezal",
            posicion="Longitudinal %s" % cara, bar_size=bar,
            forma="recta" if recta else "U",
            dims=[largo_pieza * 1000.0] if recta
                 else [tramo * 1000.0, ext * 1000.0, ext * 1000.0],
            largo=largo_pieza, cantidad=n * npz,
            as_req=As, as_prov=n * D.bar_area(bar), unidad="mm2",
            ajustado=bool(n_ov) or bool(ov.bar_size), n_elem=n,
            nota="%d%s;  As requerido %.0f mm2 (%s), colocado %.0f mm2. "
                 "Gancho 90 de %.0f mm en los extremos (ldh %.0f mm)%s" % (
                     n, bar, As, "flexion" if As_sup >= As_min else "minimo",
                     n * D.bar_area(bar), ext * 1000.0, ldh * 1000.0,
                     "" if npz == 1 else "; %d piezas por barra, solape clase B" % npz),
        ))

    # Estribos cerrados: el paso lo fija la torsion si es significativa
    tie = ov.tie_size or cb.rebar.tie_size
    s_calc = (tor.get("s_estribo", cb.rebar.tie_spacing * 1000.0) / 1000.0) if tor \
        else cb.rebar.tie_spacing
    s = (ov.s_tie / 1000.0) if ov.s_tie else s_calc
    x1 = cb.width - 2.0 * cb.rebar.cover - D.bar_diam(tie) / 1000.0
    y1 = cb.depth - 2.0 * cb.rebar.cover - D.bar_diam(tie) / 1000.0
    perim = 2.0 * (x1 + y1)
    gan135 = ext_gancho(tie, 135)
    n_est = int(math.floor(L / s)) + 1
    out.append(Marca(
        marca=num("VC"), elemento="Viga cabezal", posicion="Estribo cerrado",
        bar_size=tie, forma="estribo_rect",
        dims=[x1 * 1000.0, y1 * 1000.0, gan135 * 1000.0],
        largo=perim + 2.0 * gan135, cantidad=n_est,
        as_req=(tor.get("Avt_s", 0.0) if tor else 0.0),
        as_prov=2.0 * D.bar_area(tie) / s / 1000.0 * 1000.0,
        unidad="mm2/m", ajustado=bool(ov.tie_size) or bool(ov.s_tie),
        s_mm=s * 1000.0, s_rec_mm=s_calc * 1000.0,
        nota="E%s cerrado @ %.0f mm (%.0f x %.0f mm)%s%s" % (
            tie, s * 1000.0, x1 * 1000.0, y1 * 1000.0,
            "; paso recomendado por torsion %.0f mm" % (s_calc * 1000.0) if tor else "",
            "" if not ov.s_tie else " [ajustado]"),
    ))

    # Longitudinal adicional por torsion, repartido en el perimetro
    if tor and tor.get("Al", 0.0) > 0.0:
        bt = ov.bar_torsion or tor.get("barra_torsion", bar)
        n_t = int(ov.n_torsion or tor.get("n_barras_torsion", 4))
        npz_t, largo_t = _piezas(L - 2.0 * cb.rebar.cover + 2.0 * ext_gancho(bt, 90),
                                 bt, fc, fy)
        out.append(Marca(
            marca=num("VC"), elemento="Viga cabezal",
            posicion="Longitudinal por torsion (perimetro)", bar_size=bt,
            forma="recta", dims=[largo_t * 1000.0],
            largo=largo_t, cantidad=n_t * npz_t,
            as_req=tor.get("Al", 0.0), as_prov=n_t * D.bar_area(bt), unidad="mm2",
            ajustado=bool(ov.bar_torsion) or bool(ov.n_torsion), n_elem=n_t,
            nota="%d%s en el perimetro a <= 300 mm (ACI 9.7.5.1), una en cada esquina; "
                 "Al requerido %.0f mm2, colocado %.0f mm2"
                 % (n_t, bt, tor.get("Al", 0.0), n_t * D.bar_area(bt)),
        ))
    return out


# --------------------------------------------------------------------------
# Pantalla
# --------------------------------------------------------------------------
def despiece_muro(p: WallProject, checks: dict, num: _Numerador,
                  bar_v: str = "#5", bar_h: str = "#5") -> list[Marca]:
    """Malla en dos caras, con el acero de cada franja.

    ACI 318 11.7.2.3 obliga a dos capas en muros de mas de 250 mm, cada una
    entre 1/3 y 2/3 del total. El acero de diseno va en la cara traccionada y la
    opuesta lleva el minimo repartido; luego se comprueba el reparto.
    """
    fc = p.materials.concrete.fc
    fy = p.materials.rebar.fy
    L = p.wall.length
    franjas = ((checks.get("muro") or {}).get("franjas") or {}).get("franjas") or []
    if not franjas:
        return []

    out: list[Marca] = []

    for f in franjas:
        # Con vastago acartelado el espesor lo fija la franja; los minimos de
        # muro y la separacion maxima van con el, no con el del arranque.
        t = f.get("espesor") or p.wall.thickness
        s_max = min(3.0 * t * 1000.0, 450.0)
        dos_capas = t > 0.25
        # minimos de muro (ACI 11.6.1): rho_l = 0.0012 vertical, rho_t = 0.0020 horizontal
        as_min_v = 0.0012 * t * 1000.0 * 1000.0   # mm2/m
        as_min_h = 0.0020 * t * 1000.0 * 1000.0

        h = f["z_fin"] - f["z_ini"]
        etiqueta = "Franja %d (z %.2f a %.2f)" % (f["franja"], f["z_ini"], f["z_fin"])
        # Un ajuste de franja se aplica a las DOS caras: es como se especifica en
        # obra. La cara menos solicitada queda sobrearmada, que es inofensivo.
        ov = p.rebar_overrides.franja(f["franja"])
        bv = (ov.bar_v if ov and ov.bar_v else bar_v)
        bh = (ov.bar_h if ov and ov.bar_h else bar_h)

        # ---- vertical -----------------------------------------------------
        As_v = max(f["vertical"]["As"], as_min_v)
        caras = [("cara de tierra", As_v)]
        if dos_capas:
            caras.append(("cara vista", max(as_min_v / 2.0, As_v / 3.0)))
        for cara, as_cara in caras:
            s_calc = separacion_malla(as_cara, bv, s_max)
            s = (ov.s_v if ov and ov.s_v else s_calc)
            n = int(math.floor(L / (s / 1000.0))) + 1
            base = f["franja"] == 1
            ext = ext_gancho(bv, 90)
            ldh = ldh_gancho(bv, fc, fy)
            lap_v = solape_clase_b(bv, fc, fy)
            tramo = h + (0.0 if base else lap_v)
            largo_total = tramo + (ext if base else 0.0)
            npz, largo = _piezas(largo_total, bv, fc, fy)
            recta = (not base) or npz > 1
            detalle = ("gancho 90 de %.0f mm en la viga cabezal (ldh %.0f mm)"
                       % (ext * 1000.0, ldh * 1000.0)) if base else \
                      ("baja %.0f mm en solape clase B con la franja inferior"
                       % (lap_v * 1000.0))
            out.append(Marca(
                marca=num("MV"), elemento="Pantalla",
                posicion="%s — vertical, %s" % (etiqueta, cara),
                bar_size=bv, forma="recta" if recta else "L",
                dims=[largo * 1000.0] if recta else [tramo * 1000.0, ext * 1000.0],
                largo=largo, cantidad=n * npz,
                as_req=as_cara, as_prov=as_de_malla(bv, s), unidad="mm2/m",
                ajustado=bool(ov and (ov.bar_v or ov.s_v)),
                s_mm=s, s_rec_mm=s_calc, franja=f["franja"],
                nota="%s @ %.0f mm (colocado %.0f, requerido %.0f mm2/m); %s%s"
                     % (bv, s, as_de_malla(bv, s), as_cara, detalle,
                        "  [ajustado; recomendado @ %.0f mm]" % s_calc
                        if ov and ov.s_v and abs(ov.s_v - s_calc) > 1 else ""),
            ))

        # ---- horizontal ---------------------------------------------------
        As_h = max(f["horizontal_apoyo"]["As"], f["horizontal_vano"]["As"], as_min_h)
        caras_h = [("cara de tierra", As_h / (2.0 if dos_capas else 1.0))]
        if dos_capas:
            caras_h.append(("cara vista", As_h / 2.0))
        for cara, as_cara in caras_h:
            s_calc = separacion_malla(as_cara, bh, s_max)
            s = (ov.s_h if ov and ov.s_h else s_calc)
            n_filas = max(int(math.floor(h / (s / 1000.0))), 1)
            npz, largo = _piezas(L - 0.10 + 2.0 * ext_gancho(bh, 90), bh, fc, fy)
            out.append(Marca(
                marca=num("MH"), elemento="Pantalla",
                posicion="%s — horizontal, %s" % (etiqueta, cara),
                bar_size=bh, forma="recta", dims=[largo * 1000.0],
                largo=largo, cantidad=n_filas * npz,
                as_req=as_cara, as_prov=as_de_malla(bh, s), unidad="mm2/m",
                ajustado=bool(ov and (ov.bar_h or ov.s_h)),
                s_mm=s, s_rec_mm=s_calc, franja=f["franja"],
                nota="%s @ %.0f mm (colocado %.0f, requerido %.0f mm2/m); %d corridas%s"
                     % (bh, s, as_de_malla(bh, s), as_cara, n_filas,
                        "  [ajustado; recomendado @ %.0f mm]" % s_calc
                        if ov and ov.s_h and abs(ov.s_h - s_calc) > 1 else ""),
            ))
    return out


# --------------------------------------------------------------------------
# Planilla completa
# --------------------------------------------------------------------------
def build_schedule(p: WallProject, checks: dict,
                   bar_v: str | None = None, bar_h: str | None = None) -> dict:
    """Planilla de aceros completa, agrupada por elemento y por diametro.

    Sin `bar_v`/`bar_h` se toman los de `p.rebar_overrides`, que es lo que hace
    que la lamina, el Excel y la memoria salgan siempre con el armado que el
    ingeniero dejo ajustado en la interfaz: una sola fuente de verdad.
    """
    bar_v = bar_v or p.rebar_overrides.bar_v
    bar_h = bar_h or p.rebar_overrides.bar_h
    num = _Numerador()
    marcas: list[Marca] = []
    marcas += despiece_pilas(p, checks, num)
    marcas += despiece_viga(p, checks, num)
    marcas += despiece_muro(p, checks, num, bar_v, bar_h)

    por_diam: dict[str, dict] = {}
    for m in marcas:
        d = por_diam.setdefault(m.bar_size, {"diametro": m.bar_size, "db_mm": round(m.db, 1),
                                             "largo_m": 0.0, "peso_kg": 0.0, "n_marcas": 0})
        d["largo_m"] += m.largo_total
        d["peso_kg"] += m.peso_total
        d["n_marcas"] += 1
    for d in por_diam.values():
        d["largo_m"] = round(d["largo_m"], 1)
        d["peso_kg"] = round(d["peso_kg"], 1)

    por_elem: dict[str, float] = {}
    for m in marcas:
        por_elem[m.elemento] = por_elem.get(m.elemento, 0.0) + m.peso_total

    peso = sum(m.peso_total for m in marcas)
    vol = _volumen_concreto(p)
    return {
        "marcas_insuficientes": [m.marca for m in marcas if not m.cumple],
        "marcas_ajustadas": [m.marca for m in marcas if m.ajustado],
        "marcas": [m.as_dict() for m in marcas],
        "por_diametro": sorted(por_diam.values(),
                               key=lambda r: int(r["diametro"].lstrip("#"))),
        "por_elemento": {k: round(v, 1) for k, v in sorted(por_elem.items())},
        "peso_total_kg": round(peso, 1),
        "volumen_concreto_m3": round(vol, 2),
        "cuantia_kg_m3": round(peso / vol, 1) if vol > 0 else None,
        "barra_vertical_muro": bar_v,
        "barra_horizontal_muro": bar_h,
        "nota": ("Longitudes de desarrollo, ganchos y traslapos segun ACI 318-19 cap. 25, "
                 "con barra comercial de %.0f m y solape clase B. Las dimensiones de "
                 "doblado son al eje de la barra." % LARGO_COMERCIAL),
    }


def _volumen_concreto(p: WallProject) -> float:
    """Volumen de concreto de pantalla, viga cabezal y pilas, en m3.

    El area del alzado se integra como corona MENOS base: con la base en
    pendiente, quedarse con la corona sola mide desde el datum y no desde el
    arranque, y el resultado no tiene nada que ver con el muro.
    """
    w = p.wall
    y0, y1 = w.y_start, w.y_end
    n_int = 200
    dy = (y1 - y0) / n_int
    area = 0.0
    for k in range(n_int):
        ya, yb = y0 + k * dy, y0 + (k + 1) * dy
        ha = max(w.crown_at(ya) - w.base_at(ya), 0.0)
        hb = max(w.crown_at(yb) - w.base_at(yb), 0.0)
        area += 0.5 * (ha + hb) * dy
    vol = area * w.thickness_mean
    if p.cap_beam.enabled:
        # La viga recorre todo el muro cuando lleva voladizos; si no, solo de
        # pila extrema a pila extrema.
        ys = p.pile_y_positions()
        largo = (y1 - y0) if p.cap_beam.overhangs else (ys[-1] - ys[0])
        vol += p.cap_beam.width * p.cap_beam.depth * largo
    ys = p.pile_y_positions()
    tops = p.piles.z_tops(w, ys)
    vol += sum(math.pi * p.piles.diameter ** 2 / 4.0 * (tops[i] - p.piles.z_bot_of(i))
               for i in range(len(ys)))
    return vol

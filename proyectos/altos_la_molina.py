"""Muro de Altos de La Molina — Guarne, Antioquia.

Traduce el estudio geologico-geotecnico 017-2026 de IDEAR+ a dos proyectos de
la herramienta, uno por tramo. La junta de contraccion de la abscisa K0+011.00
separa el muro en dos estructuras independientes (numeral 6.10.2 del estudio),
asi que se modelan por separado, que es exactamente como trabajan.

    python proyectos/altos_la_molina.py        # resumen de los dos tramos

Convenio de cotas
-----------------
Z = 0 en la corona del muro, que es horizontal en los 17.00 m (la rasante de la
via menos los 1.50 m del talud revestido). El fondo de la excavacion baja
0.2647 m/m, de modo que la base del muro, la viga cabezal y las cabezas de pila
van en pendiente y la altura del vastago crece con la abscisa.

    h(x) = 0.2647 * x      con x en abscisas del muro (K0+x)

Lo que viene del estudio y no se recalcula
------------------------------------------
- Diagrama de presiones (tabla 40 y 41). El estudio lo obtiene por cuna de
  prueba sobre el perfil real, no por Rankine ni Coulomb, asi que aqui se
  reproduce con K impuesto: K = (p_arranque - p_corona) / (gamma*h) y la
  sobrecarga de 12 kPa da la ordenada de corona, K*q. Los dos tramos salen con
  K distinto porque el talud de la corona pesa relativamente mas en el muro
  bajo.
- Incremento sismico (tabla 41), triangulo invertido: dK = p_corona/(gamma*h).
- Geometria, longitudes de pila y n_h (tablas 14, 28, 29 y 45).
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.params import (  # noqa: E402
    CapBeamGeometry, Concrete, EarthPressure, Materials, MeshParams,
    PileGeometry, PileZone, ProjectInfo, Rebar, RebarCircular, RebarRect,
    Seismic, SoilProfile, WallGeometry, WallProject,
)

# --------------------------------------------------------------------------
# Datos comunes del estudio
# --------------------------------------------------------------------------
PENDIENTE = 0.2647          # m de profundidad por m de abscisa (numeral 6.1)
GAMMA = 17.5                # kN/m3, tabla 11
Q = 12.0                    # kPa, sobrecarga vehicular CCP-14
KH = 0.180                  # coeficiente sismico seudoestatico, numeral 5.3
NH = 7500.0                 # kN/m3, modulo de reaccion horizontal, tabla 45
FC = 21000.0                # kPa
REC_PILA = 0.075            # tabla 48
REC_VIGA = 0.050

# Cajetin. Van vacios a proposito: son datos personales y este archivo se
# publica. Rellenelos en su copia, o desde el panel «Proyecto» de la app, que
# los guarda en el .json del proyecto y no en el codigo.
#
#     INGENIERO = "Nombre Apellido"
#     MATRICULA = "00000-0000000 XXX"   # matricula profesional, junto a la firma
#     CLIENTE   = "Quien encarga el diseno estructural"
INGENIERO = ""
MATRICULA = ""
CLIENTE = ""


def _k(p_corona: float, p_arranque: float, h: float) -> float:
    """K que reproduce la pendiente del trapecio del estudio.

    La ordenada de corona no hace falta imponerla: sale sola como K*q con la
    sobrecarga de 12 kPa del propio estudio, y coincide con la tabla 40.
    """
    return (p_arranque - p_corona) / (GAMMA * h)


def _dk(p_corona: float, h: float) -> float:
    """dKae que reproduce el triangulo invertido del incremento sismico."""
    return p_corona / (GAMMA * h)


def _materiales() -> Materials:
    return Materials(concrete=Concrete(name="f'c_21 MPa", fc=FC, gamma=24.0),
                     rebar=Rebar(name="420 MPa", fy=420000.0))


def _tramo(nombre: str, x_ini: float, x_fin: float,
           esp_corona: float, esp_base: float,
           viga_b: float, viga_h: float,
           diam: float, x_pilas: list[float], largos: list[float],
           p_corona: float, p_arranque: float, p_sismo: float) -> WallProject:
    """Arma un tramo a partir de sus abscisas del muro y los datos del estudio."""
    L = x_fin - x_ini
    z_base = [(0.0, -PENDIENTE * x_ini), (L, -PENDIENTE * x_fin)]
    h_max = PENDIENTE * x_fin

    ys = [x - x_ini for x in x_pilas]
    cabezas = [-PENDIENTE * x for x in x_pilas]
    puntas = [zc - lg for zc, lg in zip(cabezas, largos)]

    K = _k(p_corona, p_arranque, h_max)
    dK = _dk(p_sismo, h_max)

    # Zonas de refuerzo de la pila: la superior toma el 45 % de la pila mas
    # larga, que es donde vive el momento del mecanismo de pila larga.
    z_cabeza = max(cabezas)
    z_punta = min(puntas)
    z_corte = z_cabeza - 0.45 * (z_cabeza - z_punta)

    return WallProject(
        info=ProjectInfo(
            name="Altos de La Molina — %s" % nombre,
            engineer=INGENIERO,
            license=MATRICULA,
            client=CLIENTE,
            notes=("Estudio geologico-geotecnico 017-2026, IDEAR+ Ingenieria y "
                   "Geotecnia S.A.S. Abscisas del muro K0+%06.2f a K0+%06.2f."
                   % (x_ini, x_fin)),
        ),
        materials=_materiales(),
        wall=WallGeometry(
            name="M_%.2f" % esp_base,
            thickness=esp_base, thickness_top=esp_corona,
            length=L, z_base=-PENDIENTE * x_fin, z_top=0.0,
            crown_profile=[(0.0, 0.0), (L, 0.0)],
            base_profile=z_base,
        ),
        piles=PileGeometry(
            diameter=diam, y_positions=ys, z_top=max(cabezas),
            z_bot=min(puntas), z_bots=puntas,
            segment_length=0.5, tip_restraint=True,
            zones=[
                PileZone(name="P_%.2f_SUP" % diam, z_from=z_cabeza, z_to=z_corte,
                         rebar=RebarCircular(cover=REC_PILA, num_bars=16,
                                             bar_size="#8", tie_size="#4",
                                             tie_spacing=0.15)),
                PileZone(name="P_%.2f_INF" % diam, z_from=z_corte, z_to=z_punta,
                         rebar=RebarCircular(cover=REC_PILA, num_bars=16,
                                             bar_size="#6", tie_size="#4",
                                             tie_spacing=0.20)),
            ],
        ),
        cap_beam=CapBeamGeometry(
            name="VC_%.2fx%.2f" % (viga_b, viga_h),
            width=viga_b, depth=viga_h, overhangs=True,
            rebar=RebarRect(cover=REC_VIGA, num_bars_3=5, num_bars_2=3,
                            bar_size="#7", tie_size="#4", tie_spacing=0.10),
        ),
        soil=SoilProfile(nh=NH, water_table_z=None),
        earth=EarthPressure(method="usuario", K_user=K, gamma=GAMMA,
                            phi=30.0, delta=12.0, surcharge=Q),
        seismic=Seismic(enabled=True, kh=KH, method="usuario", dK_user=dK,
                        distribution="triangular_invertida",
                        include_inertia=True),
        mesh=MeshParams(wall_div_per_bay=4, wall_target_dz=0.5,
                        pile_segment=0.5, wall_design_strips=3),
    )


def tramo_1() -> WallProject:
    """K0+001.70 a K0+011.00 — 3 pilas Ø1.00, viga 1.00 x 0.45."""
    return _tramo(
        "Tramo 1", 1.70, 11.00,
        esp_corona=0.25, esp_base=0.35,
        viga_b=1.00, viga_h=0.45,
        diam=1.00, x_pilas=[2.90, 6.35, 9.80], largos=[4.00, 5.50, 6.00],
        p_corona=7.7, p_arranque=40.5, p_sismo=25.0,
    )


def tramo_2() -> WallProject:
    """K0+011.00 a K0+017.00 — 2 pilas Ø1.20, viga 1.20 x 0.60."""
    return _tramo(
        "Tramo 2", 11.00, 17.00,
        esp_corona=0.30, esp_base=0.50,
        viga_b=1.20, viga_h=0.60,
        diam=1.20, x_pilas=[12.28, 15.73], largos=[7.00, 8.50],
        p_corona=6.9, p_arranque=52.0, p_sismo=34.0,
    )


def tramos() -> list[WallProject]:
    return [tramo_1(), tramo_2()]


# --------------------------------------------------------------------------
if __name__ == "__main__":
    from app.core.builder import build
    from app.core.soil import PressureProfile

    # Lo que dice el estudio, para contrastar la traduccion (tablas 20 y 40)
    ESPERADO = {
        "Tramo 1": {"h": 2.91, "E": 70.1, "dE": 36.3, "p_base": 40.5, "p_cor": 7.7},
        "Tramo 2": {"h": 4.50, "E": 132.5, "dE": 76.6, "p_base": 52.0, "p_cor": 6.9},
    }

    for p in tramos():
        etq = p.info.name.split("— ")[1]
        esp = ESPERADO[etq]
        res = build(p)
        s = res.model.summary()
        press = PressureProfile(p)
        h = esp["h"]
        r = press.resultants(h)
        p_cor = press.at(0.0, 0.0, -h).total - press.at(0.0, 0.0, -h).seismic
        p_bas = press.at(-h, 0.0, -h).soil + press.at(-h, 0.0, -h).surcharge

        print("\n%s  —  %s" % (p.info.name, p.info.notes.split("Abscisas")[1].strip()))
        print("  muro %.2f m de largo, vastago %.2f -> %.2f m, %d pilas O%.2f"
              % (p.wall.length, p.wall.thickness_top, p.wall.thickness,
                 len(p.pile_y_positions()), p.piles.diameter))
        print("  punta de pila en Z = %s" % ", ".join("%.2f" % v for v in p.piles.z_bots))
        print("  modelo: %d nudos, %d frames, %d shells, %d resortes"
              % (s["joints"], s["frames"], s["areas"], s["springs"]))
        print("  K = %.4f   q_eq = %.2f kPa   dKae = %.4f" % (press.K, p.earth.surcharge, press.dK))
        print("  presion en corona   %7.2f kPa   estudio %7.2f" % (p_cor, esp["p_cor"]))
        print("  presion en arranque %7.2f kPa   estudio %7.2f" % (p_bas, esp["p_base"]))
        print("  empuje estatico     %7.2f kN/m  estudio %7.2f"
              % (r["P_suelo"] + r["P_sobrecarga"], esp["E"]))
        print("  incremento sismico  %7.2f kN/m  estudio %7.2f" % (r["P_sismo"], esp["dE"]))
        for w in res.warnings:
            print("  AVISO: %s" % w)

"""Calculo de empujes y de modulos de balasto.

Las presiones se evaluan nodo a nodo en kPa y se cargan como valores de
*joint pattern* en SAP, aplicando luego una presion superficial unitaria. Asi la
misma maquinaria cubre relleno estratificado, nivel freatico y coronas
inclinadas sin cambiar el esquema de cargas.
"""
from __future__ import annotations

from dataclasses import dataclass

from .params import EarthPressure, Seismic, SoilProfile, WallProject


@dataclass
class PressureResult:
    """Presiones laterales en un punto del paramento, en kPa."""

    soil: float          # empuje efectivo del relleno
    water: float         # presion hidrostatica
    surcharge: float     # empuje por sobrecarga en corona
    seismic: float       # incremento sismico

    @property
    def total(self) -> float:
        return self.soil + self.water + self.surcharge + self.seismic


class PressureProfile:
    """Evalua el estado tensional lateral sobre la pantalla."""

    def __init__(self, project: WallProject) -> None:
        self.p = project
        self.earth: EarthPressure = project.earth
        self.seis: Seismic = project.seismic
        self.soil: SoilProfile = project.soil
        self.K = self.earth.coefficient()
        self.dK = self.seis.delta_K(self.earth) if self.seis.enabled else 0.0
        self.wt = self.soil.water_table_z

    # -- tensiones verticales ---------------------------------------------
    def sigma_v_eff(self, z: float, z_crown: float) -> float:
        """Tension vertical efectiva en la cota z, medida desde la corona z_crown."""
        if z >= z_crown:
            return 0.0
        g = self.earth.gamma
        g_sat = getattr(self.earth, "gamma_sat", None) or (g + 2.0)
        gw = self.soil.gamma_w

        if self.wt is None or self.wt >= z_crown:
            if self.wt is None:
                return g * (z_crown - z)
            # Freatico en o por encima de la corona: todo el relleno sumergido
            return max(g_sat - gw, 0.0) * (z_crown - z)

        if z >= self.wt:
            return g * (z_crown - z)
        seco = g * (z_crown - self.wt)
        sumergido = max(g_sat - gw, 0.0) * (self.wt - z)
        return seco + sumergido

    def pore_pressure(self, z: float) -> float:
        if self.wt is None or z >= self.wt:
            return 0.0
        return self.soil.gamma_w * (self.wt - z)

    # -- presiones laterales ----------------------------------------------
    def at(self, z: float, z_crown: float, z_base: float) -> PressureResult:
        """Presiones laterales en la cota z de una columna cuyo paramento va de z_base a z_crown."""
        if z > z_crown + 1e-9 or z < z_base - 1e-9:
            return PressureResult(0.0, 0.0, 0.0, 0.0)

        soil = self.K * self.sigma_v_eff(z, z_crown)
        water = self.pore_pressure(z)
        surcharge = self.K * self.earth.surcharge
        seismic = self._seismic(z, z_crown, z_base)
        return PressureResult(soil, water, surcharge, seismic)

    def _seismic(self, z: float, z_crown: float, z_base: float) -> float:
        if not self.seis.enabled or self.dK <= 0.0:
            return 0.0
        H = z_crown - z_base
        if H <= 1e-9:
            return 0.0
        g = self.earth.gamma
        dist = self.seis.distribution

        if dist == "triangular_invertida":
            # Resultante a 2H/3 sobre la base: maxima en corona, nula en la base
            return self.dK * g * (z - z_base)
        if dist == "uniforme":
            return 0.5 * self.dK * g * H
        # 'triangular': crece con la profundidad, igual que el empuje estatico
        return self.dK * g * (z_crown - z)

    # -- resultantes -------------------------------------------------------
    def resultants(self, H: float) -> dict:
        """Resultantes por metro lineal de muro (kN/m) para una altura H."""
        g = self.earth.gamma
        Pa = 0.5 * self.K * g * H * H
        Pq = self.K * self.earth.surcharge * H
        dPae = 0.5 * self.dK * g * H * H
        Pw = 0.0
        if self.wt is not None:
            hw = max(0.0, min(H, self.wt - (0.0)))
            Pw = 0.5 * self.soil.gamma_w * hw * hw
        return {
            "K": self.K,
            "dK": self.dK,
            "Ka_gamma": self.K * g,
            "dKae_gamma": self.dK * g,
            "P_suelo": Pa,
            "y_suelo": H / 3.0,
            "P_sobrecarga": Pq,
            "y_sobrecarga": H / 2.0,
            "P_sismo": dPae,
            "y_sismo": 2.0 * H / 3.0 if self.seis.distribution == "triangular_invertida" else H / 3.0,
            "P_agua": Pw,
            "P_total": Pa + Pq + dPae + Pw,
        }


# --------------------------------------------------------------------------
# Balasto
# --------------------------------------------------------------------------
def lateral_spring(ks_h: float, diameter: float, trib_length: float) -> float:
    """Rigidez de resorte lateral nodal [kN/m] = ks_h [kN/m3] * D [m] * L_trib [m]."""
    return ks_h * diameter * trib_length


def tip_spring(ks_v: float, diameter: float) -> float:
    """Rigidez de punta [kN/m] = ks_v [kN/m3] * area de punta [m2]."""
    import math

    return ks_v * math.pi * diameter * diameter / 4.0

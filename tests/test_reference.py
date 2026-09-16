"""Verifica que el generador reproduce el modelo de referencia MuroContencion.s2k."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.builder import build
from app.core.params import (
    CapBeamGeometry,
    EarthPressure,
    MeshParams,
    PileGeometry,
    ProjectInfo,
    Seismic,
    WallGeometry,
    WallProject,
)
from app.exporters import s2k


def reference_project() -> WallProject:
    """Parametros equivalentes al modelo de ETABS/SAP entregado."""
    return WallProject(
        info=ProjectInfo(name="Muro referencia"),
        wall=WallGeometry(thickness=0.70, length=14.0, z_base=0.0, z_top=6.0, name="00_M_0.70"),
        # El modelo original lleva RESORTE de punta, no restriccion. Se conserva
        # asi para que esta prueba siga contrastando contra el .s2k de partida;
        # el valor por defecto de la herramienta es restringir U3 en la punta.
        piles=PileGeometry(diameter=1.20, spacing=2.80, z_top=0.0, z_bot=-10.0,
                           segment_length=1.0, tip_restraint=False),
        cap_beam=CapBeamGeometry(width=1.40, depth=0.60, name="01_V_1.4x0.60"),
        earth=EarthPressure(method="usuario", K_user=0.30, gamma=17.0, surcharge=0.0),
        seismic=Seismic(enabled=True, method="usuario", dK_user=0.16,
                        distribution="triangular_invertida"),
        mesh=MeshParams(wall_div_per_bay=3, wall_target_dz=1.0, pile_segment=1.0),
    )


def main() -> int:
    res = build(reference_project())
    m = res.model
    s = m.summary()
    fails: list[str] = []

    def check(label: str, got, want) -> None:
        ok = abs(got - want) < 1e-6 if isinstance(want, float) else got == want
        print("  %-38s %-10s (esperado %s) %s" % (label, got, want, "OK" if ok else "<<< FALLA"))
        if not ok:
            fails.append(label)

    print("Topologia del modelo generado:")
    check("nudos", s["joints"], 172)
    check("frames", s["frames"], 65)
    check("shells", s["areas"], 90)
    check("resortes", s["springs"], 60)

    # Presion estatica en la base: K*gamma*H = 0.30*17*6 = 30.6 kPa
    print("\nCargas:")
    base_vals = [
        v.value for v in m.pattern_values
        if v.pattern == "EMPUJE" and abs(m.get_joint(v.joint).z - 0.0) < 1e-9
    ]
    check("empuje en la base [kPa]", round(max(base_vals), 3), 30.6)
    crown_vals = [
        v.value for v in m.pattern_values
        if v.pattern == "EMPUJE_DIN" and abs(m.get_joint(v.joint).z - 6.0) < 1e-9
    ]
    check("sismo en corona [kPa]", round(max(crown_vals), 3), 16.32)

    # Balasto: ks_h * D * L_trib con el perfil por defecto de 3 estratos
    print("\nResortes (muestra):")
    for sp in m.springs[:3]:
        j = m.get_joint(sp.joint)
        print("  Z=%6.2f   U1=U2=%10.1f   U3=%10.1f" % (j.z, sp.u1, sp.u3))
    tip = [sp for sp in m.springs if abs(m.get_joint(sp.joint).z + 10.0) < 1e-9]
    check("n resortes de punta", len(tip), 6)
    check("U3 de punta [kN/m]", round(tip[0].u3, 1), round(100000 * 3.141592653589793 * 1.44 / 4.0 / 1000 * 1000, 1))

    print("\nGrupos:", ", ".join(g.name for g in m.groups))
    check("cortes de seccion", len(m.section_cuts), 2)
    # Un corte por grupo solo devuelve algo si el grupo incluye los nudos del
    # plano de corte: era justo lo que faltaba en el modelo original.
    for sc in m.section_cuts:
        check("  %s con nudos" % sc.name, len(m.group_element_ids(sc.group, "Joint")) > 0, True)
    check("nudos del corte del muro", len(m.group_element_ids("CORTE_MURO_BASE", "Joint")), 16)
    check("nudos del corte de pilas", len(m.group_element_ids("CORTE_PILAS_CABEZA", "Joint")), 6)
    check("grupos con miembros", all(
        any(m.group_element_ids(g.name, k) for k in ("Frame", "Area", "Joint"))
        for g in m.groups), True)
    check("nudos en APOYOS", len(m.group_element_ids("APOYOS", "Joint")), 60)

    # Exportacion
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out_referencia.s2k")
    s2k.write_file(m, out)
    size = os.path.getsize(out)
    print("\n.s2k escrito: %s (%d bytes)" % (out, size))
    with open(out, encoding="utf-8", newline="") as fh:
        text = fh.read()
    check("termina con END TABLE DATA", text.rstrip().endswith("END TABLE DATA"), True)
    check("usa CRLF", "\r\n" in text, True)
    check("sin lineas sobre 240 col", max(len(l) for l in text.split("\r\n")) <= 240, True)

    if res.warnings:
        print("\nAdvertencias:")
        for wmsg in res.warnings:
            print("  -", wmsg)

    print("\n%s" % ("TODO OK" if not fails else "FALLAS: " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

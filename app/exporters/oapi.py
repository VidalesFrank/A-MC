"""Driver de SAP2000 por OAPI (COM).

Estrategia: el modelo se materializa siempre a traves del .s2k generado y se
carga con SapModel.File.OpenFile(), que acepta extensiones .s2k/.$2k. Esto evita
duplicar en llamadas API la definicion de secciones, patrones de junta y
presiones superficiales -- y hace que el camino OAPI y el camino "importar a
mano" produzcan exactamente el mismo modelo.

A partir de ahi el driver si usa la API nativa para lo que el .s2k no puede
hacer: correr el analisis, leer resultados y lanzar el diseno.

Requiere Windows, SAP2000 instalado y el paquete `comtypes`.
"""
from __future__ import annotations

import os
import tempfile

from ..core import model as M
from . import s2k

UNITS_KN_M_C = 6

# ItemTypeElm: el que usan las funciones de RESULTADOS
ELM_OBJECT = 0
ELM_ELEMENT = 1
ELM_GROUP = 2
ELM_SELECTION = 3

# ItemType: el que usan las funciones de DISENO. Ojo, no es el mismo enum:
# aqui el grupo es 1 y el 2 significa "objetos seleccionados". Pasar el 2 de
# ItemTypeElm hace que SAP mire la seleccion —vacia— y devuelva codigo 1.
IT_OBJECT = 0
IT_GROUP = 1
IT_SELECTION = 2


class OAPIError(RuntimeError):
    pass


def _call(fn, in_args: tuple, n_out: int):
    """Invoca una funcion de resultados del OAPI.

    Con la type library generada, comtypes rellena los parametros de salida y
    solo hay que pasarle los de entrada. Sin ella (late binding) hay que aportar
    tantas listas vacias como salidas tenga la firma.
    """
    try:
        return fn(*in_args)
    except TypeError:
        return fn(*in_args, *([[] for _ in range(n_out)]))


def _unpack(ret, n_arrays: int):
    """Normaliza la salida de comtypes: (NumberResults, arr1..arrN, returnCode).

    comtypes devuelve unas veces tupla y otras lista segun la firma.
    """
    if not isinstance(ret, (tuple, list)):
        raise OAPIError("Respuesta inesperada de la API: %r" % (ret,))
    if len(ret) < n_arrays + 2:
        raise OAPIError(
            "La firma devolvio %d valores y se esperaban %d. "
            "Probablemente cambio entre versiones del OAPI." % (len(ret), n_arrays + 2)
        )
    code = ret[-1]
    if code != 0:
        raise OAPIError(
            "La API devolvio el codigo %s (sin resultados: revise que el analisis "
            "se haya corrido y que el caso o combinacion este seleccionado para salida)" % code
        )
    return ret[0], ret[1:1 + n_arrays]


def _code(ret) -> int:
    """Codigo de retorno de una llamada del OAPI, venga sola o dentro de tupla."""
    return ret[-1] if isinstance(ret, (tuple, list)) else ret


def _unpack_any(ret):
    """Como `_unpack`, pero deduce cuantos arrays vienen en vez de exigirlo.

    Las funciones de diseno y de resultados modales han ganado y perdido
    parametros entre versiones del OAPI; aqui solo interesan los primeros, asi
    que se acepta lo que llegue y el lector se queda con los que necesita.
    """
    if not isinstance(ret, (tuple, list)) or len(ret) < 3:
        raise OAPIError("Respuesta inesperada de la API: %r" % (ret,))
    code = ret[-1]
    if code != 0:
        raise OAPIError(
            "La API devolvio el codigo %s (sin resultados: revise que el analisis o el "
            "diseno se hayan corrido y que el caso este seleccionado para salida)" % code
        )
    return ret[0], ret[1:-1]


class SapDriver:
    """Sesion de trabajo contra SAP2000."""

    def __init__(self, attach: bool = True, visible: bool = True, exe_path: str | None = None) -> None:
        self.attach = attach
        self.visible = visible
        self.exe_path = exe_path
        self.sap = None
        self.model = None
        self._started = False

    # -- ciclo de vida -----------------------------------------------------
    def open(self) -> "SapDriver":
        try:
            import comtypes.client  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise OAPIError(
                "Falta el paquete 'comtypes'. Instalelo con: pip install comtypes"
            ) from exc
        import comtypes.client as cc

        helper = cc.CreateObject("SAP2000v1.Helper")
        try:
            import comtypes.gen.SAP2000v1 as sap_gen

            helper = helper.QueryInterface(sap_gen.cHelper)
        except Exception:
            # Sin type library generada seguimos con late binding
            pass

        if self.attach:
            try:
                self.sap = helper.GetObject("CSI.SAP2000.API.SapObject")
            except Exception:
                self.sap = None

        if self.sap is None:
            if self.exe_path:
                self.sap = helper.CreateObject(self.exe_path)
            else:
                self.sap = helper.CreateObjectProgID("CSI.SAP2000.API.SapObject")
            ret = self.sap.ApplicationStart()
            if ret != 0:
                raise OAPIError("No se pudo iniciar SAP2000 (codigo %s)" % ret)
            self._started = True

        self.model = self.sap.SapModel
        self.model.SetPresentUnits(UNITS_KN_M_C)
        return self

    def close(self, keep_open: bool = True) -> None:
        if self.sap is not None and self._started and not keep_open:
            try:
                self.sap.ApplicationExit(False)
            except Exception:
                pass
        self.sap = None
        self.model = None

    def __enter__(self) -> "SapDriver":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close(keep_open=True)

    # -- construccion ------------------------------------------------------
    def build_from_model(self, m: M.StructuralModel, sdb_path: str | None = None) -> str:
        """Carga en SAP el modelo neutro y lo guarda como .sdb."""
        tmp_dir = tempfile.mkdtemp(prefix="muro_sap_")
        s2k_path = os.path.join(tmp_dir, "modelo.s2k")
        s2k.write_file(m, s2k_path)

        ret = self.model.File.OpenFile(s2k_path)
        if ret != 0:
            raise OAPIError(
                "SAP2000 no pudo abrir el .s2k generado (codigo %s). Archivo: %s" % (ret, s2k_path)
            )
        self.model.SetPresentUnits(UNITS_KN_M_C)

        self.set_beam_sections(m)

        if sdb_path:
            os.makedirs(os.path.dirname(os.path.abspath(sdb_path)), exist_ok=True)
            ret = self.model.File.Save(sdb_path)
            if ret != 0:
                raise OAPIError("No se pudo guardar el .sdb (codigo %s)" % ret)
            return sdb_path
        return s2k_path

    # -- secciones de diseno ----------------------------------------------
    def set_beam_sections(self, m: M.StructuralModel) -> list[str]:
        """Marca como VIGA las secciones rectangulares de viga.

        SAP decide si una seccion de concreto se disena como viga o como columna
        por el tipo de ARMADURA que tiene definida, no por la orientacion del
        miembro. El `.s2k` escribe la tabla `FRAME SECTION PROPERTIES 05 -
        CONCRETE BEAM`, pero eso no cambia ese indicador: la viga cabezal
        acababa disenandose por interaccion P-M-M, que **no mira la torsion**,
        y por eso no habia con que contrastar el calculo propio.

        Con `SetRebarBeam` el indicador si cambia. Las areas van a cero a
        proposito, para que SAP **disene** el refuerzo en vez de comprobar uno
        impuesto: asi su resultado sirve de contraste independiente.
        """
        vigas = [x for x in m.rect_sections if x.is_beam]
        if not vigas:
            return []
        acero = m.rebar[0].name if m.rebar else ""
        hechas: list[str] = []
        for sec in vigas:
            ret = self.model.PropFrame.SetRebarBeam(
                sec.name, acero, acero, sec.cover, sec.cover, 0.0, 0.0, 0.0, 0.0)
            if _code(ret) != 0:
                raise OAPIError(
                    "No se pudo marcar %r como seccion de viga (codigo %s)"
                    % (sec.name, _code(ret)))
            hechas.append(sec.name)
        return hechas

    # -- analisis ----------------------------------------------------------
    def run_analysis(self, cases: list[str] | None = None) -> None:
        if cases is not None:
            self.model.Analyze.SetRunCaseFlag("", False, True)
            for c in cases:
                self.model.Analyze.SetRunCaseFlag(c, True, False)
        ret = self.model.Analyze.RunAnalysis()
        if ret != 0:
            raise OAPIError("El analisis fallo (codigo %s)" % ret)

    # -- seleccion de salida ----------------------------------------------
    def select_output(self, combos: list[str], envelopes: bool = True) -> None:
        setup = self.model.Results.Setup
        setup.DeselectAllCasesAndCombosForOutput()
        setup.SetOptionMultiValuedCombo(1 if envelopes else 2)
        for c in combos:
            if setup.SetComboSelectedForOutput(c) != 0:
                setup.SetCaseSelectedForOutput(c)

    # -- lectura de resultados --------------------------------------------
    def frame_forces(self, target: str, item_type: int = ELM_GROUP) -> list[dict]:
        """Fuerzas en frames. `target` puede ser un nombre de grupo o de elemento.

        Salidas: Obj, ObjSta, Elm, ElmSta, LoadCase, StepType, StepNum,
        P, V2, V3, T, M2, M3  (13 arrays).
        """
        ret = _call(self.model.Results.FrameForce, (target, item_type, 0), 14)
        n, a = _unpack(ret, 13)
        obj, sta, elm, elm_sta, case, step_t, step_n, P, V2, V3, T, M2, M3 = a
        return [
            {"obj": obj[i], "sta": sta[i], "case": case[i], "step": step_t[i],
             "P": P[i], "V2": V2[i], "V3": V3[i], "T": T[i], "M2": M2[i], "M3": M3[i]}
            for i in range(n)
        ]

    def area_forces(self, target: str, item_type: int = ELM_GROUP) -> list[dict]:
        """Fuerzas en shells.

        Salidas: Obj, Elm, PointElm, LoadCase, StepType, StepNum, F11, F22, F12,
        FMax, FMin, FAngle, FVM, M11, M22, M12, MMax, MMin, MAngle,
        V13, V23, VMax, VAngle  (23 arrays).
        """
        ret = _call(self.model.Results.AreaForceShell, (target, item_type, 0), 24)
        n, a = _unpack(ret, 23)
        (obj, elm, pt, case, step_t, step_n, F11, F22, F12, FMax, FMin, FAng, FVM,
         M11, M22, M12, MMax, MMin, MAng, V13, V23, VMax, VAng) = a
        return [
            {"obj": obj[i], "point": pt[i], "case": case[i],
             "F11": F11[i], "F22": F22[i], "F12": F12[i],
             "M11": M11[i], "M22": M22[i], "M12": M12[i],
             "V13": V13[i], "V23": V23[i], "VMax": VMax[i]}
            for i in range(n)
        ]

    def joint_reactions(self, target: str, item_type: int = ELM_GROUP) -> list[dict]:
        """Salidas: Obj, Elm, LoadCase, StepType, StepNum, F1, F2, F3, M1, M2, M3 (11)."""
        ret = _call(self.model.Results.JointReact, (target, item_type, 0), 12)
        n, a = _unpack(ret, 11)
        obj, elm, case, step_t, step_n, F1, F2, F3, Mx, My, Mz = a
        return [
            {"obj": obj[i], "case": case[i], "F1": F1[i], "F2": F2[i], "F3": F3[i],
             "M1": Mx[i], "M2": My[i], "M3": Mz[i]}
            for i in range(n)
        ]

    def section_cut_forces(self) -> list[dict]:
        """Salidas: SCut, LoadCase, StepType, StepNum, F1, F2, F3, M1, M2, M3 (10)."""
        ret = _call(self.model.Results.SectionCutAnalysis, (0,), 11)
        n, a = _unpack(ret, 10)
        cut, case, step_t, step_n, F1, F2, F3, M1, M2, M3 = a
        return [
            {"cut": cut[i], "case": case[i], "F1": F1[i], "F2": F2[i], "F3": F3[i],
             "M1": M1[i], "M2": M2[i], "M3": M3[i]}
            for i in range(n)
        ]

    # -- analisis modal ----------------------------------------------------
    def modal_periods(self) -> list[dict]:
        """Periodos y frecuencias de los modos.

        Salidas: LoadCase, StepType, StepNum, Period, Frequency, CircFreq,
        EigenValue (7 arrays).
        """
        ret = _call(self.model.Results.ModalPeriod, (), 8)
        n, a = _unpack_any(ret)
        case, step_t, step_n, period, freq, circ, eig = a[:7]
        return [
            {"case": case[i], "modo": int(step_n[i]), "T": period[i],
             "f": freq[i], "w": circ[i]}
            for i in range(n)
        ]

    def modal_mass_ratios(self) -> list[dict]:
        """Masa participante por modo.

        Salidas: LoadCase, StepType, StepNum, Period, Ux, Uy, Uz, SumUx, SumUy,
        SumUz, Rx, Ry, Rz, SumRx, SumRy, SumRz (16 arrays).
        """
        ret = _call(self.model.Results.ModalParticipatingMassRatios, (), 17)
        n, a = _unpack_any(ret)
        case, step_t, step_n, period, ux, uy, uz, sux, suy, suz = a[:10]
        return [
            {"case": case[i], "modo": int(step_n[i]), "T": period[i],
             "Ux": ux[i], "Uy": uy[i], "Uz": uz[i],
             "SumUx": sux[i], "SumUy": suy[i], "SumUz": suz[i]}
            for i in range(n)
        ]

    # -- diseno ------------------------------------------------------------
    CONCRETE_CODES = ("ACI 318-19", "ACI 318-14", "ACI 318-11", "ACI 318-08")

    def run_concrete_design(self, code: str | None = None) -> str:
        """Lanza el diseno de concreto de SAP y devuelve el codigo que acepto.

        El nombre del codigo cambia entre versiones de SAP, asi que se prueban
        en orden hasta que uno sea aceptado. Si `code` viene dado, se prueba
        primero ese.
        """
        candidates = ([code] if code else []) + [
            c for c in self.CONCRETE_CODES if c != code
        ]
        chosen = None
        for cand in candidates:
            try:
                if self.model.DesignConcrete.SetCode(cand) == 0:
                    chosen = cand
                    break
            except Exception:
                continue
        if chosen is None:
            raise OAPIError(
                "SAP no acepto ninguno de los codigos de diseno probados: %s"
                % ", ".join(candidates)
            )
        ret = self.model.DesignConcrete.StartDesign()
        if ret != 0:
            raise OAPIError(
                "El diseno de concreto fallo (codigo %s). Suele deberse a que no hay "
                "combinaciones de diseno seleccionadas o a que el analisis no se corrio." % ret
            )
        return chosen

    def design_results_beam(self, targets, item_type: int = IT_OBJECT) -> list[dict]:
        """Resumen de diseno de vigas, objeto a objeto.

        La consulta por GRUPO devuelve codigo 1 en SAP v27 (probado), asi que se
        itera sobre los nombres de frame, que son los mismos ids del modelo
        neutro porque el .s2k conserva las etiquetas.

        Salidas: FrameName, Location, TopCombo, TopArea, BotCombo, BotArea,
        VMajorCombo, VMajorArea, TLCombo, TLArea, TTCombo, TTArea,
        ErrorSummary, WarningSummary (14 arrays). TLArea es el longitudinal por
        torsion (mm2) y TTArea el transversal por torsion (mm2/mm), que es
        justo lo que calcula `design.torsion_design`.
        """
        filas = []
        for t in ([targets] if isinstance(targets, str) else list(targets)):
            ret = _call(self.model.DesignConcrete.GetSummaryResultsBeam,
                        (str(t), item_type), 16)
            n, a = _unpack_any(ret)
            name, loc, tc, ta, bc, ba, vc, va, tlc, tla, ttc, tta, err, warn = a[:14]
            filas += [
                {"frame": name[i], "x": loc[i],
                 "As_sup": ta[i], "combo_sup": tc[i],
                 "As_inf": ba[i], "combo_inf": bc[i],
                 "Av_s": va[i], "combo_V": vc[i],
                 "Al_torsion": tla[i], "combo_Al": tlc[i],
                 "At_s_torsion": tta[i], "combo_At": ttc[i],
                 "error": err[i], "aviso": warn[i]}
                for i in range(n)
            ]
        return filas

    def design_results_column(self, targets, item_type: int = IT_OBJECT) -> list[dict]:
        """Resumen de diseno de columnas.

        Salidas: FrameName, MyOption, Location, PMMCombo, PMMArea, PMMRatio,
        VMajorCombo, AVMajor, VMinorCombo, AVMinor, ErrorSummary,
        WarningSummary (12 arrays).
        """
        filas = []
        for t in ([targets] if isinstance(targets, str) else list(targets)):
            ret = _call(self.model.DesignConcrete.GetSummaryResultsColumn,
                        (str(t), item_type), 14)
            n, a = _unpack_any(ret)
            name, opt, loc, pmmc, pmma, pmmr, vmc, avm, vnc, avn, err, warn = a[:12]
            filas += [
                {"frame": name[i], "x": loc[i], "opcion": opt[i],
                 "As_PMM": pmma[i], "ratio_PMM": pmmr[i], "combo_PMM": pmmc[i],
                 "Av_s_mayor": avm[i], "combo_Vmayor": vmc[i],
                 "Av_s_menor": avn[i], "combo_Vmenor": vnc[i],
                 "error": err[i], "aviso": warn[i]}
                for i in range(n)
            ]
        return filas


def is_available() -> tuple[bool, str]:
    """Indica si el entorno puede hablar con SAP2000."""
    if os.name != "nt":
        return False, "El OAPI de SAP2000 solo funciona en Windows."
    try:
        import comtypes  # noqa: F401
    except ImportError:
        return False, "Falta el paquete 'comtypes' (pip install comtypes)."
    return True, "OAPI disponible."

"""Escritor de archivos .s2k (SAP2000 Text File).

Reproduce el formato tabular de SAP2000: CRLF, filas con sangria de 3 espacios,
campos separados por 3 espacios, continuacion de linea con ' _' y cierre con
'END TABLE DATA'. El archivo resultante se importa con
File > Import > SAP2000 .s2k Text File.
"""
from __future__ import annotations

import datetime as _dt
import math

from ..core import model as M

NL = "\r\n"
SEP = "   "
INDENT = "   "
CONT_INDENT = " " * 8
MAX_LINE = 240


# --------------------------------------------------------------------------
# Utilidades de formato
# --------------------------------------------------------------------------
def num(v: float | int) -> str:
    """Numero en el formato compacto que usa SAP."""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, int):
        return str(v)
    if v == 0:
        return "0"
    s = "%.10g" % v
    if "e" in s or "E" in s:
        s = "%.10f" % v
        s = s.rstrip("0").rstrip(".")
        if s in ("", "-"):
            s = "0"
    return s


def val(v) -> str:
    """Valor formateado y entrecomillado si contiene espacios o apostrofes."""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return num(v)
    s = str(v)
    if s == "":
        return '""'
    if any(ch in s for ch in " '\t"):
        return '"%s"' % s
    return s


def row(pairs: list[tuple[str, object]]) -> str:
    """Una fila de tabla, plegada con ' _' si excede el ancho maximo."""
    fields = ["%s=%s" % (k, val(v)) for k, v in pairs if v is not None]
    if not fields:
        return INDENT
    lines: list[str] = []
    current = INDENT + fields[0]
    for f in fields[1:]:
        candidate = current + SEP + f
        # Se reservan 2 columnas para el marcador de continuacion ' _'
        if len(candidate) + 2 > MAX_LINE:
            lines.append(current + " _")
            current = CONT_INDENT + f
        else:
            current = candidate
    lines.append(current)
    return NL.join(lines)


class S2KWriter:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def table(self, name: str, rows: list[list[tuple[str, object]]]) -> None:
        """Escribe una tabla; las tablas sin filas se emiten igual (SAP las admite vacias)."""
        self.parts.append(' ')
        self.parts.append('TABLE:  "%s"' % name)
        for r in rows:
            self.parts.append(row(r))

    def render(self, path_hint: str) -> str:
        head = "File %s was saved on %s" % (
            path_hint,
            _dt.datetime.now().strftime("%m/%d/%y at %H:%M:%S"),
        )
        body = NL.join([head] + self.parts + [" ", "END TABLE DATA", ""])
        return body


# --------------------------------------------------------------------------
# Propiedades de seccion
# --------------------------------------------------------------------------
def circle_props(d: float) -> dict:
    a = math.pi * d * d / 4.0
    i = math.pi * d ** 4 / 64.0
    return {
        "Area": a,
        "TorsConst": 2.0 * i,
        "I33": i,
        "I22": i,
        "I23": 0,
        "AS2": 0.9 * a,
        "AS3": 0.9 * a,
        "S33Top": i / (d / 2.0),
        "S33Bot": i / (d / 2.0),
        "S22Left": i / (d / 2.0),
        "S22Right": i / (d / 2.0),
        "Z33": d ** 3 / 6.0,
        "Z22": d ** 3 / 6.0,
        "R33": d / 4.0,
        "R22": d / 4.0,
    }


def rect_props(t3: float, t2: float) -> dict:
    """t3 = canto (direccion 3), t2 = ancho (direccion 2)."""
    a = t2 * t3
    i33 = t2 * t3 ** 3 / 12.0
    i22 = t3 * t2 ** 3 / 12.0
    long_side, short_side = max(t2, t3), min(t2, t3)
    r = short_side / long_side
    j = long_side * short_side ** 3 * (1.0 / 3.0 - 0.21 * r * (1.0 - r ** 4 / 12.0))
    return {
        "Area": a,
        "TorsConst": j,
        "I33": i33,
        "I22": i22,
        "I23": 0,
        "AS2": 5.0 / 6.0 * a,
        "AS3": 5.0 / 6.0 * a,
        "S33Top": i33 / (t3 / 2.0),
        "S33Bot": i33 / (t3 / 2.0),
        "S22Left": i22 / (t2 / 2.0),
        "S22Right": i22 / (t2 / 2.0),
        "Z33": t2 * t3 ** 2 / 4.0,
        "Z22": t3 * t2 ** 2 / 4.0,
        "R33": math.sqrt(i33 / a),
        "R22": math.sqrt(i22 / a),
    }


# --------------------------------------------------------------------------
# Exportador
# --------------------------------------------------------------------------
def export(m: M.StructuralModel, path_hint: str = "Modelo.s2k") -> str:
    w = S2KWriter()

    # ---- cabecera del programa ------------------------------------------
    w.table("PROGRAM CONTROL", [[
        ("ProgramName", "SAP2000"), ("Version", "27.1.0"), ("ProgLevel", "Advanced"),
        ("CurrUnits", "KN, m, C"), ("SteelCode", "AISC 360-10"), ("ConcCode", "ACI 318-11"),
        ("AlumCode", "AA 2015"), ("ColdCode", "AISI-ASD96"), ("RegenHinge", "Yes"),
    ]])

    w.table("ACTIVE DEGREES OF FREEDOM", [[
        ("UX", "Yes"), ("UY", "Yes"), ("UZ", "Yes"), ("RX", "Yes"), ("RY", "Yes"), ("RZ", "Yes"),
    ]])

    w.table("COORDINATE SYSTEMS", [[
        ("Name", "GLOBAL"), ("Type", "Cartesian"), ("X", 0), ("Y", 0), ("Z", 0),
        ("AboutZ", 0), ("AboutY", 0), ("AboutX", 0),
    ]])

    w.table("GRID LINES", [
        [("CoordSys", "GLOBAL"), ("AxisDir", g.axis), ("GridID", g.grid_id),
         ("XRYZCoord", g.coord), ("LineType", "Primary"), ("LineColor", "Gray8Dark"),
         ("Visible", "Yes"), ("BubbleLoc", "End")]
        for g in m.grid_lines
    ])

    # ---- materiales ------------------------------------------------------
    mat01 = []
    mat02 = []
    for c in m.concrete:
        mat01.append([("Material", c.name), ("Type", "Concrete"), ("SymType", "Isotropic"),
                      ("TempDepend", "No"), ("Color", "Red")])
        mat02.append([("Material", c.name), ("UnitWeight", c.gamma), ("UnitMass", c.mass),
                      ("E1", c.E), ("G12", c.G), ("U12", c.nu), ("A1", c.alpha)])
    for r in m.rebar:
        mat01.append([("Material", r.name), ("Type", "Rebar"), ("SymType", "Uniaxial"),
                      ("TempDepend", "No"), ("Color", "Magenta")])
        mat02.append([("Material", r.name), ("UnitWeight", r.gamma), ("UnitMass", r.mass),
                      ("E1", r.E), ("A1", r.alpha)])
    w.table("MATERIAL PROPERTIES 01 - GENERAL", mat01)
    w.table("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES", mat02)

    w.table("MATERIAL PROPERTIES 03B - CONCRETE DATA", [
        [("Material", c.name), ("Fc", c.fc), ("eFc", c.fc), ("LtWtConc", "No"),
         ("SSCurveOpt", "Mander"), ("SSHysType", "Takeda"), ("SFc", 0.00221914),
         ("SCap", 0.005), ("FinalSlope", -0.1), ("FAngle", 0), ("DAngle", 0)]
        for c in m.concrete
    ])
    w.table("MATERIAL PROPERTIES 03E - REBAR DATA", [
        [("Material", r.name), ("Fy", r.fy), ("Fu", r.fu), ("EffFy", r.fy), ("EffFu", r.fu),
         ("SSCurveOpt", "Simple"), ("SSHysType", "Kinematic"), ("SHard", 0.01),
         ("SCap", 0.09), ("FinalSlope", -0.1), ("UseCTDef", "No")]
        for r in m.rebar
    ])

    # ---- secciones de frame ---------------------------------------------
    fsec: list[list[tuple[str, object]]] = []
    for s in m.circle_sections:
        p = circle_props(s.diameter)
        fsec.append(
            [("SectionName", s.name), ("Material", s.material), ("Shape", "Circle"), ("t3", s.diameter)]
            + [(k, v) for k, v in p.items()]
            + [("ConcCol", "Yes"), ("ConcBeam", "No"), ("Color", "Red"), ("FromFile", "No"),
               ("AMod", 1), ("A2Mod", 1), ("A3Mod", 1), ("JMod", 1), ("I2Mod", 1), ("I3Mod", 1),
               ("MMod", 1), ("WMod", 1)]
        )
    for s in m.rect_sections:
        p = rect_props(s.depth, s.width)
        fsec.append(
            [("SectionName", s.name), ("Material", s.material), ("Shape", "Rectangular"),
             ("t3", s.depth), ("t2", s.width)]
            + [(k, v) for k, v in p.items()]
            + [("ConcCol", "No"), ("ConcBeam", "Yes"), ("Color", "Blue"), ("FromFile", "No"),
               ("AMod", 1), ("A2Mod", 1), ("A3Mod", 1), ("JMod", 1), ("I2Mod", 1), ("I3Mod", 1),
               ("MMod", 1), ("WMod", 1)]
        )
    w.table("FRAME SECTION PROPERTIES 01 - GENERAL", fsec)

    ccol: list[list[tuple[str, object]]] = []
    for s in m.circle_sections:
        ccol.append([("SectionName", s.name), ("RebarMatL", _rebar_name(m)), ("RebarMatC", _rebar_name(m)),
                     ("ReinfConfig", "Circular"), ("LatReinf", "Ties"), ("Cover", s.cover),
                     ("NumBarsCirc", s.num_bars), ("BarSizeL", s.bar_size), ("BarSizeC", s.tie_size),
                     ("SpacingC", s.tie_spacing), ("ReinfType", "Check")])
    for s in m.rect_sections:
        if s.is_beam:
            continue
        ccol.append([("SectionName", s.name), ("RebarMatL", _rebar_name(m)), ("RebarMatC", _rebar_name(m)),
                     ("ReinfConfig", "Rectangular"), ("LatReinf", "Ties"), ("Cover", s.cover),
                     ("NumBars3Dir", s.num_bars_3), ("NumBars2Dir", s.num_bars_2),
                     ("BarSizeL", s.bar_size), ("BarSizeC", s.tie_size), ("SpacingC", s.tie_spacing),
                     ("NumCBars2", s.num_bars_2), ("NumCBars3", s.num_bars_3), ("ReinfType", "Check")])
    w.table("FRAME SECTION PROPERTIES 02 - CONCRETE COLUMN", ccol)

    # Las secciones de viga van en su propia tabla. Si una seccion rectangular
    # aparece en la tabla de COLUMNA, SAP la disena como columna aunque en la
    # tabla 01 diga ConcBeam=Yes, y entonces no comprueba nunca la torsion.
    # Las areas se dejan en cero para que SAP DISENE el refuerzo en vez de
    # comprobar uno impuesto: asi su resultado sirve de contraste independiente.
    cbeam = [
        [("SectionName", s.name), ("RebarMatL", _rebar_name(m)), ("RebarMatC", _rebar_name(m)),
         ("CoverTop", s.cover), ("CoverBot", s.cover),
         ("TopLeftArea", 0), ("TopRghtArea", 0), ("BotLeftArea", 0), ("BotRghtArea", 0)]
        for s in m.rect_sections if s.is_beam
    ]
    if cbeam:
        w.table("FRAME SECTION PROPERTIES 05 - CONCRETE BEAM", cbeam)

    # ---- secciones de area ----------------------------------------------
    w.table("AREA SECTION PROPERTIES", [
        [("Section", s.name), ("Material", s.material), ("MatAngle", 0), ("AreaType", "Shell"),
         ("Type", s.shell_type), ("DrillDOF", "Yes"), ("Thickness", s.thickness),
         ("BendThick", s.thickness), ("Color", "Green"),
         ("F11Mod", 1), ("F22Mod", 1), ("F12Mod", 1), ("M11Mod", 1), ("M22Mod", 1), ("M12Mod", 1),
         ("V13Mod", 1), ("V23Mod", 1), ("MMod", 1), ("WMod", 1)]
        for s in m.shell_sections
    ])
    w.table("AREA SECTION PROPERTY DESIGN PARAMETERS", [
        [("Section", s.name), ("RebarMat", s.rebar_material or _rebar_name(m)), ("RebarOpt", "Default")]
        for s in m.shell_sections
    ])

    # ---- cargas ----------------------------------------------------------
    w.table("LOAD PATTERN DEFINITIONS", [
        [("LoadPat", p.name), ("DesignType", p.design_type), ("SelfWtMult", p.self_weight)]
        for p in m.load_patterns
    ])

    combo_rows: list[list[tuple[str, object]]] = []
    for c in m.combos:
        for idx, (pat, sf) in enumerate(c.factors):
            if idx == 0:
                combo_rows.append([
                    ("ComboName", c.name), ("ComboType", "Linear Add"), ("AutoDesign", "No"),
                    ("CaseType", "Linear Static"), ("CaseName", pat), ("ScaleFactor", sf),
                    ("SteelDesign", "None"), ("ConcDesign", c.design),
                    ("AlumDesign", "None"), ("ColdDesign", "None"),
                ])
            else:
                combo_rows.append([
                    ("ComboName", c.name), ("CaseType", "Linear Static"),
                    ("CaseName", pat), ("ScaleFactor", sf),
                ])
    w.table("COMBINATION DEFINITIONS", combo_rows)

    # ---- grupos y cortes -------------------------------------------------
    w.table("GROUPS 1 - DEFINITIONS", [
        [("GroupName", g.name), ("Selection", "Yes"), ("SectionCut", "Yes"), ("Steel", "Yes"),
         ("Concrete", "Yes"), ("Aluminum", "Yes"), ("ColdFormed", "Yes"), ("Stage", "Yes"),
         ("Bridge", "Yes"), ("AutoSeismic", "No"), ("AutoWind", "No"), ("SelDesSteel", "No"),
         ("SelDesAlum", "No"), ("SelDesCold", "No"), ("MassWeight", "Yes"), ("Color", "Green")]
        for g in m.groups
    ])
    w.table("GROUPS 2 - ASSIGNMENTS", [
        [("GroupName", g), ("ObjectType", kind), ("ObjectLabel", str(eid))]
        for g, kind, eid in m.group_members
    ])
    w.table("SECTION CUTS 1 - GENERAL", [
        [("CutName", sc.name), ("DefinedBy", "Group"), ("Group", sc.group),
         ("ResultType", "Analysis"), ("DefaultLoc", "Yes"),
         ("GlobalX", 0), ("GlobalY", 0), ("GlobalZ", 0),
         ("AngleA", 0), ("AngleB", 0), ("AngleC", 0), ("AdvanceAxes", "No")]
        for sc in m.section_cuts
    ])

    w.table("JOINT PATTERN DEFINITIONS", [[("Pattern", p)] for p in m.joint_patterns])
    w.table("MASS SOURCE", [[("MassSource", "MSSSRC1"), ("Elements", "Yes"), ("Masses", "Yes"),
                             ("Loads", "No"), ("IsDefault", "Yes")]])

    case_rows = [
        [("Case", c.name), ("Type", c.case_type), ("InitialCond", "Zero"),
         ("DesTypeOpt", "Prog Det"), ("DesignType", c.design_type), ("DesActOpt", "Prog Det"),
         ("DesignAct", "Other"), ("AutoType", "None"), ("RunCase", "Yes"), ("CaseStatus", "Not Run")]
        for c in m.load_cases
    ]
    case_rows += [
        [("Case", mc.name), ("Type", "LinModal"), ("InitialCond", "Zero"),
         ("DesTypeOpt", "Prog Det"), ("DesignType", "Other"), ("DesActOpt", "Prog Det"),
         ("DesignAct", "Other"), ("AutoType", "None"), ("RunCase", "Yes"), ("CaseStatus", "Not Run")]
        for mc in m.modal_cases
    ]
    w.table("LOAD CASE DEFINITIONS", case_rows)
    w.table("CASE - STATIC 1 - LOAD ASSIGNMENTS",
            [[("Case", c.name), ("LoadType", "Load pattern"), ("LoadName", pat), ("LoadSF", sf)]
             for c in m.load_cases for pat, sf in c.loads]
            + [[("Case", c.name), ("LoadType", "Acceleration"), ("LoadName", eje), ("LoadSF", sf)]
               for c in m.load_cases for eje, sf in c.accels])

    # Los casos no lineales y modales solo emiten tabla si existen: sin ellos el
    # archivo sale identico al del camino lineal ya validado.
    nl_cases = [c for c in m.load_cases if c.case_type != "LinStatic"]
    if nl_cases:
        w.table("CASE - STATIC 2 - NONLINEAR LOAD APPLICATION", [
            [("Case", c.name), ("LoadApp", "Full Load"), ("MonitorDOF", "U1"),
             ("MonitorJt", 1)]
            for c in nl_cases
        ])
        w.table("CASE - STATIC 4 - NONLINEAR PARAMETERS", [
            [("Case", c.name), ("GeoNonLin", c.geo_nonlin), ("ResultsSave", "Final State Only"),
             ("MaxTotal", 200), ("MaxNull", 50), ("MaxConstIter", 10), ("MaxNRIter", 40),
             ("IterCOnvTol", 1e-4), ("EventLump", "Yes"), ("LineSearch", "No")]
            for c in nl_cases
        ])
    if m.modal_cases:
        w.table("CASE - MODAL 1 - GENERAL", [
            [("Case", mc.name), ("ModeType", mc.mode_type), ("MaxNumModes", mc.max_modes),
             ("MinNumModes", mc.min_modes), ("EigenShift", 0), ("EigenCutoff", 0),
             ("EigenTol", 1e-9), ("AutoShift", "Yes")]
            for mc in m.modal_cases
        ])

    # ---- geometria -------------------------------------------------------
    w.table("JOINT COORDINATES", [
        [("Joint", j.id), ("CoordSys", "GLOBAL"), ("CoordType", "Cartesian"),
         ("XorR", j.x), ("Y", j.y), ("Z", j.z), ("SpecialJt", "No")]
        for j in m.joints
    ])
    w.table("CONNECTIVITY - FRAME", [
        [("Frame", f.id), ("JointI", f.i), ("JointJ", f.j), ("IsCurved", "No")]
        for f in m.frames
    ])
    w.table("CONNECTIVITY - AREA", [
        ([("Area", a.id), ("NumJoints", len(a.joints))]
         + [("Joint%d" % (k + 1), jid) for k, jid in enumerate(a.joints)])
        for a in m.areas
    ])

    # ---- asignaciones ----------------------------------------------------
    w.table("JOINT SPRING ASSIGNMENTS 1 - UNCOUPLED", [
        [("Joint", s.joint), ("CoordSys", "Local"), ("U1", s.u1), ("U2", s.u2), ("U3", s.u3),
         ("R1", s.r1), ("R2", s.r2), ("R3", s.r3)]
        for s in m.springs
    ])
    if m.restraints:
        w.table("JOINT RESTRAINT ASSIGNMENTS", [
            [("Joint", r.joint), ("U1", r.u1), ("U2", r.u2), ("U3", r.u3),
             ("R1", r.r1), ("R2", r.r2), ("R3", r.r3)]
            for r in m.restraints
        ])
    w.table("JOINT PATTERN ASSIGNMENTS", [
        [("Joint", v.joint), ("Pattern", v.pattern), ("Value", v.value)]
        for v in m.pattern_values
    ])

    circ = {s.name for s in m.circle_sections}
    w.table("FRAME SECTION ASSIGNMENTS", [
        [("Frame", f.id),
         ("SectionType", "Circle" if f.section in circ else "Rectangular"),
         ("AutoSelect", "N.A."), ("AnalSect", f.section), ("DesignSect", f.section),
         ("MatProp", "Default")]
        for f in m.frames
    ])
    w.table("FRAME AUTO MESH ASSIGNMENTS", [
        [("Frame", f.id), ("AutoMesh", "Yes" if f.auto_mesh_at_joints else "No"),
         ("AtJoints", "Yes" if f.auto_mesh_at_joints else "No"), ("AtFrames", "No"),
         ("NumSegments", 0), ("MaxLength", 0), ("MaxDegrees", 0)]
        for f in m.frames
    ])
    w.table("AREA SECTION ASSIGNMENTS", [
        [("Area", a.id), ("Section", a.section), ("MatProp", "Default")]
        for a in m.areas
    ])
    w.table("AREA LOADS - SURFACE PRESSURE", [
        ([("Area", sp.area), ("LoadPat", sp.load_pattern), ("Face", sp.face), ("Pressure", sp.pressure)]
         + ([("JtPattern", sp.joint_pattern)] if sp.joint_pattern else []))
        for sp in m.surface_pressures
    ])

    # ---- preferencias y cierre -------------------------------------------
    w.table("PREFERENCES - DIMENSIONAL", [[("MergeTol", 0.001), ("FineGrid", 0.25), ("Nudge", 0.25),
                                           ("SelectTol", 3), ("SnapTol", 12), ("SLineThick", 1),
                                           ("PLineThick", 4), ("MaxFont", 8), ("MinFont", 3),
                                           ("AutoZoom", 10), ("ShrinkFact", 70), ("TextFileLen", 240)]])
    w.table("PREFERENCES - CONCRETE DESIGN - ACI 318-11", [[("THDesign", "Envelopes"), ("NumCurves", 24),
                                                            ("NumPoints", 11), ("MinEccen", "Yes"),
                                                            ("PatLLF", 0.75), ("UFLimit", 0.95),
                                                            ("SeisCat", "D"), ("PhiT", 0.9),
                                                            ("PhiCTied", 0.65), ("PhiCSpiral", 0.75),
                                                            ("PhiV", 0.75), ("PhiVSeismic", 0.6),
                                                            ("PhiVJoint", 0.85)]])
    w.table("DATABASE FORMAT TYPES", [[("UnitsCurr", "Yes"), ("OverrideE", "No")]])
    w.table("PROJECT INFORMATION", [
        [("Item", "Project Name"), ("Data", m.name)],
        [("Item", "Model Name"), ("Data", m.name)],
    ])

    return w.render(path_hint)


def _rebar_name(m: M.StructuralModel) -> str:
    return m.rebar[0].name if m.rebar else "420 MPa"


def write_file(m: M.StructuralModel, path: str) -> str:
    text = export(m, path)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return path

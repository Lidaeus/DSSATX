"""Apply unique, read-only trace insertions to the frozen official source.

Run once from this worktree. Each anchor must match exactly once. Do not run
against another version or re-run on instrumented files. No V15 source is read.
"""
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[2]


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Anchor count {text.count(old)}: {old[:90]!r}")
    return text.replace(old, new)


def vector(event, variables, control="CONTROL"):
    names = ",".join(variables)
    chunks = textwrap.wrap(names, 52, break_long_words=True, break_on_hyphens=False)
    # Wrapping must not insert or drop whitespace in variable names.
    assert "".join(chunks) == names
    lines = [f"        CALL P0_V({control},'{event}',"]
    for i, chunk in enumerate(chunks):
        lines.append("     &    '" + chunk + ("'//" if i < len(chunks)-1 else "',"))
    expression = ",".join(variables)
    chunks = textwrap.wrap(expression, 50, break_long_words=True, break_on_hyphens=False)
    # Split expressions on commas; identifiers themselves must stay intact.
    parts, current = [], ""
    for item in variables:
        addition = ("," if current else "") + item
        if len(current + addition) > 50:
            parts.append(current + ",")
            current = item
        else:
            current += addition
    parts.append(current)
    for i, chunk in enumerate(parts):
        lines.append("     &    " + ("(/" if i == 0 else "  ") + chunk +
                     ("/))" if i == len(parts)-1 else ""))
    return "\n".join(lines) + "\n"


def block(event, variables=(), layers=(), text=()):
    result = "!     P0b read-only trace; no model state is assigned.\n"
    result += "      IF (P0_ENABLED()) THEN\n"
    if variables:
        result += vector(event, variables)
    for key in layers:
        result += f"        CALL P0_L(CONTROL,'{event}','{key}',\n     &    {key},NLAYR)\n"
    for key in text:
        result += f"        CALL P0_TEXT(CONTROL,'{event}','{key}',{key})\n"
    result += "      ENDIF\n"
    return result


def mutate(path, operation):
    p = ROOT / path
    old = p.read_text(encoding="utf-8")
    new = operation(old)
    p.write_text(new, encoding="utf-8", newline="\n")


def common_use(s):
    anchor = "      USE ModuleData\n"
    return replace(s, anchor, anchor + "      USE CG_P0Trace\n")


STATE = ["WTNLF", "WTNST", "WTNRT", "WTNSH", "WTNSD", "WTNNOD",
         "WTNLO", "WTNSO", "WTNRO", "WTNSHO", "WTNSDO", "WTNNO",
         "SDNPL", "SEEDNI", "WTNUP", "WTNFX", "TNLEAK",
         "WTLF", "STMWT", "RTWT", "WCRLF", "WCRST", "WCRRT",
         "RNITP", "PCNL", "PCNST", "XLAI"]


def crop(s):
    s = common_use(s)
    anchor = "      ELSE IF (DYNAMIC .EQ. RATE) THEN\n"
    s = replace(s, anchor, anchor + block("cg_rate", layers=["SW", "NO3", "NH4", "RLV"],
                                         text=["MEPHO", "ISWWAT", "ISWNIT"]))
    anchor = "!     Initialize available N and C for beginning of daily calcs.\n"
    s = replace(s, anchor, block("cg_begin", STATE + ["RPROAV", "PG", "CMOBMX", "DTX", "DXR57"]) + anchor)
    anchor = "      IF (YRDOY == YREND) RETURN\n"
    s = replace(s, anchor, block("cg_demand", ["PGAVL", "MAINR", "CMINEP", "NDMNEW", "NDMOLD",
                  "NDMTOT", "NDMSDR", "NMINEP", "NMOBR", "FNINL", "FNINS", "FNINR",
                  "RPROAV", "AGRVG2", "AGRSD2", "AGRSH2"]) + anchor)
    anchor = "      IF (ISWNIT .EQ. 'Y') THEN\n        CALL NUPTAK(INTEGR,"
    s = replace(s, anchor, block("cg_seed", ["NAVL", "SDNPL", "PGAVL"]) + anchor)
    anchor = "        RSPNO3 = TRNO3U/0.16 * RNO3C\n"
    s = replace(s, anchor, block("cg_uptake", ["TRNU", "TRNO3U", "TRNH4U", "PGAVL", "RNO3C", "RNH4C"],
                                ["UNO3", "UNH4", "SW", "NO3", "NH4", "RLV"]) + anchor)
    anchor = "        NAVL = NAVL + TRNU\n"
    s = replace(s, anchor, anchor + block("cg_N_cost", ["RSPNO3", "RSPNH4", "PGAVL", "NAVL"]))
    anchor = "      NAVL   = NAVL + NMINEA\n"
    s = replace(s, anchor, anchor + block("cg_mobil", ["NMINEA", "NRUSLF", "NRUSST", "NRUSRT", "NRUSSH",
                                                      "RPRO", "PGAVL", "NAVL"]))
    anchor = "      NAVL = NAVL + NFIXN\n"
    s = replace(s, anchor, anchor + block("cg_fix", ["NFIXN", "CNOD", "PGAVL", "NAVL"]))
    anchor = "      NAVL   = MAX(0.0,NAVL)\n"
    s = replace(s, anchor, anchor + block("cg_repro", ["CGRSD", "CGRSH", "NGRSD", "NGRSH", "PGAVL", "NAVL",
                                      "HPODWT", "HSDWT", "HSHELWT"]))
    anchor = "      PGAVL = PGAVL - CSAVEV\n"
    s = replace(s, anchor, anchor + block("cg_before_veg", ["CSAVEV", "PGAVL", "NAVL", "TNLEAK"]))
    anchor = "      PGAVL = PGAVL - AGRVG * (WLDOTN + WSDOTN + WRDOTN)\n"
    s = replace(s, anchor, block("cg_veg", ["AGRVG", "WLDOTN", "WSDOTN", "WRDOTN", "NGRLF", "NGRST", "NGRRT",
                          "NADLF", "NADST", "NADRT", "CADLF", "CADST", "PCH2O", "CMINEA", "TNLEAK",
                          "NSTRES", "EXCESS", "FRLF", "FRSTM", "FRRT"]) + anchor)
    anchor = "      PGAVL = PGAVL - (CADST + CADLF) * PCH2O\n"
    s = replace(s, anchor, anchor + block("cg_ledger_end", ["PGAVL", "NAVL"]))
    anchor = "      AGRVG2 = AGRVG + (FRLF*PROLFI+FRRT*PRORTI+FRSTM*PROSTI)*RPROAV\n"
    s = replace(s, anchor, anchor + block("cg_source_next", ["RPROAV", "RPRO", "RFIXN", "TRNU", "NMINEA",
                           "NFIXN", "RSPNO3", "RSPNH4", "AGRVG2", "AGRSD2", "AGRSH2"]))
    anchor = "      IF ((WTLF+STMWT).GT. 0.0001) THEN\n"
    s = replace(s, anchor, block("cg_end", STATE) + anchor)
    # Common exit reached after initialization, output, integration, and SEASEND.
    anchor = "!     Store plant module data for use in ETPHOT.\n"
    s = replace(s, anchor,
        "      IF (DYNAMIC .EQ. SEASINIT) THEN\n" +
        block("cg_reset", ["WTNUP", "TNLEAK"], ["UNO3", "UNH4"], ["MEPHO"]) +
        "      ELSEIF (DYNAMIC .EQ. SEASEND) THEN\n" +
        block("cg_season_end", STATE, ["UNO3", "UNH4"]) + "      ENDIF\n" + anchor)
    return s


def soil(s):
    s = common_use(s)
    anchor = "      DO L = 1, NLAYR\n!       Update with yesterday's plant N uptake\n"
    s = replace(s, anchor, block("soil_debit_before", ["WTNUP"], ["SNO3", "SNH4", "UREA", "UNO3", "UNH4"]) + anchor)
    anchor = "!     Check for fertilizer added today or active slow release fertilizers \n"
    s = replace(s, anchor, block("soil_debit_after", ["WTNUP"], ["SNO3", "SNH4", "UREA"]) + anchor)
    anchor = "!     Loop through soil layers for integration\n"
    s = replace(s, anchor, block("soil_integr_before", layers=["SNO3", "SNH4", "UREA", "DLTSNO3", "DLTSNH4", "DLTUREA"]) + anchor)
    anchor = "      NO3_plant = NO3\n      NH4_plant = NH4\n"
    # Anchor also appears in initialization; use the one immediately preceding OUTPUT.
    tail = "\n!***********************************************************************\n!***********************************************************************\n!     OUTPUT\n"
    s = replace(s, anchor + tail, anchor + block("soil_integr_end", ["WTNUP"], ["SNO3", "SNH4", "UREA", "NO3_plant", "NH4_plant"]) + tail)
    anchor = "      ELSEIF (DYNAMIC .EQ. OUTPUT .OR. DYNAMIC .EQ. SEASEND) THEN\n"
    s = replace(s, anchor, anchor +
        "      IF (DYNAMIC .EQ. SEASEND) THEN\n" +
        block("soil_season_end", ["WTNUP", "CNUPTAKE"], ["SNO3", "SNH4", "UREA", "UNO3", "UNH4"]) + "      ENDIF\n")
    return s


def spam(s):
    s = common_use(s)
    anchor = "      DYNAMIC = CONTROL % DYNAMIC\n"
    s = replace(s, anchor, anchor + "      CALL P0_CONTEXT(CONTROL)\n")
    anchor = "      CALL PUT('SPAM', 'UH2O',RWU)\n"
    s = replace(s, anchor, anchor + block("spam_rate", ["EP", "EOP", "TRWU", "TRWUP"],
                ["RWU", "SW", "SWDELTX", "RLV", "DLAYR"], ["MEPHO", "MEEVP", "ISWWAT"]))
    return s


def cache(s):
    anchor = "      REAL NH4(NL), NO3(NL), UNH4(NL), UNO3(NL)\n"
    s = replace(s, anchor, anchor + "      REAL P0_RWU(NL), P0_EP\n")
    anchor = "      ELSE IF (DYNAMIC .EQ. RATE) THEN\n"
    return replace(s, anchor, anchor +
        "!     P0b private reads verify the actual shared-cache interface.\n" +
        "      IF (P0_ENABLED()) THEN\n" +
        "        CALL GET('SPAM','UH2O',P0_RWU)\n" +
        "        CALL GET('SPAM','EP',P0_EP)\n" +
        "        CALL P0_V(CONTROL,'cg_cache','EP',(/P0_EP/))\n" +
        "        CALL P0_L(CONTROL,'cg_cache','RWU',P0_RWU,NLAYR)\n" +
        "      ENDIF\n")


def water_snapshot(s):
    anchor = "        CALL P0_L(CONTROL,'spam_rate','SWDELTX',\n"
    extra = ""
    for key in ["LL", "SW_AVAIL", "SWDELTS", "SWDELTU"]:
        extra += f"        CALL P0_L(CONTROL,'spam_rate','{key}',\n     &    {key},NLAYR)\n"
    return replace(s, anchor, extra + anchor)


def century(s):
    s = replace(s, "      USE ModuleDefs\n", "      USE ModuleDefs\n      USE CG_P0Trace\n")
    anchor = "      CALL SENESADD_C (RATE,\n"
    extra = block("century_residue_before", ["SENESSUMN"])
    extra += "      IF (P0_ENABLED()) THEN\n"
    extra += "        CALL P0_V(CONTROL,'century_residue_input',\n"
    extra += "     &    'surface_N,root_N,residue_DM',\n"
    extra += "     &    (/SENESCE%ResE(0,N),\n"
    extra += "     &      SUM(SENESCE%ResE(1:NLAYR,N)),\n"
    extra += "     &      SUM(SENESCE%ResWt(0:NLAYR))/))\n"
    extra += "      ENDIF\n"
    s = replace(s, anchor, extra + anchor)
    anchor = "     &  SENESSUMC, SENESSUMN, SENESSUMP)                  !Output\n"
    # This output signature also occurs at SEASINIT; scope to the RATE call.
    start = s.index("      CALL SENESADD_C (RATE,")
    head, tail = s[:start], s[start:]
    tail = replace(tail, anchor, anchor + block("century_residue_after", ["SENESSUMN"]))
    return head + tail


def etphot(s):
    s = common_use(s)
    anchor = "      CALL PUT('SPAM', 'PG'    , PG)\n"
    s = replace(s, anchor, anchor + "      IF (DYNAMIC .EQ. RATE .AND. MEPHO .EQ. 'L') THEN\n" +
        block("etphot_rate", ["RNITP", "PG", "AGEFAC", "EP", "EOP", "XLAI", "EXCESS",
               "PCNLSL", "PCNLSH", "SLWSLN", "SLWSHN", "PNLSLN", "PNLSHN",
               "LMXSLN", "LMXSHN"]) + "      ENDIF\n")
    return s


def etphr(s):
    start = s.index("      SUBROUTINE PGLFEQ(")
    head, section = s[:start], s[start:]
    section = replace(section, "      USE MODULEDATA\n", "      USE MODULEDATA\n      USE CG_P0Trace, ONLY: P0_LEAF\n")
    anchor = "      LFMAX = LXREF * SLWMAX * TEMPMX * AGEMXL * CO2MAX * CHILL * BETAMX\n"
    section = replace(section, anchor, anchor +
        "!     P0b observes actual leaf N responses; no feedback is added.\n" +
        "      CALL P0_LEAF(RNITP,SLW,SLWREF,LNREF,AGEMXL,AGEQE,\n     &    LFMAX,QEFF)\n")
    return head + section


def grow(s):
    s = common_use(s) if "      USE ModuleData\n" in s else replace(s,
        "      USE ModuleDefs", "      USE CG_P0Trace\n      USE ModuleDefs")
    anchor = "      SenE(0,1) = AMAX1 (SenE(0,1),0.) * 10.0             !kg[N]/ha\n"
    s = replace(s, anchor, anchor + block("grow_losses", ["NLOFF", "NSOFF", "NROFF", "NSHOFF", "NSDOFF",
         "NLDOT", "NSDOT", "NRDOT", "NSHDOT", "NSDDOT", "NADLF", "NADST", "NADRT",
         "HPODWT", "HSDWT", "HSHELWT", "PCNSD", "PCNSH", "NHSHWT", "NHSDWT", "NLPEST"]))
    anchor = "C     Leaf Area, Specific Leaf Area Calculations\n"
    s = replace(s, anchor, "      IF (P0_ENABLED()) THEN\n" +
        "        CALL P0_V(CONTROL,'grow_residue','surface_N',\n     &    (/SenE(0,1)/))\n" +
        "        CALL P0_L(CONTROL,'grow_residue','root_N',\n     &    SenE(1:NL,1),NLAYR)\n" + "      ENDIF\n" + anchor)
    return s


def detailed_grow(s):
    anchor = "      NLOFF  = (SLNDOT + WLIDOT + WLFDOT) * (PCNL/100.) +\n"
    s = replace(s, anchor, block('grow_N_before', ['PCNSD','PCNSH','NHSHWT','NHSDWT',
                     'WTNLF','WTNST','WTNRT','WTNSH','WTNSD']) + anchor)
    anchor = "      IF ((NLDOT < 0.0) .AND. (ABS(NLDOT) > WTNLF)) THEN\n"
    s = replace(s, anchor, block('grow_N_rates_raw', ['NLDOT','NSDOT','NRDOT','NSHDOT','NSDDOT']) + anchor)
    return s


def veggr(s):
    s=replace(s, '      USE ModuleDefs', '      USE CG_P0Trace\n      USE ModuleDefs')
    anchor = "      NRATIO = 1.0\n"
    s = replace(s, anchor,
        "      IF (P0_ENABLED()) THEN\n" +
        "        CALL P0_LOCAL('veg_potential',\n" +
        "     &    'AGRVG,NGRVEG,NGRVGG,NAVL,VGRDEM,PGAVL',\n" +
        "     &    (/AGRVG,NGRVEG,NGRVGG,NAVL,VGRDEM,PGAVL/))\n" +
        "      ENDIF\n" + anchor)
    anchor = "      IF (PGLEFT < 1.E-5) PGLEFT = 0.0\n"
    s = replace(s, anchor, anchor +
        "      IF (P0_ENABLED()) THEN\n" +
        "        CALL P0_LOCAL('veg_after_N',\n" +
        "     &    'AGRVG,NRATIO,PGAVL,PGLEFT',\n" +
        "     &    (/AGRVG,NRATIO,PGAVL,PGLEFT/))\n" +
        "      ENDIF\n")
    return s


def main():
    mutations = {
        "Plant/CROPGRO/CROPGRO.for": lambda s: cache(crop(s)),
        "Soil/Inorganic_N/SoilNi.for": soil,
        "SPAM/SPAM.for": lambda s: water_snapshot(spam(s)),
        "SPAM/ETPHOT.for": etphot,
        "SPAM/ETPHR.for": etphr,
        "Plant/CROPGRO/GROW.for": lambda s: detailed_grow(grow(s)),
        "Plant/CROPGRO/VEGGR.for": veggr,
        "Soil/CENTURY_OrganicMatter/CENTURY.for": century,
        "CMakeLists.txt": lambda s: replace(s, '        "Utilities/ModuleDefs.for"\n',
            '        "Utilities/ModuleDefs.for"\n        "Utilities/CG_P0Trace.f90"\n'),
    }
    # Prepare every edit first. Any bad anchor leaves every source unchanged.
    prepared = {}
    for name, operation in mutations.items():
        old = (ROOT / name).read_text(encoding="latin-1")
        prepared[name] = operation(old)
    for name, new in prepared.items():
        (ROOT / name).write_text(new, encoding="latin-1", newline="\n")
    print("Instrumented", len(prepared), "files (diagnostics only).")


if __name__ == "__main__":
    main()

"""Historical initial P1/P2 patch generator (14905c94), not a current rebuild tool.

Use the current Git tree for the complete integration. Do not replay this older
API against later module versions. No V15 sources are read.
"""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def once(s,a,b):
    if s.count(a)!=1:raise ValueError((s.count(a),a[:100]))
    return s.replace(a,b)
def edit(name,fn):
    p=ROOT/name;s=p.read_text(encoding='latin-1');p.write_text(fn(s),encoding='latin-1',newline='\n')
def crop(s):
    s=once(s,'      USE CG_P0Trace\n','      USE CG_P0Trace\n      USE CG_Nitrogen\n')
    s=once(s,'      REAL P0_RWU(NL), P0_EP\n','      REAL P0_RWU(NL), P0_EP\n'
        '      REAL NASSIMD, NFORGROW, NIUNUSED, NIREFUND, NILEAK0\n'
        '      REAL NISHARE\n')
    a='      IF (DYNAMIC .EQ. RUNINIT) THEN\n'
    s=once(s,a,a+'      CALL NI_LOAD(CONTROL,ISWITCH)\n')
    a='      ELSEIF (DYNAMIC .EQ. SEASINIT) THEN\n'
    s=once(s,a,a+'      CALL NI_RESET()\n')
    a='!     Initialize available N and C for beginning of daily calcs.\n'
    s=once(s,a,'      IF (NI_ENABLED()) THEN\n'
        '        CALL NI_BEGIN((/WTLF,STMWT,RTWT/))\n'
        '        NILEAK0=TNLEAK\n      ENDIF\n'+a)
    # Preserve the complete official soil uptake/cost branch as the ELSE path.
    start=s.index("      IF (ISWNIT .EQ. 'Y') THEN\n        CALL NUPTAK(INTEGR,")
    end=s.index('C    CALL Nitrogen mobilization subroutine',start)
    official=s[start:end]
    # Ends in the original ENDIF and separator comments. Put new choice INSIDE ISWNIT.
    first="      IF (ISWNIT .EQ. 'Y') THEN\n"
    new=(first+"      IF (NI_ENABLED()) THEN\n"
      "        IF (NI_ROOT_MODE().GT.0) THEN\n"
      "          CALL NI_ROOT_UPTAKE(CONTROL,NLAYR,SOILPROP%BD,\n"
      "     &      DLAYR,LL,DUL,SAT,NO3,NH4,KG2PPM,UNO3,UNH4)\n"
      "        ELSE\n"
      "          CALL NUPTAK(INTEGR,\n"
      "     &      DLAYR,DUL,FILECC,KG2PPM,LL,NDMSDR,NDMTOT,\n"
      "     &      NH4,NO3,NLAYR,RLV,SAT,SW,\n"
      "     &      TRNH4U,TRNO3U,TRNU,UNH4,UNO3)\n"
      "        ENDIF\n"
      "        CALL NI_ACCEPT_UPTAKE(UNO3,UNH4,NLAYR,\n"
      "     &    TRNO3U,TRNH4U,TRNU)\n"
      "        CALL NI_ASSIMILATE(PGAVL,MAX(0.,NDMTOT-NAVL),DTX,\n"
      "     &    RNO3C,RNH4C,NASSIMD,RSPNO3,RSPNH4)\n"
      "        NAVL=NAVL+NASSIMD\n"
      "      ELSE\n")
    tail=official[len(first):]
    last=tail.rfind('      ENDIF\n')
    tail=tail[:last]+'      ENDIF\n'+tail[last:]
    s=s[:start]+new+tail+s[end:]
    a='      CALL MOBIL(INTEGR,\n     &    NDMNEW, NMINEP, NMOBR, RPRO, TRNU,'
    b='      NFORGROW=TRNU\n      IF (NI_ENABLED()) NFORGROW=NASSIMD\n'
    b+='      CALL MOBIL(INTEGR,\n     &    NDMNEW, NMINEP, NMOBR, RPRO, NFORGROW,'
    s=once(s,a,b)
    start=s.index('      CALL VEGGR(INTEGR,')
    end=s.index('C     Compute C required for LF',start)
    fragment=s[start:end].replace('     &    TRNU, TURFAC,','     &    NFORGROW, TURFAC,')
    s=s[:start]+fragment+s[end:]
    a='      PGAVL = PGAVL - AGRVG * (WLDOTN + WSDOTN + WRDOTN)\n'
    new="      IF (NI_ENABLED()) THEN\n"
    new+="        NIUNUSED=MIN(NASSIMD,MAX(0.,TNLEAK-NILEAK0))\n"
    new+="        CALL NI_SETTLE(NIUNUSED,RSPNO3,RSPNH4,NASSIMD,NIREFUND)\n"
    new+="        TNLEAK=TNLEAK-NIUNUSED\n        NAVL=NAVL-NIUNUSED\n"
    new+="        PGAVL=PGAVL+NIREFUND\n"
    new+="        NISHARE=MAX(0.,WTLF)/MAX(1.E-12,WTLF+STMWT)\n"
    new+="        CADLF=CADLF+NIREFUND/PCH2O*NISHARE\n"
    new+="        CADST=CADST+NIREFUND/PCH2O*(1.-NISHARE)\n"
    new+="        NFORGROW=NASSIMD\n      ENDIF\n"
    s=once(s,a,new+a)
    a='      IF ((TRNU + NFIXN + NMINEA) .GT. 1.E-4) THEN\n'
    new="      IF (NI_ENABLED()) THEN\n"
    new+="        IF ((NFORGROW+NFIXN+NMINEA).GT.1.E-4) THEN\n"
    new+="          RPROAV=((RSPNO3+RSPNH4)*0.16+NFIXN*RFIXN\n"
    new+="     &      +NMINEA*RPRO)/(NFORGROW+NFIXN+NMINEA)\n"
    new+="        ELSE\n          RPROAV=(RNO3C+RNH4C)/2.\n        ENDIF\n"
    new+="      ELSE\n"
    s=once(s,a,new+a)
    a='         RPROAV = (RNO3C + RNH4C) / 2.\n      ENDIF\n'
    s=once(s,a,a+'      ENDIF\n')
    a='      IF ((WTLF+STMWT).GT. 0.0001) THEN\n'
    s=once(s,a,'      IF (NI_ENABLED()) THEN\n'
      '        CALL NI_END(CONTROL,(/WTLF,STMWT,RTWT/),\n'
      '     &    (/SLDOT+WLIDOT+WLFDOT,SSDOT+WSIDOT,SRDOT+WRIDOT/),\n'
      '     &    SENRT,NLAYR,(/WTNLF,WTNST,WTNRT/),XLAI,WCRLF)\n'
      '      ENDIF\n'+a)
    return s
def nuptak(s):
    s=once(s,'      USE ModuleDefs\n','      USE ModuleDefs\n      USE CG_Nitrogen, ONLY: NI_SET_NH4\n')
    a='      CLOSE (LUNCRP)\n'
    return once(s,a,a+'      CALL NI_SET_NH4(RTNH4)\n')
def soil(s):
    s=once(s,'      USE CG_P0Trace\n','      USE CG_P0Trace\n      USE CG_Nitrogen, ONLY: NI_RETURN_LITTER\n')
    a='      DO L = 1, NLAYR\n!       Update with yesterday\'s plant N uptake\n'
    return once(s,a,'      CALL NI_RETURN_LITTER(SNO3,SNH4,NLAYR)\n'+a)
def balance(s):
    s=once(s,'      USE Interface_SoilNBalSum\n',
      '      USE Interface_SoilNBalSum\n      USE CG_Nitrogen, ONLY: NI_ENABLED, NI_SOIL_INPUT\n')
    s=once(s,'      REAL UnreleasedN  !Slow release fertilizer\n',
      '      REAL UnreleasedN  !Slow release fertilizer\n      REAL NIINPUTY, NIINPUT\n')
    a='      IF (DYNAMIC == SEASINIT) THEN\n'
    s=once(s,a,a+'      NIINPUTY=0.\n')
    a='      TOTADD   = AMTFERTODAY + MINERTODAY\n'
    s=once(s,a,a+'      IF (NI_ENABLED()) THEN\n'
      '        NIINPUT=NI_SOIL_INPUT()\n'
      '        TOTADD=TOTADD+NIINPUT-NIINPUTY\n'
      '        NIINPUTY=NIINPUT\n      ENDIF\n')
    a='        TALLNI  = TALLNI + AMTFER + CMINERN !Initial + add\n'
    s=once(s,a,a+'        IF (NI_ENABLED()) TALLNI=TALLNI+NI_SOIL_INPUT()\n')
    a='        WRITE(LUNSNC,800) TALLNI, TALLN\n'
    return once(s,a,'        IF (NI_ENABLED()) WRITE(LUNSNC,\n'
      '     &    \'(A,F14.6)\') " Inorganic tissue return input kg N/ha: ",\n'
      '     &    NI_SOIL_INPUT()\n'+a)
def main():
    prepared={p:fn((ROOT/p).read_text(encoding='latin-1')) for p,fn in [
       ('Plant/CROPGRO/CROPGRO.for',crop),('Plant/CROPGRO/NUPTAK.for',nuptak),
       ('Soil/Inorganic_N/SOILNI.for',soil),('Soil/Inorganic_N/SoilNiBal.for',balance)]}
    for p,text in prepared.items():(ROOT/p).write_text(text,encoding='latin-1',newline='\n')
    edit('CMakeLists.txt',lambda s:once(s,'        "Utilities/CG_P0Trace.f90"\n',
      '        "Utilities/CG_P0Trace.f90"\n        "Plant/CROPGRO/CG_Nitrogen.f90"\n'))
if __name__=='__main__':main()

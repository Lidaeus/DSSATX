from tools.experiments.derive_default_initial_n_bundle import (
    replace_initial_mineral_n,
)


FILEX = """*EXP.DETAILS
example
*INITIAL CONDITIONS
@C   PCR ICDAT  ICRT  ICND  ICRN  ICRE  ICWD ICRES ICREN ICREP ICRIP ICRID ICNAME
 1   -99 25069     1     0     1     1   -99   -99   -99   -99   -99   -99 1
@C  ICBL  SH2O  SNH4  SNO3
 1    20  .216   1.5  33.7
 1    40  .224     1  13.8
*PLANTING DETAILS
"""


def test_replace_initial_mineral_n_changes_only_n_fields():
    transformed, audit = replace_initial_mineral_n(FILEX, snh4=0.5, sno3=1.0)
    assert len(audit) == 2
    assert "  1    20  .216    .5     1" in transformed
    assert "  1    40  .224    .5     1" in transformed
    assert "*PLANTING DETAILS" in transformed
    assert audit[0]["old_snh4"] == 1.5
    assert audit[0]["old_sno3"] == 33.7

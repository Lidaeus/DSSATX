from pathlib import Path

import pandas as pd

from src.dssat.run_dssat import update_planting_details_file


def _write_filex(path: Path, page="60", penv="25") -> None:
    path.write_text(
        "*PLANTING DETAILS\n"
        "@P PDATE EDATE PPOP PPOE PLME PLDS PLRS PLRD PLDP PLWT PAGE PENV PLPH SPRL\n"
        f" 2 25075   -99   2.7   2.7     T     R    90    90     8   9.5    {page:>2}    {penv:>2}     1     8                        Eggplant\n"
        "*FERTILIZERS\n",
        encoding="utf-8",
    )


def _write_params(path: Path) -> None:
    pd.DataFrame(
        {
            "name": ["PAGE_25SP", "PENV_25SP", "PAGE_26SP", "PENV_26SP"],
            "value": [60, 20, 34, 19],
        }
    ).to_csv(path, index=False)


def test_season_scoped_page_penv_injection_preserves_other_fields(tmp_path: Path):
    params = tmp_path / "pest_params.csv"
    _write_params(params)

    filex25 = tmp_path / "XXQL2501.TMX"
    _write_filex(filex25)
    before25 = filex25.read_text(encoding="utf-8").splitlines()[2].split()
    update_planting_details_file(str(params), str(filex25))
    after25 = filex25.read_text(encoding="utf-8").splitlines()[2].split()
    assert after25[11:13] == ["60", "20"]
    assert after25[:11] == before25[:11]
    assert after25[13:] == before25[13:]

    filex26 = tmp_path / "XXQL2601.TMX"
    _write_filex(filex26)
    before26 = filex26.read_text(encoding="utf-8").splitlines()[2].split()
    update_planting_details_file(str(params), str(filex26))
    after26 = filex26.read_text(encoding="utf-8").splitlines()[2].split()
    assert after26[11:13] == ["34", "19"]
    assert after26[:11] == before26[:11]
    assert after26[13:] == before26[13:]

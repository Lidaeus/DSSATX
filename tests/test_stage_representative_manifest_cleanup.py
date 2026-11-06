from src.calibration.stage_representative import clear_stage_representative_manifest_fields


def test_clear_stage_representative_manifest_fields_preserves_other_fields(tmp_path):
    manifest = tmp_path / "run_manifest.yaml"
    manifest.write_text(
        "run_id: 'new_case'\n"
        "stage_representative_params: 'old/rep.csv'\n"
        "stage_representative_params_sha256: 'abc'\n"
        "stage_representative_rule: 'median_of_final_parameter_ensemble'\n"
        "stage_representative_source: 'old.5.par.csv'\n"
        "stage_representative_source_sha256: 'def'\n"
        "noptmax: 4\n",
        encoding="utf-8",
    )

    removed = clear_stage_representative_manifest_fields(manifest)

    assert set(removed) == {
        "stage_representative_params",
        "stage_representative_params_sha256",
        "stage_representative_rule",
        "stage_representative_source",
        "stage_representative_source_sha256",
    }
    assert manifest.read_text(encoding="utf-8") == "run_id: 'new_case'\nnoptmax: 4\n"

from src.sensitivity.replay_morris_failure import (
    apply_candidate_minimums,
    batch_treatments,
    read_candidate,
    write_filtered_batch,
)


def test_candidate_and_treatment_batch_are_reconstructed(tmp_path):
    parameter_file = tmp_path / "case.sen.par.csv"
    parameter_file.write_text(
        "run_id,a,b\n0,1.0,2.0\n1,3.0,4.0\n", encoding="utf-8"
    )
    assert read_candidate(parameter_file, 1) == {"a": "3.0", "b": "4.0"}

    batch = tmp_path / "DSSBatch.v48"
    batch.write_text(
        "$BATCH(TEST)\n"
        "@FILEX TRTNO RP SQ OP CO\n"
        "XXQL2501.TMX 2 1 0 0 0\n"
        "XXQL2501.TMX 3 1 0 0 0\n",
        encoding="utf-8",
    )
    assert batch_treatments(batch) == [2, 3]
    filtered = write_filtered_batch(batch, tmp_path / "tn3.v48", 3)
    text = filtered.read_text(encoding="utf-8")
    assert " 3 1 0 0 0" in text
    assert " 2 1 0 0 0" not in text


def test_diagnostic_minimums_only_raise_values_below_candidate_bound():
    candidate, changes = apply_candidate_minimums(
        {"slaref": "225", "xmage": "11", "other": "2"},
        {"SLAREF": 250, "xmage": 10},
    )
    assert candidate == {"slaref": "250", "xmage": "11", "other": "2"}
    assert changes == {"slaref": {"original": 225.0, "minimum": 250.0}}

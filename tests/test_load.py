from stagecraft.load import ORIG_COLS, PERF_COLS, parse_orig, perf_lazy


def test_layout_has_32_columns_each():
    assert len(ORIG_COLS) == 32 and len(PERF_COLS) == 32
    assert ORIG_COLS[19] == "loan_id" and PERF_COLS[3] == "dlq_status" and PERF_COLS[8] == "zb_code"


def test_parse_pipe_files(tmp_path):
    o = ["9999", "201803", "N", "204802", "", "025", "1", "P", "90", "999", "200000", "90", "4.500", "R", "N", "FRM",
         "CA", "SF", "94100", "F18Q1000001", "P", "360", "02", "x", "y", "", "", "9", "", "9", "N", "N"]
    (tmp_path / "o.txt").write_text("|".join(o) + "\n")
    df = parse_orig(tmp_path / "o.txt", 2018)
    r = df.row(0, named=True)
    assert r["credit_score"] is None and r["dti"] is None  # 9999 / 999 -> missing
    assert r["fpd_mi"] == 2018 * 12 + 2 and r["ltv"] == 90 and r["orig_rate"] == 4.5
    p1 = ["F18Q1000001", "201805", "199000.00", "RA", "3", "357", "", "", "", "", "4.500", "0"] + [""] * 20
    p2 = ["F18Q1000001", "201806", "0.00", "4", "4", "356", "", "P", "9", "201806", "4.500", "0"] + [""] * 20
    (tmp_path / "p.txt").write_text("|".join(p1) + "\n" + "|".join(p2) + "\n")
    p = perf_lazy(tmp_path / "p.txt").collect()
    assert p["reo"].to_list() == [True, False]
    assert p["status"].to_list() == [None, 4]
    assert p["zb_code"].to_list() == [None, "09"]  # zero-padded
    assert p["mi"].to_list() == [2018 * 12 + 4, 2018 * 12 + 5]


def test_parse_current_release_layout(tmp_path):
    """Current release: 31-field origination (servicer name and MI cancellation
    moved to the performance file), sample_perf naming, zero-padded status codes."""
    o = ["646", "200505", "N", "203504", "17140", "0", "1", "P", "77", "43", "274000", "77", "6.125", "R", "N", "FRM",
         "KY", "SF", "410", "F05Q10000011", "N", "360", "2", "OTHER", "N", "", "", "N", "7", "N", "9999"]
    (tmp_path / "sample_orig_2005.txt").write_text("|".join(o) + "\n")
    p = ["F05Q10000011", "201309", "0.00", "00", "101", "259", "", "", "01", "201309", "6.125", "0.00"] + [""] * 20 \
        + ["7", "OTHER", ""]
    (tmp_path / "sample_perf_2005.txt").write_text("|".join(p) + "\n")
    from stagecraft.load import discover
    found = discover(tmp_path)
    assert set(found[2005]) == {"orig", "svcg"}
    r = parse_orig(found[2005]["orig"], 2005).row(0, named=True)
    assert r["loan_id"] == "F05Q10000011" and r["loan_purpose"] == "N" and r["orig_term"] == 360
    assert r["io_indicator"] == "N" and r["ltv"] == 77
    q = perf_lazy(found[2005]["svcg"]).collect().row(0, named=True)
    assert q["status"] == 0 and q["zb_code"] == "01" and q["current_rate"] == 6.125


def test_loss_sign_detection_handles_negative_recoveries(cfg):
    import polars as pl

    from stagecraft.datacheck import sign_convention

    # Current release: recoveries negative, expenses positive, Actual Loss positive.
    loans = pl.DataFrame({
        "exit_code": ["09", "03"], "zb_removal_upb": [100_000.0, 50_000.0], "dai": [5_000.0, 2_000.0],
        "net_sales_proceeds": [-60_000.0, -40_000.0], "mi_recoveries": [-10_000.0, 0.0], "non_mi_recoveries": [0.0, -500.0],
        "expenses": [8_000.0, 3_000.0], "actual_loss": [43_000.0, 14_500.0],
    })
    assert sign_convention(loans, cfg)["sign"] == 1
    # Older convention: loss negative.
    flipped = loans.with_columns(-pl.col("actual_loss"))
    assert sign_convention(flipped, cfg)["sign"] == -1

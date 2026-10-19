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

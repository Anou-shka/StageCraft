import polars as pl

from stagecraft.buckets import DEFAULT, bucket_of_status, is_dpd_default, loan_events


def test_bucket_assignment(cfg):
    df = pl.DataFrame({"status": [0, 1, 2, 3, 4, 12]})
    out = df.select(bucket_of_status(pl.col("status"), cfg)).to_series().to_list()
    assert out == [0, 1, 2, DEFAULT, DEFAULT, DEFAULT]


def test_default_flag_status_and_reo(cfg):
    df = pl.DataFrame({"status": [0, 2, 3, None], "reo": [False, False, False, True]})
    out = df.select(is_dpd_default(pl.col("status"), pl.col("reo"), cfg)).to_series().to_list()
    assert out == [False, False, True, True]


def _perf(rows):
    cols = ["loan_id", "mi", "status", "reo", "zb_code", "current_upb", "actual_loss", "net_sales_proceeds", "nsp_raw",
            "mi_recoveries", "non_mi_recoveries", "expenses", "dai", "zb_removal_upb", "current_rate", "mod_flag"]
    data = {c: [] for c in cols}
    for r in rows:
        base = dict(zip(cols, [None] * len(cols)))
        base.update(r)
        for c in cols:
            data[c].append(base[c])
    return pl.DataFrame(data, schema_overrides={"zb_code": pl.String, "nsp_raw": pl.String, "mod_flag": pl.String,
                                                 "actual_loss": pl.Float64, "net_sales_proceeds": pl.Float64,
                                                 "mi_recoveries": pl.Float64, "non_mi_recoveries": pl.Float64,
                                                 "expenses": pl.Float64, "dai": pl.Float64, "zb_removal_upb": pl.Float64,
                                                 "current_rate": pl.Float64, "status": pl.Int16}).lazy()


def test_default_month_dpd_vs_credit_event(cfg):
    rows = [
        # A: rolls to 90+ in month 3, then REO disposition
        {"loan_id": "A", "mi": 1, "status": 0, "reo": False, "current_upb": 100.0},
        {"loan_id": "A", "mi": 2, "status": 1, "reo": False, "current_upb": 100.0},
        {"loan_id": "A", "mi": 3, "status": 3, "reo": False, "current_upb": 100.0},
        {"loan_id": "A", "mi": 4, "status": 4, "reo": False, "zb_code": "09", "current_upb": 0.0, "zb_removal_upb": 100.0},
        # B: short sale straight from 60 DPD (credit event without a 90+ month)
        {"loan_id": "B", "mi": 1, "status": 2, "reo": False, "current_upb": 50.0},
        {"loan_id": "B", "mi": 2, "status": 2, "reo": False, "zb_code": "03", "current_upb": 0.0, "zb_removal_upb": 50.0},
        # C: prepaid, never in default
        {"loan_id": "C", "mi": 1, "status": 0, "reo": False, "current_upb": 80.0},
        {"loan_id": "C", "mi": 2, "status": 0, "reo": False, "zb_code": "01", "current_upb": 0.0, "zb_removal_upb": 80.0},
    ]
    ev = loan_events(_perf(rows), cfg).collect().sort("loan_id").to_dicts()
    a, b, c = ev
    assert a["default_mi"] == 3 and a["exit_type"] == "credit_event" and a["upb_at_default"] == 100.0
    assert b["default_mi"] == 2 and b["exit_type"] == "credit_event" and b["upb_at_default"] == 50.0
    assert c["default_mi"] is None and c["exit_type"] == "prepaid"

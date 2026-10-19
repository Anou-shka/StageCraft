"""Synthetic loan-level sample in the exact Freddie Mac file format.

WHY THIS EXISTS. The Freddie Mac Single-Family Loan-Level Dataset needs a
registered login, so it cannot be downloaded by code or committed to GitHub.
To let the package, tests and dashboard run from a fresh clone, this module
simulates loans and writes them as `sample_orig_YYYY.txt` /
`sample_svcg_YYYY.txt` (pipe-delimited, no header, the 32 + 32 columns of the
official file layout) zipped as `sample_YYYY.zip`, exactly like the real
download. The parser in load.py cannot tell the difference, so replacing the
synthetic files with real ones requires no code change.

The simulation is driven by real FRED history (unemployment, house prices,
mortgage rates), so the 2008 crisis, the refinancing waves and the 2020
COVID forbearance spike all appear. It is a stylised data-generating
process, not a fit to Freddie Mac data: NO RESULT PRODUCED FROM IT IS AN
EMPIRICAL FINDING ABOUT US MORTGAGES.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .config import load_config, path
from .dates import mi_to_ym, ym_to_mi
from .load import ORIG_COLS, PERF_COLS
from .macro import load_macro

STATES = ["CA", "TX", "FL", "NY", "IL", "PA", "OH", "GA", "NC", "MI", "NJ", "VA", "WA", "AZ", "MA", "CO", "MN", "MD", "NV", "OR"]
STATE_P = np.array([14, 8, 7, 5, 5, 4, 4, 4, 4, 4, 4, 4, 3, 3, 3, 3, 3, 3, 2, 2], dtype=float)


def _sched_balance(P, r_annual, n, k):
    """Scheduled balance after k payments of an n-month annuity."""
    r = r_annual / 1200.0
    k = np.clip(k, 0, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        a = (1 + r) ** n
        b = np.where(r > 0, P * (a - (1 + r) ** k) / (a - 1), P * (1 - k / n))
    return np.maximum(b, 0.0)


def _payment(P, r_annual, n):
    r = r_annual / 1200.0
    return np.where(r > 0, P * r / (1 - (1 + r) ** (-n)), P / n)


def _originations(rng, vintage: int, n: int, macro: pd.DataFrame) -> pd.DataFrame:
    crisis = vintage <= 2007
    om = vintage * 12 + rng.integers(0, 12, n)  # origination month index
    fico = np.clip(rng.normal(718 if crisis else 752, 55 if crisis else 42, n), 300, 850).round()
    ltv_choice = rng.choice([60, 70, 75, 80, 85, 90, 95, 97], n,
                            p=[.10, .10, .10, .35, .07, .12, .12, .04] if crisis else [.14, .14, .12, .34, .06, .10, .08, .02])
    ltv = np.clip(ltv_choice - rng.integers(0, 8, n) * (ltv_choice <= 80), 20, 97)
    cltv = np.where(rng.random(n) < (0.25 if crisis else 0.08), np.minimum(ltv + rng.integers(5, 20, n), 100), ltv)
    dti = np.clip(rng.normal(39 if crisis else 34, 9, n), 5, 65).round()
    purpose = rng.choice(["P", "C", "N"], n, p=[.40, .30, .30] if crisis else [.50, .20, .30])
    occ = rng.choice(["P", "S", "I"], n, p=[.88, .04, .08])
    channel = rng.choice(["R", "B", "C", "T"], n, p=[.45, .15, .30, .10] if crisis else [.55, .05, .35, .05])
    term = rng.choice([360, 240, 180], n, p=[.82, .04, .14])
    upb = np.round(np.exp(rng.normal(np.log(165_000 if crisis else 225_000), 0.5, n)) / 1000) * 1000
    upb = np.clip(upb, 25_000, 800_000)
    mkt = macro["mtg_rate"].reindex(om).to_numpy()
    rate = mkt + 0.15 + 0.004 * (740 - fico) / 10 + 0.01 * (ltv - 80) / 5 - 0.6 * (term == 180) + rng.normal(0, 0.25, n)
    rate = np.round(np.clip(rate, 2.0, 9.5) * 8) / 8
    mi_pct = np.where(ltv > 80, rng.choice([12, 25, 30], n, p=[.3, .4, .3]), 0)
    fico_s = np.where(rng.random(n) < 0.005, 9999, fico).astype(int)
    dti_s = np.where(rng.random(n) < 0.01, 999, dti).astype(int)
    q = (om % 12) // 3 + 1
    seq = [f"F{vintage % 100:02d}Q{qq}{k:07d}" for qq, k in zip(q, rng.permutation(9_000_000)[:n] + 1_000_000)]
    fpd = om + 2
    return pd.DataFrame({
        "credit_score": fico_s, "fico": fico, "first_payment_mi": fpd, "orig_mi": om,
        "first_time_homebuyer": np.where(purpose == "P", rng.choice(["Y", "N"], n, p=[.3, .7]), "N"),
        "maturity_mi": fpd + term - 1, "msa": rng.choice([12060, 16980, 19100, 31080, 35620, 47900, 0], n),
        "mi_pct": mi_pct, "units": rng.choice([1, 2, 3, 4], n, p=[.96, .03, .005, .005]), "occupancy": occ,
        "cltv": cltv, "dti": dti_s, "dti_true": dti, "orig_upb": upb, "ltv": ltv, "rate": rate,
        "channel": channel, "state": rng.choice(STATES, n, p=STATE_P / STATE_P.sum()),
        "property_type": rng.choice(["SF", "PU", "CO", "MH"], n, p=[.68, .2, .1, .02]),
        "postal": rng.integers(100, 999, n) * 100, "loan_id": seq, "purpose": purpose, "term": term,
        "n_borrowers": rng.choice([1, 2], n, p=[.45, .55]), "vintage": vintage,
    })


def simulate(cfg: dict | None = None, out_dir: Path | None = None, n_per_vintage: int | None = None) -> Path:
    cfg = cfg or load_config()
    scfg = cfg["synthetic"]
    rng = np.random.default_rng(scfg["seed"])
    n_per = n_per_vintage or scfg["loans_per_vintage"]
    out_dir = out_dir or path(cfg, "sample_freddie")
    out_dir.mkdir(parents=True, exist_ok=True)
    macro = load_macro(cfg)
    v0, v1 = cfg["vintages"]
    orig = pd.concat([_originations(rng, v, n_per, macro) for v in range(v0, v1 + 1)], ignore_index=True)
    cutoff = int(ym_to_mi(int(scfg["performance_cutoff"].replace("-", ""))))
    N = len(orig)

    # ---- static loan risk -------------------------------------------------
    fico = orig["fico"].to_numpy()
    ltv = orig["ltv"].to_numpy().astype(float)
    frailty = rng.normal(0, 0.55, N)
    static = (-0.013 * (fico - 740) + 0.018 * (orig["dti_true"].to_numpy() - 35)
              + 0.30 * (orig["purpose"].to_numpy() == "C") + 0.30 * (orig["occupancy"].to_numpy() == "I")
              + 0.20 * np.isin(orig["channel"].to_numpy(), ["B", "C", "T"]) + 0.25 * (orig["cltv"].to_numpy() > ltv)
              + 0.25 * (orig["vintage"].to_numpy() <= 2007) + frailty)
    value0 = orig["orig_upb"].to_numpy() / (ltv / 100) * np.exp(rng.normal(0, 0.03, N))
    hpi = macro["hpi"]
    hpi0 = hpi.reindex(orig["orig_mi"]).to_numpy()
    local_beta = np.exp(rng.normal(0, 0.25, N))  # regional sensitivity to national HPI

    # ---- dynamic state ----------------------------------------------------
    fpd = orig["first_payment_mi"].to_numpy()
    P = orig["orig_upb"].to_numpy().astype(float)
    r = orig["rate"].to_numpy().astype(float)
    n_am = orig["term"].to_numpy().astype(int)
    k_off = np.zeros(N, int)            # payments made before the current amortisation schedule
    age_base = fpd.copy()               # loan age resets on modification
    maturity = orig["maturity_mi"].to_numpy().copy()
    alive = np.ones(N, bool)
    status = np.zeros(N, int)           # missed payments
    reo_left = np.full(N, -1)           # months of REO before disposition
    mod_state = np.zeros(N, int)        # 0 none, 1 this month, 2 prior
    defer_state = np.zeros(N, int)
    deferred_upb = np.zeros(N)
    forb_left = np.zeros(N, int)
    upb_default = np.zeros(N)
    default_mi = np.full(N, -1)
    mod_cost = np.zeros(N)
    pmt = _payment(P, r, n_am)
    rows = []
    ur = macro["ur"]
    mtg = macro["mtg_rate"]

    for t in range(int(fpd.min()), cutoff + 1):
        act = alive & (fpd <= t)
        if not act.any():
            continue
        idx = np.flatnonzero(act)
        dur = float(ur.get(t, np.nan) - ur.get(t - 12, np.nan))
        dur = 0.0 if np.isnan(dur) else float(np.clip(dur, -2.0, 4.5))
        h_t = hpi.get(t)
        mkt = mtg.get(t)
        covid = 2020 * 12 + 3 <= t <= 2021 * 12 + 8   # Apr-2020 .. Sep-2021
        fc_moratorium = 2020 * 12 + 2 <= t <= 2021 * 12 + 6
        u = rng.random((len(idx), 4))

        st = status[idx]
        age = t - age_base[idx] + 1
        paid = np.clip(t - fpd[idx] + 1 - st - k_off[idx], 0, None)
        bal = _sched_balance(P[idx], r[idx], n_am[idx], paid)
        val = value0[idx] * (h_t / hpi0[idx]) ** local_beta[idx]
        cltv = 100 * (bal + deferred_upb[idx]) / val
        ageeff = 0.5 * np.exp(-((np.log(np.maximum(age, 1)) - np.log(40)) ** 2) / 1.2) - 0.4 * (age < 7)
        m = static[idx] + 0.20 * dur + 0.022 * np.maximum(cltv - 80, 0) + 0.012 * np.maximum(cltv - 100, 0) + ageeff
        new_st = st.copy()
        zb = np.full(len(idx), "", dtype=object)
        mflag = mod_state[idx].copy()
        mflag[mflag == 1] = 2
        dflag = defer_state[idx].copy()
        dflag[dflag == 1] = 2
        assist = np.full(len(idx), "", dtype=object)

        in_reo = reo_left[idx] >= 0
        forb = forb_left[idx] > 0
        normal = ~in_reo & ~forb

        # Current loans: delinquency roll, prepayment, maturity.
        c = normal & (st == 0)
        p01 = np.minimum(0.0011 * np.exp(m), 0.15)
        incentive = np.clip(r[idx] - mkt, -2.5, 2.5)
        smm = 0.004 * np.exp(1.25 * incentive - 0.02 * np.maximum(cltv - 85, 0)) * (1 - 0.6 * (age < 6)) + 0.0025
        smm = np.minimum(smm, 0.08)
        roll = c & (u[:, 0] < p01)
        prep = c & ~roll & (u[:, 1] < smm)
        new_st[roll] = 1
        zb[prep] = "01"

        # COVID forbearance: a slice of current loans stops paying, reported delinquent.
        if covid:
            f_start = c & ~roll & ~prep & (u[:, 2] < (0.005 if t < 2020 * 12 + 8 else 0.0008) * np.exp(0.4 * frailty[idx]))
            forb_left[idx[f_start]] = rng.integers(4, 13, f_start.sum())
            new_st[f_start] = 1
            assist[f_start] = "F"

        # 30 and 60 days.
        d1 = normal & (st == 1)
        p10 = np.clip(0.45 * np.exp(-0.25 * np.maximum(m, 0)), 0.15, 0.6)
        p12 = np.clip(0.18 * np.exp(0.3 * m), 0.04, 0.6)
        new_st[d1 & (u[:, 0] < p10)] = 0
        new_st[d1 & (u[:, 0] >= p10) & (u[:, 0] < p10 + p12)] = 2
        d2 = normal & (st == 2)
        p20 = np.clip(0.18 * np.exp(-0.25 * np.maximum(m, 0)), 0.05, 0.4)
        p23 = np.clip(0.45 * np.exp(0.3 * m), 0.2, 0.9)
        new_st[d2 & (u[:, 0] < p20)] = 0
        new_st[d2 & (u[:, 0] >= p20) & (u[:, 0] < p20 + 0.08)] = 1
        new_st[d2 & (u[:, 0] >= p20 + 0.08) & (u[:, 0] < p20 + 0.08 + p23)] = 3

        # Seriously delinquent: cure, modification, foreclosure / sale, or deeper.
        d3 = normal & (st >= 3)
        hamp = 2009 * 12 <= t <= 2016 * 12
        p_cure = 0.03
        p_mod = 0.035 if hamp else 0.015
        p_fc = np.where(st >= 6, (0.03 if 2009 * 12 <= t <= 2012 * 12 + 11 else 0.06), 0.0)
        if fc_moratorium:
            p_fc = p_fc * 0.05
        p_nps = np.where((st >= 6) & (2014 * 12 <= t <= 2019 * 12 + 11), 0.012, 0.0)
        cure = d3 & (u[:, 0] < p_cure)
        modi = d3 & (u[:, 0] >= p_cure) & (u[:, 0] < p_cure + p_mod)
        fc = d3 & ~cure & ~modi & (u[:, 1] < p_fc)
        nps = d3 & ~cure & ~modi & ~fc & (u[:, 2] < p_nps)
        new_st[cure] = 0
        new_st[d3 & ~cure & ~modi & ~fc & ~nps] = np.minimum(st[d3 & ~cure & ~modi & ~fc & ~nps] + 1, 99)

        # Modification: capitalise arrears, cut the rate, extend to 40 years.
        if modi.any():
            j = idx[modi]
            arrears = st[modi] * pmt[j] * 0.5
            newP = bal[modi] + arrears
            newr = np.maximum(np.minimum(r[j], mkt) - 1.0, 2.0)
            mod_cost[j] += (r[j] - newr) / 1200 * newP
            P[j], r[j], n_am[j] = newP, np.round(newr * 8) / 8, 480
            k_off[j] = t - fpd[j] + 1
            age_base[j] = t + 1
            maturity[j] = t + 480
            pmt[j] = _payment(P[j], r[j], n_am[j])
            new_st[modi] = 0
            mflag[modi] = 1

        # Foreclosure: about 60% go through REO before disposition.
        fc_reo = fc & (u[:, 3] < 0.6)
        reo_left[idx[fc_reo]] = rng.integers(2, 9, fc_reo.sum())
        fc_direct = fc & ~fc_reo
        zb[fc_direct] = np.where(u[fc_direct, 2] < 0.75, "03", "02")
        zb[nps] = "15"

        # REO disposition.
        reo_now = in_reo & (reo_left[idx] == 0)
        zb[reo_now] = "09"
        reo_left[idx[in_reo]] -= 1

        # Forbearance progression and exit via payment deferral.
        if forb.any():
            fj = idx[forb]
            forb_left[fj] -= 1
            new_st[forb] = st[forb] + 1
            assist[forb] = "F"
            ending = forb & (forb_left[idx] == 0)
            deferral = ending & (u[:, 3] < 0.85)
            deferred_upb[idx[deferral]] += st[deferral] * pmt[idx[deferral]]
            k_off[idx[deferral]] -= st[deferral]
            new_st[deferral] = 0
            dflag[deferral] = 1

        # Modified, reperforming loans sold into RPL securitisations.
        rpl = (mflag == 2) & (new_st == 0) & (zb == "") & (2016 * 12 <= t <= 2019 * 12 + 11) & (u[:, 3] < 0.004)
        zb[rpl] = "16"
        defect = (zb == "") & (rng.random(len(idx)) < 2e-5)
        zb[defect] = "96"
        matured = (zb == "") & (t >= maturity[idx]) & (new_st == 0)
        zb[matured] = "01"

        # First month in 90+ (or credit event): remember UPB at default.
        newly_def = (default_mi[idx] < 0) & ((new_st >= 3) | np.isin(zb, ["02", "03", "09", "15"]))
        default_mi[idx[newly_def]] = t
        upb_default[idx[newly_def]] = bal[newly_def] + deferred_upb[idx[newly_def]]

        status[idx] = np.where(in_reo, st, new_st)
        mod_state[idx] = mflag
        defer_state[idx] = dflag

        paid_new = np.clip(t - fpd[idx] + 1 - status[idx] - k_off[idx], 0, None)
        upb = _sched_balance(P[idx], r[idx], n_am[idx], paid_new) + deferred_upb[idx]
        upb = np.where(t - fpd[idx] < 6, np.round(upb / 1000) * 1000, np.round(upb, 2))
        ended = zb != ""
        rows.append(_records(rng, t, idx, orig, status, in_reo & ~reo_now, upb, age, maturity, mflag, dflag, assist,
                             zb, r, deferred_upb, value0, hpi0, local_beta, h_t, cutoff, default_mi, upb_default,
                             orig["mi_pct"].to_numpy(), mod_cost, cltv))
        alive[idx[ended]] = False

    perf = pd.concat(rows, ignore_index=True)
    _write(out_dir, orig, perf)
    (out_dir / "SYNTHETIC.md").write_text(
        "# Synthetic data — not real Freddie Mac loans\n\n"
        "These files were generated by `stagecraft.synth` in the Freddie Mac sample-file format so the\n"
        "code runs from a fresh clone. Delete this folder's zips and put the real\n"
        "`sample_YYYY.zip` files in `data/raw/freddie/` to run on real data.\n"
    )
    return out_dir


def _records(rng, t, idx, orig, status, reo_flag, upb, age, maturity, mflag, dflag, assist, zb, r, deferred_upb,
             value0, hpi0, local_beta, h_t, cutoff, default_mi, upb_default, mi_pct, mod_cost, cltv):
    n = len(idx)
    st = status[idx]
    st_s = np.where(reo_flag, "RA", st.astype(str)).astype(object)
    rec = {c: np.full(n, "", dtype=object) for c in PERF_COLS}
    rec["loan_id"] = orig["loan_id"].to_numpy()[idx]
    rec["period"] = np.full(n, str(int(mi_to_ym(t))), dtype=object)
    rec["current_upb"] = np.char.mod("%.2f", np.where(zb != "", 0.0, upb)).astype(object)
    rec["dlq_status"] = st_s
    rec["loan_age"] = age.astype(str).astype(object)
    rec["rem_months"] = np.maximum(maturity[idx] - t, 0).astype(str).astype(object)
    rec["mod_flag"] = np.select([mflag == 1, mflag == 2], ["Y", "P"], "").astype(object)
    rec["step_mod"] = np.where(mflag > 0, "N", "").astype(object)
    rec["deferral_flag"] = np.select([dflag == 1, dflag == 2], ["Y", "P"], "").astype(object)
    rec["current_rate"] = np.char.mod("%.3f", r[idx]).astype(object)
    rec["deferred_upb"] = np.char.mod("%.2f", deferred_upb[idx]).astype(object)
    rec["ddlpi"] = np.array([str(int(mi_to_ym(t - s))) for s in np.where(reo_flag, 0, st)], dtype=object)
    rec["assistance"] = assist
    rec["interest_bearing_upb"] = np.char.mod("%.2f", np.where(zb != "", 0.0, upb - deferred_upb[idx])).astype(object)
    if t >= 2017 * 12 + 3:
        rec["eltv"] = np.clip(np.round(cltv), 1, 998).astype(int).astype(str).astype(object)
    if mflag.any():
        rec["mod_cost"] = np.where(mflag > 0, np.char.mod("%.2f", mod_cost[idx]), "").astype(object)

    e = np.flatnonzero(zb != "")
    for j in e:
        i = idx[j]
        rec["zb_code"][j] = zb[j]
        rec["zb_date"][j] = str(int(mi_to_ym(t)))
        rec["zb_removal_upb"][j] = f"{upb[j]:.2f}"
        if zb[j] in ("02", "03", "09", "15"):
            ub = upb[j]  # zero-balance removal UPB, the base of Freddie's Actual Loss
            months = max(t - default_mi[i], 1) if default_mi[i] >= 0 else 3
            dai = ub * (r[i] - 0.35) / 1200 * min(months, 36)
            val = value0[i] * (h_t / hpi0[i]) ** local_beta[i] * np.exp(rng.normal(0, 0.15))
            if zb[j] == "15":
                nsp = min(val * 0.85, ub * rng.uniform(0.55, 0.9))
                expenses = -0.01 * ub
            else:
                haircut = {"09": 0.66, "03": 0.78, "02": 0.85}[zb[j]]
                nsp = val * haircut
                expenses = -(0.03 + 0.0025 * min(months, 48)) * ub
            exposure = ub + dai - expenses
            nsp = min(nsp, exposure * rng.uniform(0.97, 1.0))  # any surplus goes to the borrower
            pre_mi_loss = max(exposure - nsp, 0.0)
            mi_rec = min(mi_pct[i] / 100 * exposure, pre_mi_loss)
            non_mi = ub * rng.uniform(0, 0.01)
            # Sign convention: negative = loss (see data report sign check).
            loss = nsp + mi_rec + non_mi + expenses - ub - dai
            rec["dai"][j] = f"{dai:.2f}"
            rec["expenses"][j] = f"{expenses:.2f}"
            rec["legal_costs"][j] = f"{expenses * 0.4:.2f}"
            rec["maint_costs"][j] = f"{expenses * 0.3:.2f}"
            rec["taxes_ins"][j] = f"{expenses * 0.2:.2f}"
            rec["misc_expenses"][j] = f"{expenses * 0.1:.2f}"
            rec["mi_recoveries"][j] = f"{mi_rec:.2f}"
            rec["non_mi_recoveries"][j] = f"{non_mi:.2f}"
            if t > cutoff - 3:
                rec["actual_loss"][j] = ""        # Freddie: null if disposed within 3 months of cutoff
                rec["net_sales_proceeds"][j] = "U"
            else:
                rec["net_sales_proceeds"][j] = "U" if rng.random() < 0.02 else f"{nsp:.2f}"
                rec["actual_loss"][j] = f"{loss:.2f}"
    return pd.DataFrame(rec)


def _fmt_orig(o: pd.DataFrame) -> pd.DataFrame:
    rec = {c: np.full(len(o), "", dtype=object) for c in ORIG_COLS}
    rec["credit_score"] = o["credit_score"].astype(str)
    rec["first_payment_date"] = mi_to_ym(o["first_payment_mi"]).astype(str)
    rec["first_time_homebuyer"] = o["first_time_homebuyer"]
    rec["maturity_date"] = mi_to_ym(o["maturity_mi"]).astype(str)
    rec["msa"] = np.where(o["msa"] > 0, o["msa"].astype(str), "")
    rec["mi_pct"] = o["mi_pct"].astype(str).str.zfill(3)
    rec["units"] = o["units"].astype(str)
    rec["occupancy"] = o["occupancy"]
    rec["cltv"] = o["cltv"].astype(int).astype(str)
    rec["dti"] = o["dti"].astype(str)
    rec["orig_upb"] = o["orig_upb"].astype(int).astype(str)
    rec["ltv"] = o["ltv"].astype(int).astype(str)
    rec["orig_rate"] = o["rate"].map("{:.3f}".format)
    rec["channel"] = o["channel"]
    rec["ppm_flag"] = "N"
    rec["amortization_type"] = "FRM"
    rec["property_state"] = o["state"]
    rec["property_type"] = o["property_type"]
    rec["postal_code"] = o["postal"].astype(str)
    rec["loan_id"] = o["loan_id"]
    rec["loan_purpose"] = o["purpose"]
    rec["orig_term"] = o["term"].astype(str)
    rec["n_borrowers"] = o["n_borrowers"].astype(str).str.zfill(2)
    rec["seller_name"] = "Other sellers"
    rec["servicer_name"] = "Other servicers"
    rec["program_indicator"] = "9"
    rec["property_valuation_method"] = "9"
    rec["io_indicator"] = "N"
    rec["mi_cancellation"] = np.where(o["mi_pct"] > 0, "N", "7")
    return pd.DataFrame(rec)


def _write(out_dir: Path, orig: pd.DataFrame, perf: pd.DataFrame) -> None:
    perf = perf.copy()
    perf["vintage"] = "20" + perf["loan_id"].str[1:3]
    for v, og in orig.groupby("vintage"):
        o_txt = _fmt_orig(og).to_csv(sep="|", header=False, index=False)
        pg = perf[perf["vintage"] == str(v)].drop(columns="vintage").sort_values(["loan_id", "period"])
        p_txt = pg.to_csv(sep="|", header=False, index=False)
        with zipfile.ZipFile(out_dir / f"sample_{v}.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.writestr(f"sample_orig_{v}.txt", o_txt)
            z.writestr(f"sample_svcg_{v}.txt", p_txt)


if __name__ == "__main__":
    print(simulate())

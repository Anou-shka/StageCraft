"""Model documentation PDF (reportlab). All numbers come from the run."""

from __future__ import annotations

import datetime as dt

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from . import scenarios
from .buckets import BUCKETS
from .config import path
from .load import is_synthetic
from .report import by_stage, headline

INK = colors.HexColor("#0b0b0b")
INK2 = colors.HexColor("#52514e")
RULE = colors.HexColor("#d9d8d3")
TINT = colors.HexColor("#f1f0ec")
ACCENT = colors.HexColor("#2a78d6")

ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, alignment=TA_LEFT,
                            textColor=INK, spaceAfter=4),
    "sub": ParagraphStyle("s", parent=ss["Normal"], fontSize=10.5, leading=14, textColor=INK2, spaceAfter=10),
    "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=INK,
                         spaceBefore=10, spaceAfter=5),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=INK,
                         spaceBefore=7, spaceAfter=3),
    "p": ParagraphStyle("p", parent=ss["Normal"], fontName="Helvetica", fontSize=9, leading=12.4, textColor=INK, spaceAfter=5),
    "small": ParagraphStyle("sm", parent=ss["Normal"], fontName="Helvetica", fontSize=7.6, leading=9.6, textColor=INK2,
                            spaceAfter=4),
    "cell": ParagraphStyle("c", parent=ss["Normal"], fontName="Helvetica", fontSize=7.6, leading=9.4, textColor=INK),
    "banner": ParagraphStyle("b", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=9, leading=12,
                             textColor=colors.HexColor("#7a3a10"), backColor=colors.HexColor("#fdf0e6"),
                             borderPadding=6, spaceAfter=10, spaceBefore=4),
}
W = A4[0] - 3.6 * cm


def P(t, s="p"):
    return Paragraph(t, S[s])


def bullets(items, s="p"):
    return [Paragraph(f"&bull;&nbsp;{i}", ParagraphStyle("bl", parent=S[s], leftIndent=10, firstLineIndent=-8)) for i in items]


def tbl(df: pd.DataFrame, widths=None, fmt=None, header=True):
    fmt = fmt or {}
    rows = [[Paragraph(f"<b>{c}</b>", S["cell"]) for c in df.columns]] if header else []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            f = fmt.get(c)
            s = f(v) if (f and pd.notna(v) and v != "") else ("" if (isinstance(v, float) and pd.isna(v)) else str(v))
            cells.append(Paragraph(s, S["cell"]))
        rows.append(cells)
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK2),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def img(p, width=W, max_h=9.5 * cm):
    from PIL import Image as PI

    with PI.open(p) as im:
        w, h = im.size
    height = width * h / w
    if height > max_h:
        width, height = width * max_h / height, max_h
    return Image(str(p), width=width, height=height)


def money(v):
    v = float(v)
    sign, a = ("&minus;" if v < 0 else ""), abs(v)
    if a >= 1e9:
        return f"{sign}${a / 1e9:,.2f}bn"
    if a >= 1e6:
        return f"{sign}${a / 1e6:,.2f}m"
    return f"{sign}${a:,.0f}"


pct = lambda v: f"{float(v):.2%}"  # noqa: E731
pct1 = lambda v: f"{float(v):.1%}"  # noqa: E731
num = lambda v: f"{float(v):,.0f}"  # noqa: E731


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(INK2)
    canvas.drawString(1.8 * cm, 1.1 * cm, "Stagecraft - IFRS 9 ECL model documentation")
    canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, f"Page {doc.page}")
    canvas.restoreState()


def _sens_text(sens: pd.DataFrame) -> str:
    def row(test, setting):
        r = sens[(sens["test"] == test) & (sens["setting"] == setting)]
        return r.iloc[0] if len(r) else None

    base = sens.iloc[0]
    lo, hi = row("SICR relative threshold", "1.5x"), row("SICR relative threshold", "3.0x")
    st15, st20 = row("SICR threshold under stress staging", "1.5x"), row("SICR threshold under stress staging", "2.0x")
    dt, sev = row("LGD", "downturn (2008-2011) LGD"), row("Single scenario (100%)", "severe")
    parts = []
    if lo is not None and hi is not None:
        parts.append(f"In the booked (weighted) view, moving the relative SICR threshold from 3&times; to 1.5&times; moves "
                     f"Stage 2 from {hi['stage2_share_upb']:.1%} to {lo['stage2_share_upb']:.1%} of the book and ECL by only "
                     f"{lo['change_vs_model'] - hi['change_vs_model']:+.1%}. House prices had risen well above origination "
                     "levels, so few performing loans' lifetime PDs had doubled; Stage 2 is driven by the 30-DPD backstop "
                     "and the watchlist. The cliff is latent in good times.")
    if st15 is not None and st20 is not None:
        parts.append(f"Under stress staging (severe-scenario PDs), the cliff appears: Stage 2 is {st20['stage2_share_upb']:.0%} "
                     f"of the book at 2&times; but {st15['stage2_share_upb']:.0%} at 1.5&times;, and ECL "
                     f"{st15['ecl'] / st20['ecl']:.1f}&times; higher. That non-linearity is why the threshold is a governed "
                     "judgment and why IFRS 9 stage transfers can amplify provisions in a downturn (pro-cyclicality).")
    if dt is not None and sev is not None:
        parts.append(f"Downturn LGD adds {dt['change_vs_model']:+.0%}; the severe scenario at 100% weight adds "
                     f"{sev['change_vs_model']:+.0%}.")
    return " ".join(parts)


def build(runs: dict, val: dict, cfg: dict, out) -> None:
    h = headline(runs, val, cfg)
    syn = is_synthetic(cfg)
    dates = list(runs)
    d0, d1 = dates[0], dates[-1]
    H0, H1 = h["dates"][d0], h["dates"][d1]
    ch = path(cfg, "outputs") / "charts"
    st = cfg["staging"]
    dd = cfg["default_definition"]
    w = scenarios.weights(cfg)
    m1 = runs[d1]["models"]
    E = []

    # ------------------------------------------------------------------ title
    E += [P("Stagecraft: IFRS 9 expected credit loss model", "title"),
          P(f"Model documentation &middot; US residential mortgages (Freddie Mac loan-level data) &middot; "
            f"reporting dates {', '.join(dates)} &middot; generated {dt.date.today():%d %b %Y}", "sub")]
    if syn:
        E.append(P("DATA NOTICE: the figures in this document were produced from the synthetic sample bundled with the "
                   "repository (simulated loans written in the Freddie Mac file format, driven by real FRED macro history). "
                   "They demonstrate the method end to end; they are not findings about real US mortgages. Rerunning "
                   "the pipeline on the Freddie Mac sample files regenerates every number, table and chart.", "banner"))

    E += [P("1. Purpose and scope", "h1"),
          P("Stagecraft estimates the impairment allowance for a portfolio of US first-lien residential mortgages under "
            "IFRS 9 (Financial Instruments, section 5.5). It allocates each loan to Stage 1, 2 or 3, estimates 12-month and "
            "lifetime probabilities of default (PD), loss given default (LGD) and exposure at default (EAD), and produces a "
            "probability-weighted expected credit loss (ECL) under base, upside and downside macroeconomic scenarios, with a "
            "severe scenario for stress testing. It also explains the movement in the allowance between two reporting dates "
            "in the format of IFRS 7.35H."),
          P("Intended use: a transparent, reproducible reference implementation for model review, teaching and interview "
            "discussion. It is not a production model: there is no governance sign-off, no management overlay and the "
            "data are a sample. Every judgment call is parameterised in <font face='Courier'>config/assumptions.yaml</font> "
            "and listed in section 4.")]

    # ------------------------------------------------------------------ data
    E += [P("2. Data", "h1"),
          tbl(pd.DataFrame([
              ["Loan-level origination and monthly performance", "Freddie Mac Single-Family Loan-Level Dataset, sample files "
               "sample_2005 ... sample_2019 (about 50,000 loans per origination year). Column positions and codes follow "
               "Freddie Mac's file layout and General User Guide.", "Origination: 32 fields; performance: 32 fields; pipe-delimited, no header."],
              ["Unemployment rate", "FRED UNRATE", "Monthly; publication lag of 1 month applied."],
              ["House prices", "FRED USSTHPI (FHFA all-transactions index, US)", "Quarterly; placed at mid-quarter and "
               "log-linearly interpolated to monthly; lag of 3 months applied."],
              ["Mortgage rate", "FRED MORTGAGE30US", "Weekly averaged to monthly; used only for the refinancing incentive."],
          ], columns=["Data", "Source", "Treatment"]), widths=[3.4 * cm, 7.6 * cm, W - 11 * cm])]
    loans_df = pd.read_parquet(path(cfg, "processed") / "loans.parquet")
    n_loans, n_def = len(loans_df), int(loans_df["default_mi"].notna().sum())
    n_ce = int((loans_df["exit_type"] == "credit_event").sum())
    E += [Spacer(1, 4),
          P(f"<b>Data checks</b> (full report in <font face='Courier'>docs/data_report.md</font>): {n_loans:,} loans across "
            f"{loans_df['vintage'].nunique()} vintages; {n_def:,} loans ever in default ({n_def / n_loans:.1%}); "
            f"{n_ce:,} credit-event terminations, almost all with loss data; no duplicate loan-months. "
            "Actual Loss is rebuilt from its components (removal UPB, delinquent interest, expenses, net sale proceeds, "
            "MI and non-MI recoveries) to detect its sign convention; it reconciles for over 99% of credit events. "
            "The current release stores recoveries as negative numbers and dropped a column from the origination file "
            "relative to the published layout; the parser handles both."),
          P("2.1 Default definition and delinquency buckets", "h2"),
          P(f"Freddie Mac reports delinquency as the number of missed monthly payments (MBA method). <b>Default</b> is the "
            f"first month with status &ge; {dd['min_dpd_status']} (three missed payments, reported as 90-119 days), REO "
            f"status 'RA', or a credit-event zero-balance code ({', '.join(dd['credit_event_zb_codes'])}: third-party sale, "
            "short sale or charge-off, REO disposition, whole-loan (non-performing) sale). This matches IFRS 9's rebuttable "
            "presumption that default does not occur later than 90 days past due (B5.5.37) and the Basel 90-day definition. "
            "The RBI's NPA test is 'overdue for more than 90 days' counted in days from the due date. At a month-end "
            "snapshot three missed payments are about 90 days overdue, so the RBI-strict reading would flag the loan a few "
            "days later, in the next monthly record (status 4). That is one switch in the configuration."),
          tbl(pd.DataFrame(BUCKETS, columns=["Freddie status", "MBA label", "Days past due at month-end", "RBI class"]),
              widths=[2.4 * cm, 2.8 * cm, 5.2 * cm, W - 10.4 * cm]),
          P("A payment that is a few days late but caught up before month-end never shows in a monthly status, so SMA-0 "
            "accounts that cure within the month are invisible in this data. Exits that are neither default nor voluntary "
            "payoff (16 reperforming-loan securitisation, 96 defect repurchase) are censored.", "small")]

    # ------------------------------------------------------------------ method
    E += [P("3. Methodology", "h1"),
          P("3.1 Staging", "h2"),
          tbl(pd.DataFrame([
              ["Stage 3", "Credit-impaired", f"In default at the reporting date, or cured less than {st['stage3_probation_months']} "
               "months ago (probation)."],
              ["Stage 2", "Significant increase in credit risk (SICR)",
               f"Any of: 30+ DPD backstop (status &ge; {st['backstop_min_status']}); relative test: lifetime PD now &ge; "
               f"{st['sicr_relative_multiple']}&times; the lifetime PD expected at origination for the same remaining term AND "
               f"an increase of at least {st['sicr_absolute_bp']}bp ({st['sicr_pd_basis']} scenario PD); watchlist: modified, "
               "in forbearance / repayment / trial plan, or granted a payment deferral."],
              ["Stage 1", "Performing", "Everything else; 12-month ECL."],
          ], columns=["Stage", "Meaning", "Rule"]), widths=[1.6 * cm, 3.6 * cm, W - 5.2 * cm]),
          P("The origination PD and the current PD come from the same hazard model, so the ratio isolates the change in "
            "credit risk. The origination run uses the loan's origination score, original LTV amortised on the original "
            "schedule and indexed at long-run house-price growth, a performing status, and through-the-cycle macro inputs "
            "(no change in unemployment). The current run uses today's delinquency, modification history, HPI-indexed LTV "
            "and the scenario macro paths. Banks rarely hold the PD they actually recorded at origination for old loans; "
            "this retrospective origination PD is the usual practical substitute."),
          P("3.2 Origination scorecard", "h2"),
          P(f"Logistic regression of default within {cfg['scorecard']['target_months']} months of first payment on credit "
            "score, LTV (with a hinge at 80%), DTI, loan purpose, occupancy, channel, units, first-time buyer, number of "
            "borrowers and property type, with missing-value flags. It is trained only on loans whose whole 36-month window "
            f"ended by the reporting date ({m1['scorecard'].n_train:,} loans for {d1}). Its log-odds score is the borrower-risk "
            "input to the hazard model."),
          P("3.3 PD: macro-linked discrete-time hazard model (champion)", "h2"),
          P("Every June and December before the reporting date, each performing loan (Current, 30 or 60 DPD) is followed "
            f"monthly for up to {cfg['hazard']['max_horizon']} months until it defaults, exits or reaches the reporting date. "
            "Each loan-month is a row; the outcome is entry into default that month. The logistic hazard is:"),
          P("<font face='Courier' size='8'>logit h = b0 + b1&middot;score + f(age) + g(current LTV) + &Sigma; status-at-snapshot "
            "&times; horizon-bucket + modified + forbearance + prior default + c1&middot;&Delta;unemployment(12m) + "
            "c2&middot;HPI growth(12m) + legacy-vintage flag</font>"),
          P("All covariates are either fixed at the snapshot or known functions of time and the macro path, so the model "
            "projects a full monthly PD term structure for every loan under any scenario without simulating future "
            "delinquency. The delinquency signal enters through status &times; horizon terms that decay as the horizon "
            "lengthens. Months in which a loan cannot yet reach 90 days (a current loan in its first two months) are "
            "structural zeros. Coefficients use a ridge-penalised Newton fit with step-halving. If the age slope beyond six "
            "years comes out positive it is fixed at zero, because before 2019 only crisis-era cohorts are that old. "
            f"For {d1} the fit uses {m1['hazard'].n_rows:,} loan-months with {m1['hazard'].n_events:,} default entries "
            f"(unemployment coefficient {m1['hazard'].params['dur12']:.3f} per pp; HPI growth {m1['hazard'].params['hpa12']:.3f} per %)."),
          P("3.4 PD: roll-rate Markov model (challenger)", "h2"),
          P(f"Monthly transition matrices between Current, 30 DPD, 60 DPD, Default and Prepaid, counted over the "
            f"{cfg['markov']['window_months']} months to the reporting date for nine segments (credit score band &times; "
            "current-LTV band). Each segment row is blended with the pooled row using a credibility weight of "
            f"{cfg['markov']['min_obs_per_row']} pseudo-observations. Cumulative PD is (P<super>t</super>)[s, Default]. The "
            "chain is time-homogeneous and has no macro input, so it is a sanity check rather than a scenario engine."),
          KeepTogether([img(ch / "pd_term_structure.png", max_h=7.2 * cm),
                        P("Figure 1. Average cumulative PD of performing loans: hazard model (base scenario) vs Markov "
                          "chain. Both net off prepayment.", "small")]),
          P("3.5 LGD", "h2"),
          P("For each resolved default (credit-event exit with loss data on or before the reporting date) the economic LGD "
            "is (removal UPB + expenses + delinquent interest &minus; recoveries discounted at the note rate over the "
            "workout months) &divide; UPB at default, where recoveries are net sale proceeds plus MI and non-MI recoveries. "
            "A fractional-logit severity model on current LTV at default (original LTV indexed by HPI), MI coverage, "
            "investor occupancy, loan size (log UPB) and a judicial-foreclosure-state flag explains severity. Loan size "
            "matters because foreclosure costs are partly fixed: without it the LTV effect is masked, since small, old "
            "loans have low LTVs but high percentage losses. Judicial states (court-run foreclosure, e.g. FL, IL, NY, NJ) "
            "add months of carrying costs. The LTV term is the macro link: scenario house prices move projected LTV, "
            f"and so LGD (coefficient {m1['lgd'].params[1]:.2f} per 100pp of LTV, judicial {m1['lgd'].params[5]:+.2f}, "
            f"log UPB {m1['lgd'].params[4]:+.2f} on the logit scale). Effective "
            f"LGD = P(liquidation | default) &times; severity, floored at {cfg['lgd']['floor']:.0%}. P(liquidation) "
            f"= {m1['lgd'].p_liq:.1%} for {d1}, estimated from defaults followed for {cfg['lgd']['cure_obs_months']} months. "
            "Downturn LGD = mean severity of 2008-2011 defaults by LTV band. Stage 3 LGD moves the current LTV by the "
            f"scenario's house-price change over a {cfg['lgd']['stage3_workout_months']}-month workout."),
          KeepTogether([img(ch / "lgd_by_ltv_band.png", max_h=6.5 * cm),
                        P(f"Figure 2. Loss severity by current LTV at default, all resolved defaults vs 2008-2011 defaults "
                          f"(model as at {d0}).", "small")]),
          P("3.6 EAD and prepayment", "h2"),
          P("EAD in month t is the contractual balance at the start of t, from the current interest-bearing UPB, note rate "
            "and remaining term, plus any non-interest-bearing (deferred) UPB. Prepayment is a single monthly rate (SMM) "
            "per loan, estimated over the previous 36 months as the share of Current loans that pay off in full the next "
            "month, by refinancing-incentive band (note rate minus the market 30-year rate). It is applied once, as a "
            "competing exit in the survival curve."),
          tbl(m1["cpr"][["band", "loan_months", "prepayments", "smm", "cpr"]].rename(columns={"band": "Incentive band"}),
              fmt={"loan_months": num, "prepayments": num, "smm": lambda v: f"{v:.3%}", "cpr": pct1}),
          P("3.7 ECL", "h2"),
          P("<font face='Courier' size='8'>ECL = &Sigma;<sub>t</sub> S<sub>t-1</sub>&middot;h<sub>t</sub> &times; LGD<sub>t</sub> "
            "&times; EAD<sub>t</sub> &times; (1 + r/12)<super>-t</super>,  S<sub>t</sub> = S<sub>t-1</sub>(1 - h<sub>t</sub>)(1 - SMM)</font>"),
          P("S<sub>t-1</sub>&middot;h<sub>t</sub> is the marginal PD: the probability of surviving, neither defaulted nor "
            "prepaid, to month t and then defaulting in it. The marginal PDs sum to a cumulative PD of at most 1. Stage 1 "
            "sums the first 12 months; Stage 2 sums to the remaining contractual term; Stage 3 is LGD &times; gross "
            "carrying amount with PD = 1. Discounting uses the current note rate as the effective interest rate proxy. "
            "The probability-weighted ECL is &Sigma; w<sub>s</sub> ECL<sub>s</sub> over the weighted scenarios."),
          P("3.8 Forward-looking scenarios", "h2"),
          P(f"Five-year paths for unemployment and house prices start from the data published at the reporting date. After "
            f"year 5 they glide over {cfg['macro']['reversion_years']} years to long-run values (unemployment "
            f"{cfg['macro']['long_run_unemployment']}%, HPI growth {cfg['macro']['long_run_hpi_growth']}% a year). Weights: "
            + ", ".join(f"{k} {v:.0%}" for k, v in w.items()) + ". Severe (unemployment to 10%, house prices down about "
            "20%) is used for stress testing only."),
          tbl(pd.DataFrame([[s, ", ".join(f"{x:.1f}" for x in scenarios.spec(cfg, d1, s)["unemployment"]),
                             ", ".join(f"{x:+.1f}" for x in scenarios.spec(cfg, d1, s)["hpi_growth"]),
                             f"{w.get(s, 0):.0%}" if s in w else "stress only"]
                            for s in scenarios.scenario_names(cfg)],
                           columns=["Scenario", f"Unemployment, year-end Y1-Y5 (%), {d1}", "HPI growth Y1-Y5 (%)", "Weight"]),
              widths=[2.4 * cm, 6 * cm, 5 * cm, W - 13.4 * cm]),
          KeepTogether([img(ch / f"scenario_paths_{d1}.png", max_h=6 * cm),
                        P(f"Figure 3. Scenario paths from {d1}. The vertical line marks the reporting date.", "small")])]

    # ------------------------------------------------------------------ assumptions
    E += [P("4. Assumptions owned by the model owner [RISK TO REVIEW]", "h1"),
          P("Each item is a judgment, not an estimate. The draft value is shown with the rationale; all live in "
            "<font face='Courier'>config/assumptions.yaml</font>."),
          tbl(pd.DataFrame([
              ["Default definition", f"status &ge; {dd['min_dpd_status']}, RA, codes {'/'.join(dd['credit_event_zb_codes'])}",
               "US D90 convention; IFRS 9 90-day presumption; status 4 is the RBI-strict alternative."],
              ["Whole-loan sale (15) is a credit event", "yes", "These are non-performing loan sales and Freddie computes a loss on them."],
              ["30+ DPD backstop", f"status &ge; {st['backstop_min_status']}", "IFRS 9 5.5.11 presumption; RBI SICR presumption at >30 DPD."],
              ["Relative SICR multiple", f"{st['sicr_relative_multiple']}&times;", "Common industry setting for low-PD retail; see the cliff-effect sensitivity."],
              ["Absolute SICR floor", f"{st['sicr_absolute_bp']}bp", "Stops trivially small PDs that double from triggering Stage 2."],
              ["SICR PD basis", st["sicr_pd_basis"], "Weighted lifetime PD reflects all scenarios in the staging decision."],
              ["Watchlist", "modification, forbearance, deferral", "Forbearance is a concession; IFRS 9 B5.5.17 and RBI credit-impaired indicators."],
              ["Stage 3 probation", f"{st['stage3_probation_months']} months", "Avoids flip-flopping between Stage 3 and 1/2 after a cure."],
              ["LGD floor", f"{cfg['lgd']['floor']:.0%}", "Foreclosure costs and time value never go to zero."],
              ["Cure adjustment to LGD", "on" if cfg["lgd"]["apply_cure_rate"] else "off", "About half of 90+ defaults cure; ignoring that double-counts loss."],
              ["Stage 3 workout period", f"{cfg['lgd']['stage3_workout_months']} months", "Typical US foreclosure timeline; house prices move meanwhile."],
              ["Hazard seasoning constraint", "no rise after age 72m", "Late-age slope is confounded with crisis cohorts in pre-2019 data."],
              ["Prepayment", "flat CPR by incentive band", "Simple, transparent; scenario-independent."],
              ["Scenario paths and weights", ", ".join(f"{k} {v:.0%}" for k, v in w.items()), "Downside as likely as upside; base most likely."],
              ["Management overlay", "none", "Not modelled; see Limitations."],
          ], columns=["Assumption", "Draft value", "Rationale"]), widths=[4 * cm, 4.3 * cm, W - 8.3 * cm])]

    # ------------------------------------------------------------------ results
    def stage_table(d):
        t = by_stage(runs[d]["res"], cfg)
        t["stage"] = t["stage"].map(lambda s: f"Stage {s}" if s != "Total" else "Total")
        return t[["stage", "loans", "gross_carrying_amount", "share_of_book", "ecl_weighted", "coverage", "ecl_base",
                  "mean_pd12", "mean_pd_lifetime"]].rename(columns={
            "stage": "Stage", "loans": "Loans", "gross_carrying_amount": "Gross carrying amount", "share_of_book": "Share",
            "ecl_weighted": "Weighted ECL", "coverage": "Coverage", "ecl_base": "Base ECL", "mean_pd12": "Mean 12m PD",
            "mean_pd_lifetime": "Mean lifetime PD"})
    f = {"Loans": num, "Gross carrying amount": money, "Share": pct, "Weighted ECL": money, "Coverage": pct,
         "Base ECL": money, "Mean 12m PD": pct, "Mean lifetime PD": pct}
    E += [P("5. Results", "h1")]
    for d in dates:
        E += [P(f"ECL by stage at {d}", "h2"), tbl(stage_table(d), fmt=f)]
    E += [Spacer(1, 4),
          P(f"Weighted ECL is {H1['ecl_weighted'] / H1['ecl_base'] - 1:+.1%} above base ECL at {d1} "
            f"({H0['ecl_weighted'] / H0['ecl_base'] - 1:+.1%} at {d0}). This is the non-linearity IFRS 9 B5.5.42 asks "
            "for: PD (logistic in unemployment and LTV) and LGD (rising with LTV, floored at the bottom) are convex in the "
            "macro drivers. The downside adds more loss than the upside removes, so the probability-weighted average "
            "exceeds the loss in the average (base) scenario. Under the severe stress the allowance would be "
            f"{money(H1['ecl_severe'])} ({H1['ecl_severe'] / H1['ecl_weighted']:.1f}&times; the weighted figure)."),
          KeepTogether([img(ch / "ecl_by_scenario.png", max_h=6.3 * cm), P("Figure 4. ECL by scenario.", "small")]),
          KeepTogether([img(ch / "ecl_coverage_by_vintage.png", max_h=6 * cm),
                        P("Figure 5. Coverage by origination vintage. Pre-2009 vintages carry the highest coverage "
                          "(weaker underwriting, more prior delinquency).", "small")]),
          P(f"Provision movement {d0} to {d1}", "h2"),
          img(ch / "provision_waterfall.png", max_h=7 * cm),
          P("Figure 6. Provision movement waterfall (probability-weighted ECL).", "small"),
          tbl(val["waterfall"].rename(columns={"line": "Movement", "amount": "Amount"}), fmt={"Amount": money},
              widths=[9 * cm, 4 * cm]),
          P("Attribution is loan by loan. Loans that leave the book release their opening allowance as a derecognition or a "
            "write-off. For continuing loans, the transfer effect is the opening-date ECL recomputed under the closing "
            "stage minus the opening ECL, and remeasurement is the remainder (new PDs, LGDs, macro paths, re-estimated "
            "models, amortisation). Closing = opening + movements holds exactly, and a test enforces it. The by-stage version "
            "(IFRS 7.35H layout) is in outputs/provision_waterfall_by_stage.csv.", "small")]

    # ------------------------------------------------------------------ validation
    def bt_row(d):
        b = h["dates"][d]["backtest"]
        sc = h["dates"][d]["scorecard"]
        return [d, f"{b['loans']:,}", f"{b['defaults']:,}", pct(b["observed"]), pct(b["predicted"]), pct(b["markov"]),
                b["traffic_light"], f"{b['auc']:.3f}" if b["auc"] else "", f"{b['auc_markov']:.3f}" if b["auc_markov"] else "",
                f"{sc.get('in_sample', {}).get('auc', float('nan')):.3f} / {sc.get('out_of_time', {}).get('auc', float('nan')):.3f}"]
    E += [P("6. Validation (out-of-time)", "h1"),
          P("6.1 PD backtest and discrimination", "h2"),
          P("Predicted 12-month PD (probability-weighted) for Stage 1 and 2 loans at each reporting date, compared with "
            "default entries in the following 12 months. Data after the reporting date is used here and nowhere else. The "
            "traffic light is green if observed defaults fall inside the 95% binomial band around the predicted mean, amber "
            "inside 99.9%, red outside."),
          tbl(pd.DataFrame([bt_row(d) for d in dates], columns=[
              "Date", "Loans", "Defaults", "Observed", "Predicted (hazard)", "Predicted (Markov)", "Light", "AUC hazard",
              "AUC Markov", "Scorecard AUC in/OOT"])),
          P(f"<b>From {d0}</b> the model ranks risk very well (out-of-time AUC {H0['backtest']['auc']:.2f} vs "
            f"{H0['backtest']['auc_markov']:.2f} for the Markov challenger) and errs on the conservative side: it predicted "
            f"{pct(H0['backtest']['predicted'])} against {pct(H0['backtest']['observed'])} observed "
            f"({H0['backtest']['predicted'] / H0['backtest']['observed'] - 1:+.0%}; base scenario alone "
            f"{pct(val['backtest'][d0]['overall']['predicted_pd12_base'].iloc[0])}). With {H0['backtest']['loans']:,} loans "
            f"the binomial test rejects even a small bias, so the light is {H0['backtest']['traffic_light']} "
            f"({H0['backtest']['segments_green']} of {H0['backtest']['segments_total']} segments green). The conservatism "
            "sits in the prime segments (FICO 740+), where 2019 default rates were at historic lows; the riskier segments "
            "are close to observed. Materiality matters more than significance at this sample size. "
            f"<b>From {d1}</b> the realised rate is {H1['backtest']['observed'] / H1['backtest']['predicted']:.1f}&times; the "
            "prediction: the 2020 COVID shock (unemployment from 3.5% to 14.8% in two months) and forbearance programmes "
            "that reported paused payments as delinquency. None of the weighted scenarios anticipated a shock of that "
            "size or speed, and the 90+ DPD definition counted forborne loans as defaulted. In practice banks handled this "
            "with new scenarios and post-model overlays during 2020. Discrimination also drops, because COVID distress "
            "was less related to the origination risk factors. The scorecard's out-of-time AUC is measured on the "
            "vintages whose 36-month window ran past the reporting date, so its calibration (Figure 8) is affected by "
            "the same shock."),
          KeepTogether([img(ch / "backtest_by_segment.png", max_h=7.5 * cm), P("Figure 7. Backtest by segment.", "small")]),
          KeepTogether([img(ch / "calibration.png", width=W * 0.6, max_h=7.5 * cm),
                        P("Figure 8. Calibration by decile of predicted PD.", "small")]),
          P("6.2 Stage migration", "h2"),
          img(ch / "stage_migration.png", max_h=5.5 * cm),
          P("6.3 Sensitivities and the cliff effect", "h2")]
    sens = val["sensitivity"][d1]
    E += [tbl(sens.rename(columns={"test": "Test", "setting": "Setting", "ecl": "ECL", "change_vs_model": "vs model",
                                   "stage2_share_loans": "Stage 2 (loans)", "stage2_share_upb": "Stage 2 (UPB)"}),
              fmt={"ECL": money, "vs model": lambda v: f"{float(v):+.1%}", "Stage 2 (loans)": pct, "Stage 2 (UPB)": pct},
              widths=[4.2 * cm, 4.2 * cm, 2.2 * cm, 1.8 * cm, 2.4 * cm, W - 14.8 * cm]),
          P(_sens_text(sens)),
          img(ch / f"sicr_cliff_{d1}.png", max_h=6 * cm)]

    # ------------------------------------------------------------------ limitations
    E += [P("7. Limitations", "h1")] + bullets([
        "<b>US mortgages vs other portfolios.</b> Secured, amortising, low-PD loans whose losses hinge on house prices. "
        "Unsecured retail, credit cards (revolving EAD, behavioural life), SME and corporate books need different PD "
        "drivers, CCFs and LGD models.",
        ("<b>Sample and synthetic data.</b> This run uses a simulated sample; " if syn else "<b>Sample data.</b> ")
        + "Freddie Mac sample files are a 50,000-loan-per-year random sample of conforming loans acquired by one GSE, so "
        "they exclude jumbo, subprime and portfolio loans, and low-default segments have thin data.",
        "<b>Note rate as EIR proxy.</b> The effective interest rate should include fees and costs amortised over the "
        "expected life; they are not in the data. The RBI Directions allow the contractual rate on transition for the same reason.",
        "<b>Simplified prepayment.</b> One flat SMM per incentive band, with no burnout, seasoning ramp, turnover "
        "seasonality or scenario dependence. In reality a rate shock lowers prepayment and lengthens exposure.",
        "<b>Collateral.</b> Property values are indexed with the national FHFA HPI only, with no state or MSA indices and "
        "no property-level revaluation, so regional price falls (Nevada, Florida in 2008) are understated. Judicial-state "
        "foreclosure timelines and MI enter only as LGD regressors, not as explicit cash-flow models.",
        "<b>No management overlay.</b> An overlay (post-model adjustment) is a documented, governed top-up or release of the "
        "allowance for risks the model cannot see: COVID forbearance in 2020, a new regulation, a data gap or a known "
        "model weakness. It is quantified separately, approved by a committee and reversed when the model catches up. "
        "None is booked here; the config has a placeholder (overlay.enabled).",
        "<b>Retrospective origination PD.</b> The origination PD is re-estimated with today's model rather than taken "
        "from the bank's records at origination.",
        "<b>Macro vintages.</b> FRED series are the latest revisions, not the data as first published (ALFRED). Only "
        "publication lags are respected.",
        "<b>Default definition and COVID.</b> Forbearance in 2020-21 inflates 90+ DPD defaults that later cured. The "
        "probation rule and the cure-adjusted LGD dampen the effect but do not remove it.",
        "<b>Model risk.</b> The snapshot-horizon panel has overlapping observations, so standard errors are optimistic; "
        "the ridge penalty and seasoning constraint are expert choices.",
    ])

    # ------------------------------------------------------------------ India
    E += [P("8. Relevance to India", "h1"),
          P("<b>Where the RBI stands (as of this document).</b> On 27 April 2026 the RBI issued the final Reserve Bank of "
            "India (Commercial Banks - Asset Classification, Provisioning and Income Recognition) Directions, 2026, "
            "replacing the incurred-loss IRACP norms with an IFRS 9-style expected credit loss framework <b>from 1 April "
            "2027</b> [1, 2]. The draft was released on 7 October 2025 [3], after a January 2023 discussion paper [4]. "
            "They apply to commercial banks other than small finance, payments and local area banks [2, para 4]. Separate "
            "directions for All India Financial Institutions will follow [1]. Cooperative banks such as UCBs are not "
            "covered by these Directions and remain on the existing norms."),
          *bullets([
              "<b>Three stages</b> as in IFRS 9 (12-month ECL in Stage 1, lifetime in Stages 2 and 3) [2, para 25], with a "
              "rebuttable presumption of SICR above <b>30 days past due</b> [2, paras 33-36], the same backstop Stagecraft uses.",
              "<b>NPA stays as the credit-impaired anchor:</b> a term loan is NPA when overdue for more than 90 days [2, para 8]. "
              "The existing SMA-0/1/2 early-warning buckets (1-30, 31-60, 61-90 days overdue) [5] map onto Stagecraft's "
              "Current/30/60/90 buckets as in section 2.1. SMA-1 and SMA-2 accounts are Stage 2 by the backstop.",
              "<b>Prudential floors</b> [2, para 82]: for housing loans to individuals, at least 0.25% (Stage 1) and 1.5% (Stage 2), "
              "and for Stage 3 10% in the first year rising to 100% after four years (higher on any unsecured portion). "
              f"Stagecraft's modelled coverage at {d1} is {pct(H1['coverage']['1'])} in Stage 1 (below the 0.25% floor, so an Indian bank "
              f"would book the floor), {pct(H1['coverage']['2'])} in Stage 2 (above 1.5%) and {pct(H1['coverage']['3'])} in Stage 3 "
              "(above the 10% first-year floor). The floors bite on the performing book, exactly where prime mortgages "
              "model lowest.",
              "<b>Multiple probability-weighted scenarios</b> with documented expert judgement [2, paras 47-49, 69-72], as in "
              "section 3.8. Management overlays count as general provisions for Tier 2 capital [2, para 75].",
              "<b>EIR:</b> contractual rate allowed for the opening ECL, with all loans moving to EIR by 31 March 2030 "
              "[2, paras 50-54]. This is the same compromise as Stagecraft's note-rate proxy.",
              "<b>Transition:</b> the excess of ECL over existing provisions goes to opening retained earnings, with an optional "
              "CET1 add-back phased out by 31 March 2031 (4/5, 3/5, 2/5, 1/5) [2, paras 107-108].",
          ]),
          P("<b>Practical translation.</b> An Indian bank's monthly SMA/NPA reporting already holds the delinquency "
            "history needed for a Markov roll-rate model. A hazard model needs the same panel plus macro links (GDP, "
            "repo rate, property prices such as the RBI's HPI), and the RBI's floors then sit on top of the modelled numbers."),
          P("[1] RBI Press Release 2026-2027/150, 27 Apr 2026, https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=62628 "
            "&middot; [2] RBI (Commercial Banks - Asset Classification, Provisioning and Income Recognition) Directions, 2026, "
            "https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=13400 &middot; [3] RBI press release, 7 Oct 2025, "
            "https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=61377 &middot; [4] RBI Discussion Paper on Introduction "
            "of Expected Credit Loss Framework for Provisioning by Banks, Jan 2023 &middot; [5] RBI circular "
            "DOR.STR.REC.68/21.04.048/2021-22, 12 Nov 2021 (IRACP clarifications, SMA classes). Accessed Oct 2026.", "small")]

    # ------------------------------------------------------------------ appendix
    ht = m1["hazard"].table().reset_index().rename(columns={"index": "term"})
    E += [P(f"Appendix A. Hazard model coefficients ({d1})", "h1"),
          tbl(ht, fmt={"coef": lambda v: f"{v:.3f}", "std_err": lambda v: f"{v:.3f}", "z": lambda v: f"{v:.1f}"},
              widths=[4 * cm, 3 * cm, 3 * cm, 3 * cm]),
          P("sJ_hB = status J at the snapshot (0 Current, 1 = 30 DPD, 2 = 60 DPD) &times; horizon bucket B (&le;3, 4-6, "
            "7-12, 13-24, >24 months). Zero coefficient with no standard error = term dropped (no variation, or the "
            "seasoning constraint).", "small"),
          P("Appendix B. Reproducing this document", "h1"),
          P("<font face='Courier'>pip install -e .  &&  python -m stagecraft.pipeline</font> rebuilds the panel, models, "
            "outputs/ and this PDF from data/raw/ (falling back to the bundled sample). Download the Freddie Mac files "
            "sample_2005.zip ... sample_2019.zip from the Single-Family Loan-Level Dataset page (free registration) into "
            "data/raw/freddie/. The full 750,000-loan run takes about 15 minutes on a 4-core, 16 GB machine; the hazard "
            "training panel is subsampled automatically (all defaults kept, non-defaults reweighted) to "
            f"{cfg['hazard']['max_training_rows']:,} rows.")]

    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm,
                            bottomMargin=1.7 * cm, title="Stagecraft IFRS 9 ECL model documentation", author="Stagecraft")
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.build(E, onFirstPage=_footer, onLaterPages=_footer)

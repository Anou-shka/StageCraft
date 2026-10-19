# Project spec: Stagecraft — an IFRS 9 expected credit loss engine

Paste this whole file into Claude Code as the first message of the project, then save it in the repo as `SPEC.md`.

---

## 0. Who I am and how we work

I'm Anoushka, a CS + Business graduate (NTU) and CFA Level II candidate, targeting risk analytics roles at banks and NBFCs. I worked as a freelance risk-reporting analyst at an Indian cooperative bank, monitoring SMA-0/1/2 and NPA portfolios. My earlier project Credyte is a credit-card PD model (XGBoost, calibration, SHAP).

**The one-sentence pitch:** "Stagecraft is an IFRS 9 expected credit loss engine on 600,000+ real US mortgages: it stages loans, builds 12-month and lifetime PDs from delinquency roll rates and a macro-linked model, estimates LGD and EAD, and produces probability-weighted ECL under base, upside and downside scenarios — with a provision movement waterfall like a bank's annual report."

**Why mortgages with monthly history:** IFRS 9 staging needs to know how each loan's credit risk changed since origination. The Freddie Mac data has a monthly delinquency status for every loan, which maps directly onto the buckets I used at the bank: current, 1–30 days (SMA-0), 31–60 (SMA-1), 61–90 (SMA-2), 90+ (NPA / Stage 3).

**Working rules (follow these throughout):**

1. **Document every modelling choice** the way a bank's model documentation would: what, why, alternatives considered, limitations.
2. **I make the judgment calls:** default definition, SICR thresholds, scenario paths and weights, any overlay. Draft them as `[RISK TO REVIEW]` with a one-line rationale, and I'll confirm or change them.
3. **No look-ahead.** Anything estimated "as at" a reporting date may only use data up to that date. Validation uses later data.
4. **Teach as you go.** At the end of each milestone, add to `docs/milestone-notes.md`: what you built, the 3 most important choices, and 3 questions an interviewer could ask me.
5. Stop at the end of each milestone and wait for me to say "continue".

---

## 1. Deliverables

| # | Deliverable | Format |
|---|---|---|
| 1 | Python package for staging, PD, LGD, EAD, ECL, scenarios and validation | `src/stagecraft/` |
| 2 | ECL results at the reporting date: by stage, by vintage, by segment, by scenario | `outputs/` CSVs + charts |
| 3 | Provision movement waterfall between two reporting dates (IFRS 7 style) | Chart + table |
| 4 | Streamlit dashboard: change scenario weights, SICR threshold and macro paths, and watch ECL and stage mix update | `app/` |
| 5 | Model documentation report (8–12 pages, PDF): purpose, data, methodology, assumptions, results, validation, limitations | `report/model_documentation.pdf` |
| 6 | README, website case study, interview defence sheet | `README.md`, `docs/case-study.md`, `docs/defence.md` |

---

## 2. Data

| Data | Source | Notes |
|---|---|---|
| Loan-level origination + monthly performance | **Freddie Mac Single-Family Loan-Level Dataset — sample files** (about 50,000 loans per origination year) | Free, needs registration, so **I'll download the files manually** into `data/raw/freddie/`. Tell me exactly which years and files you need. Read Freddie Mac's file layout / user guide for column definitions; don't assume them. |
| Unemployment rate | FRED `UNRATE` | Monthly |
| House prices | FRED `USSTHPI` (FHFA all-transactions HPI) | Quarterly; interpolate to monthly and document it |
| (Optional) GDP growth, mortgage rates | FRED | Only if they improve the macro model |

**Suggested scope:** origination years 2005–2019 sample files (covers the 2008 crisis, which we need for downturn LGD and the stress scenario). Reporting dates: **31 Dec 2018 and 31 Dec 2019** (two dates so we can build the movement waterfall). Use data after 2019 only for validation. Ask me before changing this.

**Data checks first:** row counts, missing values, the delinquency status codes present, how zero-balance codes (prepaid, sold, foreclosed, etc.) appear, and whether loss fields are populated. Write them to `docs/data_report.md` before modelling.

Network check first: test whether FRED is reachable; if not, tell me which series to download as CSVs.

---

## 3. Methodology

### 3.1 Default and buckets

- Delinquency buckets each month: **0 (current), 1–30, 31–60, 61–90, 90+**, plus absorbing states **default** and **prepaid/closed**.
- Default definition `[RISK TO REVIEW]`: 90+ days past due, or a zero-balance code indicating a credit event (foreclosure, short sale, REO, charge-off). Document how this aligns with the IFRS 9 rebuttable 90-day presumption and with the RBI NPA definition.
- Add a short mapping table in the report: these buckets ↔ Indian SMA-0 / SMA-1 / SMA-2 / NPA.

### 3.2 Staging at each reporting date

- **Stage 3:** in default (90+ DPD or credit event).
- **Stage 2 (significant increase in credit risk, SICR):** any of `[RISK TO REVIEW]`:
  - 30+ DPD backstop
  - relative test: current lifetime PD ≥ 2× the lifetime PD estimated at origination for the same remaining term, **and** absolute increase ≥ 50bp
  - (optional) a watchlist flag, e.g. a modification or forbearance indicator if present in the data
- **Stage 1:** everything else.
- The origination PD comes from a simple **origination scorecard** (logistic regression on credit score, LTV, DTI, loan purpose, occupancy, etc., trained only on data available before each reporting date).

### 3.3 PD

Build two approaches and compare them:

1. **Roll-rate (Markov) model:** estimate monthly transition matrices between buckets from history up to the reporting date, segmented by a small number of risk segments (e.g. credit-score band × LTV band). Raise them to powers to get cumulative PD curves; 12-month PD for Stage 1, lifetime PD over remaining term for Stage 2.
2. **Macro-linked hazard model:** a discrete-time logistic hazard model (loan-month level) with loan features, loan age, and macro variables (unemployment change, HPI change). This is how forward-looking scenarios enter PD.

Use the hazard model for scenario PDs, and the Markov model as a challenger and sanity check. Show both PD term structures on one chart.

### 3.4 LGD

- From defaulted loans with completed loss data: LGD = actual loss ÷ UPB at default, using the loss and recovery fields documented by Freddie Mac.
- Segment by current LTV band (original LTV indexed by HPI change since origination).
- **Downturn LGD:** LGD observed for defaults in 2008–2011.
- Macro link: LGD sensitivity to HPI change, used in scenarios.

### 3.5 EAD

- Amortising balance schedule from current UPB, note rate and remaining term.
- Apply a **prepayment (CPR) assumption** estimated from the data by segment, because prepaid loans can't default.

### 3.6 ECL

For each loan:

```
ECL = Σ_t  marginal PD_t × LGD_t × EAD_t × DF_t
```

- Stage 1: sum over the next 12 months; Stage 2: over the remaining lifetime; Stage 3: PD = 1, ECL = LGD × EAD.
- Discount at the loan's note rate (proxy for the effective interest rate).
- Marginal PDs must account for survival (no double counting of loans that already defaulted or prepaid).

### 3.7 Forward-looking scenarios

- Three macro paths over the next 5 years for unemployment and HPI: **Base, Upside, Downside** `[RISK TO REVIEW]`, plus a **Severe** stress (2008-like: unemployment to ~10%, HPI −20% or worse) for stress testing only.
- Probability weights `[RISK TO REVIEW]`, default 60 / 20 / 20.
- Report ECL per scenario, the weighted ECL, and show that **weighted ECL > base ECL** (non-linearity), explaining why.

### 3.8 Validation

- **PD backtest:** predicted 12-month PD vs realised 12-month default rate by segment and by vintage, using data after the reporting date (out-of-time).
- Discrimination (AUC / Gini) and calibration (predicted vs observed by decile) for the origination scorecard and hazard model.
- **Stage migration matrix** between the two reporting dates.
- **Sensitivity:** ECL change if the SICR relative threshold moves from 2× to 1.5× or 3× (the "cliff effect"), if scenario weights shift, and if LGD uses downturn values.
- **Provision movement waterfall** from 31 Dec 2018 to 31 Dec 2019: opening ECL → new originations → derecognitions (repaid / prepaid) → transfers between stages → remeasurement (PD/LGD changes) → write-offs → closing ECL.

---

## 4. Repo structure

```
stagecraft/
├── SPEC.md
├── README.md
├── data/raw/freddie/, data/raw/macro/, data/processed/
├── src/stagecraft/
│   ├── load.py           # parse Freddie Mac files, build loan-month panel
│   ├── buckets.py        # DPD buckets, default flag
│   ├── scorecard.py      # origination PD
│   ├── markov.py         # transition matrices, PD term structures
│   ├── hazard.py         # macro-linked hazard model
│   ├── lgd.py, ead.py
│   ├── staging.py
│   ├── ecl.py
│   ├── scenarios.py
│   ├── validation.py     # backtests, migration, sensitivity, waterfall
│   └── report.py         # charts + PDF
├── config/assumptions.yaml   # every [RISK TO REVIEW] parameter in one place
├── app/streamlit_app.py
├── report/
├── docs/data_report.md, milestone-notes.md, case-study.md, defence.md
└── tests/
```

Performance: the loan-month panel will be tens of millions of rows. Use Parquet and Polars or DuckDB, not row-by-row pandas loops.

---

## 5. Milestones

| Day | Milestone | Done when |
|---|---|---|
| Oct 30 | **M1. Data:** list of files for me to download, parser, loan-month panel in Parquet, data report | Data report reviewed by me |
| Oct 31 | **M2. Buckets, default, staging inputs:** DPD buckets, default flag, origination scorecard | Scorecard AUC reported; buckets map cleanly to SMA/NPA |
| Nov 1 | **M3. PD:** Markov transition matrices and hazard model, PD term structures | Both PD curves on one chart; reasonableness checks pass |
| Nov 2 | **M4. LGD + EAD + ECL:** LGD by segment incl. downturn, EAD with prepayment, loan-level ECL, staging at both reporting dates | ECL by stage table; Stage 3 coverage looks sensible |
| Nov 3 | **M5. Scenarios + validation:** macro paths, weighted ECL, stress, backtests, migration matrix, sensitivities, waterfall | All charts in `outputs/` |
| Nov 4 | **M6. Dashboard:** Streamlit app with scenario, weight and SICR controls | Runs from a fresh clone on a small sample bundled in the repo |
| Nov 5 | **M7. Report + polish:** model documentation PDF, README, case study, defence sheet | One command rebuilds outputs from `data/raw/` |

The full Freddie Mac data can't go on GitHub. Ship a **small, anonymised sample** (a few thousand loans) so the app and tests run from a fresh clone, and document how to rebuild with the full data.

---

## 6. Quality bar

- Every parameter I need to own is in `config/assumptions.yaml`, with a comment explaining it.
- Tests cover: bucket assignment, default flag, transition matrix rows summing to 1, marginal PDs never negative and cumulative PD ≤ 1, ECL = 12-month for Stage 1 and lifetime for Stage 2, discounting, waterfall closing = opening + movements.
- README shows: the pitch, a flow diagram (data → buckets → staging → PD/LGD/EAD → scenarios → ECL), headline results (total ECL and coverage ratio by stage, weighted vs base ECL, stress ECL, backtest result), how to run it, limitations.
- `docs/defence.md` lists at least 25 likely interview questions grouped by topic (IFRS 9 concepts, SICR and staging, PD modelling, LGD/EAD, scenarios and weights, validation, data limitations, India/RBI relevance), with empty space under each for my answers. Don't write the answers.
- Limitations section covers at least: US mortgages vs other portfolios, sample data, note rate as EIR proxy, simplified prepayment, no collateral revaluation beyond HPI, no management overlay modelled (explain what an overlay is).
- Include a one-page **"Relevance to India"** note: how this maps to Indian banks' SMA/NPA classification and the RBI's move towards an ECL framework. **Research and cite the RBI's current ECL position; don't rely on memory.**

---

## 7. Start now

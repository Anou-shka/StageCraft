# Milestone notes

One entry per milestone: what was built, the three choices that matter most, and three questions an interviewer
could ask. The whole build was done in one pass (at your request), so every milestone is written up here. The
`[RISK TO REVIEW]` calls are drafts waiting for your sign-off; see section 4 of the PDF.

> Numbers quoted are from the real Freddie Mac run (750,000 loans). M1–M7 were first built and tested on a synthetic sample
> in the same file format; M8 records what changed when the real data arrived.

---

## M1. Data

**Built.** `load.py` parses Freddie Mac's 32-column origination and 32-column performance files, using names and
positions from Freddie's `file_layout.xlsx` and General User Guide (downloaded and read, not assumed). It handles zips,
the `9999`/`999` missing codes, `RA` (REO) status, zero-padded zero-balance codes and `U` net sale proceeds, and writes
typed Parquet by vintage via Polars streaming. `datacheck.py` writes `docs/data_report.md`: counts, missing values,
status codes, zero-balance codes, loss-field population and the Actual Loss sign. FRED is reachable, so UNRATE,
USSTHPI and MORTGAGE30US were downloaded. Freddie needs a login, so `synth.py` generates a 12,000-loan sample in the
exact file format, driven by real FRED history.

**Files you need:** `sample_2005.zip` … `sample_2019.zip` (15 files) → `data/raw/freddie/`.

**Three choices.**
1. *Parse to Parquet with Polars lazily, one file per vintage.* The full sample is about 40M loan-months, and pandas
   loops would not cope.
2. *Detect the loss sign from the data.* The guide's two formula statements are ambiguous about the sign, so the code
   rebuilds Actual Loss from its components both ways and keeps whichever matches.
3. *Ship synthetic data in the real format rather than a different schema.* The same parser runs on both, so nothing
   changes when the real files arrive.

**Interview questions.**
- What does a zero-balance code tell you, and which ones did you treat as default?
- Why can't you see a 1–29 days-past-due account in this data?
- How did you make sure the macro data you used was available at the reporting date?

---

## M2. Buckets, default, origination scorecard

**Built.** `buckets.py` assigns monthly states (Current / 30 / 60 / Default / Prepaid / Censored) and builds the
enriched panel: HPI-indexed current LTV, default entry, months since last default, modification, forbearance and
deferral flags. `scorecard.py` is a logistic regression of default within 36 months on origination data, trained only
on loans whose 36-month window closed by the reporting date. Real data: AUC 0.84 in-sample, 0.74 out-of-time
(the out-of-time window includes COVID).

**Three choices.**
1. *Default = 3 missed payments (status ≥ 3), REO, or codes 02/03/09/15* [RISK TO REVIEW]. This is the US D90
   convention and the IFRS 9 90-day presumption. RBI-strict would be status ≥ 4.
2. *The PD event is **entry** into default, not first-ever default.* A cured or modified loan can re-default, and its
   PD must measure that.
3. *The scorecard's log-odds feed the hazard model as one covariate.* Origination PD and current PD then come from the
   same model, so their ratio is a clean SICR measure.

**Interview questions.**
- Walk me through how a Freddie status maps to SMA-0/1/2 and NPA. Where does it break down?
- Why train the scorecard only on loans with a complete 36-month window?
- Should a whole-loan sale (code 15) count as a default? What would change if not?

---

## M3. PD models

**Built.** `hazard.py` is the champion: a discrete-time logistic hazard on a (snapshot × horizon) panel, with the
origination score, piecewise loan age, current-LTV hinges, status × horizon decay terms, modification / forbearance /
prior default, 12-month change in unemployment, 12-month HPI growth and a legacy-vintage flag. It is fitted by
ridge-penalised Newton with step-halving. `markov.py` is the challenger: monthly transition matrices by FICO × LTV
segment with credibility weighting, raised to powers. The two term structures sit within about a percentage point of
each other at 5 years (`outputs/charts/pd_term_structure.png`).

**Three choices.**
1. *Snapshot × horizon design.* Every covariate is known at the reporting date or follows from the scenario path, so
   lifetime PDs come out under any scenario without simulating delinquency.
2. *Structural zeros.* A Current loan cannot be 90+ DPD within two months, so those loan-months are excluded rather
   than producing a huge negative coefficient.
3. *Seasoning constraint* [RISK TO REVIEW]. Before 2019 the only loans older than six years are crisis cohorts, so a
   rising late-age hazard is confounded. The slope is capped at zero, alongside a legacy-vintage flag.

**Interview questions.**
- Why use two PD models? What do you do when they disagree?
- How does a 60-DPD loan's PD term structure differ from a current loan's in your model, and why?
- How do you stop a model trained on 2008 from overreacting in a benign year?

---

## M4. LGD, EAD, ECL, staging

**Built.** `lgd.py` computes economic workout LGD from Freddie's loss fields (recoveries discounted at the note rate).
A fractional-logit severity on current LTV, MI and investor occupancy provides the macro link. A cure rate converts
severity to effective LGD, and the 2008–11 downturn table is kept for sensitivity. `ead.py` does contractual
amortisation plus deferred UPB, and SMM by refinancing-incentive band. `ecl.py` is the survival-weighted ECL.
`staging.py` holds the stage rules. Coverage at Dec 2019: Stage 1 0.10%, Stage 2 4.5%, Stage 3 26%.

**Three choices.**
1. *Prepayment enters once, in survival.* Marginal PD = S(t-1) × h(t) with S including prepayment, and EAD is the
   balance *if alive*. Applying CPR in both places would double count.
2. *Cure-adjusted LGD* [RISK TO REVIEW]. About half of 90+ defaults cure, so a liquidation-only severity overstates
   loss. The 5% floor protects against the cure rate doing too much.
3. *Stage 3 LGD moves with the scenario.* House prices keep moving over an 18-month workout, so Stage 3 is not
   scenario-neutral.

**Interview questions.**
- Why is Stage 3 coverage so much lower for mortgages than for credit cards?
- What is the difference between accounting and economic LGD, and which does IFRS 9 want?
- How would you validate the cure rate?

---

## M5. Scenarios and validation

**Built.** `scenarios.py` builds paths that start from data *published* by the reporting date (1-month lag for
unemployment, 3 months for HPI). They run five years, then glide to the long run. `validation.py` covers the
out-of-time backtest with a binomial traffic light, AUC/Gini, decile calibration, stage migration, sensitivities
(SICR multiple, weights, downturn LGD, single scenarios, stress staging) and the loan-level provision waterfall.

**Three choices.**
1. *Weights 60/20/20, severe stress-only* [RISK TO REVIEW]. Severe is far enough in the tail to be a stress test, not
   a plausible outcome to weight.
2. *Waterfall attribution order: transfer first, then remeasurement.* The transfer effect is the opening-date ECL
   recomputed at the new stage. Remeasurement is the rest, so closing = opening + movements exactly.
3. *Report the red 2019 backtest honestly.* COVID shows why overlays exist; tuning the model to hide it would be wrong.

**Interview questions.**
- Why is probability-weighted ECL above base ECL? When could it be below?
- Your 2019 backtest is red. Is the model wrong? What would you have done in March 2020?
- What is the cliff effect, and why does it barely show up in your sensitivity?

---

## M6. Dashboard

**Built.** `app/streamlit_app.py` on top of `dashboard.py`. Weight sliders, SICR multiple and absolute floor, a
downturn-LGD toggle and a severe-stress view re-weight and re-stage saved loan-level components instantly. Editing a
cell in the macro-path grid re-projects that scenario through the hazard and LGD models in a few seconds. It runs from a
fresh clone on the bundle in `outputs/app/`. A test checks that the dashboard reproduces the pipeline's numbers.

**Three choices.**
1. *Precompute 12m, lifetime and Stage 3 ECL per scenario per loan.* Staging and weighting are then just arithmetic,
   so sliders are instant.
2. *Re-project only an edited scenario*, with caching.
3. *Show Stage 2 triggers.* People always ask why a loan is in Stage 2.

**Interview questions.**
- If the CRO wants downside at 40%, what happens to ECL and why?
- Which input moves ECL most, and is that a problem?
- How would you stop a dashboard like this being used to "shop" for a lower provision?

---

## M7. Report and polish

**Built.** `report/model_documentation.pdf` (10 pages, generated from the run): purpose, data, methodology,
assumptions table, results, validation, limitations, India note and coefficients. Also the README with an
auto-updated results block, `docs/case-study.md`, `docs/defence.md` (35 questions, answers left blank) and
`docs/india-relevance.md` (RBI Directions 2026, cited). `python -m stagecraft.pipeline` rebuilds everything from
`data/raw/`.

**Three choices.**
1. *Every number in the PDF and README is generated*, so nothing goes stale when the real data arrives.
2. *Researched and cited the RBI position* (final Directions, 27 April 2026) rather than relying on memory.
3. *Kept the synthetic-data warning on every chart and in every document.*

**Interview questions.**
- What's the single biggest limitation of this model for a real bank?
- How would you adapt it for an Indian housing-finance book under the 2026 Directions?
- What would model validation challenge first?

---

## M8. Real data

**Built.** Pulled the 15 Freddie Mac sample files (750,000 loans, 48.5 million loan-months) and ran the full pipeline. The real
files differed from the published layout:
- **Origination file:** 31 columns, because servicer name and MI cancellation moved to the performance file.
- **Performance file:** renamed `sample_perf_YYYY.txt`.
- **Codes and signs:** delinquency codes are zero-padded, and recoveries are negative.

The parser, the loss-sign check and the LGD now handle all of these, with tests. Three changes for scale:
- the panel is built one vintage at a time;
- the hazard training panel is subsampled to 6 million rows (all defaults kept, non-defaults reweighted);
- the loan-level dashboard bundle stays out of git under Freddie's licence, with a synthetic demo bundle committed instead.

**Three choices.**
1. *Reconcile before trusting.* Rebuilding Actual Loss from its components exposed the sign change: 0.2% match before the fix,
   99.4% after. Without it, recoveries would have *increased* losses.
2. *Add loan size and judicial state to LGD.* On real data, severity first appeared to *fall* with LTV. Small, old loans have low
   LTV but high percentage losses, and judicial-foreclosure states run about 12 points higher. Controlling for both restores a
   positive LTV slope.
3. *Report the red 2018 backtest honestly.* With 308,000 loans the binomial test flags any bias. The useful finding is the
   direction: conservative in Stage 1, too low in Stage 2.

**Interview questions.**
- What did you find when you reconciled the loss fields?
- Why did severity fall with LTV at first, and how did you fix it?
- Your backtest is statistically red but conservative overall. Is that a pass?

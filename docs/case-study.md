# Stagecraft: building a bank-style IFRS 9 ECL engine

*Case study for the portfolio site. Results quoted are from the bundled synthetic sample; replace them with the
real-data run from `outputs/headline.json`.*

## The problem

Under IFRS 9 a bank provisions for credit losses it **expects**, not only those already incurred. Each loan is put in
a stage: Stage 1 (12 months of expected loss), Stage 2 (lifetime, once credit risk has risen significantly) or
Stage 3 (credit-impaired). The answer has to be forward-looking and weighted across economic scenarios. At an Indian
cooperative bank I tracked SMA-0/1/2 and NPA buckets every month. Stagecraft is what that monitoring becomes under an
expected-loss regime, which the RBI's April 2026 Directions now require of commercial banks from April 2027.

## The data

The Freddie Mac Single-Family Loan-Level Dataset gives every loan's origination profile (credit score, LTV, DTI,
purpose…) and its **monthly delinquency status** until payoff, sale or foreclosure, with realised losses. FRED supplies
unemployment, house prices and mortgage rates. The pipeline is built for the 2005–2019 sample files (about 750,000
loans), which cover the 2008 crisis and run into COVID.

## What I built

1. **Data layer.** A parser for Freddie Mac's official 32 + 32 column layout, a Parquet loan-month panel, and an
   automated data report (codes, missing values, loss-field sign).
2. **Default and buckets.** Current / 30 / 60 / 90+ mapped to SMA-0/1/2 and NPA, with an explicit treatment of the
   one-month gap between US (missed-payment) and RBI (days-overdue) counting.
3. **Two PD models.** A macro-linked discrete-time hazard model (the champion), whose status × horizon terms let a
   delinquency signal decay over time, and a Markov roll-rate challenger. Their 5-year term structures agree within
   about a percentage point.
4. **LGD and EAD.** Economic workout LGD from Freddie's loss fields, linked to house prices through current LTV and
   adjusted for cures. EAD is the amortising balance, with prepayment as a competing risk.
5. **Staging and ECL.** A 30-DPD backstop, a relative + absolute lifetime-PD test against a like-for-like origination
   PD, and a forbearance/modification watchlist. ECL is the survival-weighted sum of marginal PD × LGD × EAD ×
   discount factor.
6. **Scenarios.** Base / upside / downside paths starting only from data published by the reporting date, plus a
   2008-style severe stress.
7. **Validation.** Out-of-time backtests with a traffic light, AUC, calibration, stage migration, sensitivities and an
   IFRS 7-style provision waterfall that reconciles exactly.
8. **Dashboard and documentation.** A Streamlit app for weights, SICR thresholds and editable macro paths, and a
   10-page generated model-documentation PDF.

## What I found (synthetic sample)

- **Weighted ECL is about 5% above base ECL.** Losses are convex in unemployment and house prices, so the downside
  adds more than the upside removes, which is exactly why IFRS 9 insists on multiple scenarios.
- **The 2018 model backtested well.** It predicted a 0.80% 12-month default rate and 0.78% was observed (green), and
  every segment was green.
- **The 2019 model failed in 2020.** It predicted 0.82% and 4.3% was observed. COVID forbearance was reported as
  delinquency, and no weighted scenario anticipated a 14.8% unemployment rate. This is the textbook case for a
  governed post-model overlay.
- **The SICR cliff effect is latent in good times.** With house prices up, almost no current loan's PD doubled, so
  Stage 2 was driven by the 30-DPD backstop. Under stress staging, a 1.5× threshold doubles Stage 2.
- **Under India's 2026 floors, prime housing would be floored.** Modelled Stage 1 coverage (0.04%) is well below the
  RBI's 0.25% minimum.

## What I'd do next

State-level house price indices, a scenario-dependent prepayment model, an explicit overlay framework, and porting
the pipeline to an Indian retail book with SMA history and RBI floors.

**Stack:** Python, Polars, Parquet, NumPy, statsmodels, scikit-learn, Matplotlib, ReportLab, Streamlit, pytest.

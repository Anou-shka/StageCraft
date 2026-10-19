# Stagecraft: building a bank-grade IFRS 9 ECL engine on 750,000 real mortgages

## The problem

Under IFRS 9 a bank provisions for credit losses it **expects**, not only those already incurred. Every loan sits in Stage 1
(12 months of expected loss), Stage 2 (lifetime loss, once credit risk has risen significantly since origination) or Stage 3
(credit-impaired). The number has to be forward-looking and weighted across economic scenarios.

At an Indian cooperative bank I monitored SMA-0/1/2 and NPA buckets every month. Stagecraft is what that monitoring becomes under
an expected-loss regime, which the RBI's April 2026 Directions now require of commercial banks from April 2027.

## The data

- **Freddie Mac Single-Family Loan-Level Dataset:** 750,000 mortgages from the 2005–2019 vintages, with 48.5 million monthly
  delinquency records and realised foreclosure losses, running through the 2008 crisis and COVID.
- **FRED:** unemployment, house prices and mortgage rates.

Reconciling losses showed that Freddie's current release had changed the published layout: a column moved and recoveries are now
negative numbers. The parser now detects both, and losses reconcile for 99.4% of credit events.

## What I built

| Layer | What it does |
|---|---|
| Data | Typed loan-month panel in Parquet (15 vintages in about a minute with Polars), with an automated data-quality report |
| Default & buckets | Current / 30 / 60 / 90+ mapped to SMA-0/1/2 and NPA, including the one-month gap between US (missed-payment) and RBI (day-count) conventions |
| PD | A macro-linked discrete-time hazard model (4m training rows, out-of-time AUC 0.88) and a Markov roll-rate challenger (0.85) |
| LGD | Economic workout LGD from about 14,000 foreclosures. Driven by LTV, mortgage insurance, loan size and judicial-foreclosure state; adjusted for cures |
| EAD | Amortising balance with prepayment as a competing risk |
| Staging | 30-DPD backstop, a 2×-and-50bp lifetime-PD test against a like-for-like origination PD, and a modification/forbearance watchlist |
| Scenarios | Base, upside and downside paths built only from data published at each reporting date; 2008-style severe stress |
| Validation | Out-of-time backtests, calibration, stage migration, sensitivities, IFRS 7-style provision waterfall |
| Delivery | Streamlit dashboard with live scenario and threshold controls; 10-page generated model documentation |

## Results (31 Dec 2019)

- **Allowance:** $207m on a $58.5bn book (0.35%).
- **Coverage by stage:** Stage 1 0.10%, Stage 2 4.5%, Stage 3 26%.
- **Weighted vs base:** the weighted ECL is 4.9% above base; the severe stress would need $368m.
- **Provision movement:** $251m at December 2018 to $207m at December 2019:
  - +$47m from loans moving into Stage 3;
  - −$40m from repayments;
  - −$50m of remeasurement as house prices kept rising.

## What I learned

- **Convexity is the point of multiple scenarios.** The downside adds $59m to the allowance; the upside removes only $10m.
- **A "red" backtest can be the most interesting slide.**
  - **2018 model:** ranks risk excellently (AUC 0.88) but over-predicts prime Stage 1 defaults and under-predicts Stage 2. Those
    are concrete recalibration targets.
  - **2019 model:** missed COVID entirely (0.6% predicted vs 4.0% observed). Forbearance reported as delinquency and an
    unprecedented shock are exactly why banks booked overlays in 2020.
- **The SICR cliff effect hides in good times.** In 2019, moving the threshold from 3× to 1.5× barely moves Stage 2. Under
  stress, the same change moves Stage 2 from 22% to 94% of the book.
- **Regulation can override the model.** India's 0.25% Stage 1 floor for housing loans is more than double the modelled 0.10%.

## Next steps

State-level house-price indices, scenario-dependent prepayment, a governed overlay framework, Stage 2 recalibration, and porting
the engine to an Indian retail book with SMA history and RBI floors.

**Stack:** Python · Polars · Parquet · NumPy · statsmodels · scikit-learn · Matplotlib · ReportLab · Streamlit · pytest

# Stagecraft: interview prep

Everything you need to talk about this project with confidence, in the order you'll need it. All numbers are from the real
Freddie Mac run (750,000 loans, 2005–2019 vintages). The blank-answer question bank for practice is in [`defence.md`](defence.md).

---

## 1. The 30-second pitch

> "I built Stagecraft, an IFRS 9 expected credit loss engine on 750,000 real US mortgages from Freddie Mac's loan-level data,
> covering 2005 to 2019 and so including the 2008 crisis. It does what a bank's impairment model does. It puts each loan in
> Stage 1, 2 or 3, estimates 12-month and lifetime PDs with a macro-linked hazard model and a roll-rate challenger, estimates LGD
> from actual foreclosure losses, and produces probability-weighted ECL under three economic scenarios plus a stress test. It also
> explains the movement in the provision between two year-ends like an annual report. At December 2019 the allowance is
> $207 million on a $58 billion book, and the PD model has an out-of-time AUC of 0.88. Coming from SMA and NPA monitoring at a
> cooperative bank, I also mapped it to the RBI's new ECL Directions that start in April 2027."

## 2. The 2-minute walkthrough (say it in this order)

1. **Why.** At the cooperative bank I tracked SMA-0/1/2 and NPA every month, which is backward-looking. IFRS 9, and the RBI from
   April 2027, requires provisioning for *expected* losses, forward-looking and weighted across scenarios. I wanted to build that
   end to end on real data.
2. **Data.** 750,000 loans with monthly delinquency status (48.5 million loan-months) plus actual loss data on foreclosures, with
   FRED unemployment and house prices. I wrote the parser against Freddie's file layout and found the current release had changed:
   a column moved and recoveries are now stored as negative numbers. I detect the loss sign by rebuilding the loss from its
   components, which reconciles for 99.4% of credit events.
3. **Default and staging.**
   - Default is 90+ days past due, foreclosure, short sale or REO.
   - Stage 2 has three triggers: a 30-days-past-due backstop; lifetime PD at least 2× what was expected at origination *and*
     50bp higher; or a modified or forborne loan.
   - Stage 3 is default, with six months' probation after a cure.
4. **PD.**
   - **Champion:** a discrete-time logistic hazard model on 4 million loan-months. A missed payment's signal fades over time, and
     the change in unemployment and house-price growth are what make it forward-looking.
   - **Challenger:** a Markov roll-rate model, as a sanity check.
5. **LGD and EAD.**
   - **LGD:** from about 14,000 real foreclosures, using economic LGD (recoveries discounted back to the default date). Driven by
     LTV, mortgage insurance, loan size and whether the state forecloses through the courts, then adjusted because about 45% of
     defaults cure.
   - **EAD:** the amortisation schedule, with prepayment as a competing exit.
6. **ECL.** For each month: the probability of surviving to that month and then defaulting, times LGD, times EAD, discounted at
   the note rate. 12 months for Stage 1, lifetime for Stage 2, LGD × balance for Stage 3.
7. **Validation.** Out-of-time backtests, AUC, calibration, stage migration, sensitivities, and a provision waterfall that
   reconciles exactly.

## 3. Numbers to know cold

| | 31 Dec 2018 | 31 Dec 2019 |
|---|---|---|
| Book | 310k loans, $56.4bn | 319k loans, $58.5bn |
| Weighted ECL / coverage | $251m / 0.45% | $207m / 0.35% |
| Coverage Stage 1 / 2 / 3 | 0.11% / 6.1% / 28% | 0.10% / 4.5% / 26% |
| Share of book in Stage 2 | 2.3% | 2.1% |
| Weighted vs base ECL | +5.0% | +4.9% |
| Severe stress ECL | $441m (1.8×) | $368m (1.8×) |
| 12-month PD: predicted vs observed | 0.68% vs 0.54% | 0.60% vs 4.0% (COVID) |
| Out-of-time AUC: hazard / Markov | 0.88 / 0.85 | 0.71 / 0.67 |

- **Waterfall 2018 → 2019:**

  | Movement | $m |
  |---|---|
  | Opening | 251.3 |
  | New loans | +14.9 |
  | Repaid / prepaid / sold | −40.0 |
  | Transfers into Stage 3 | +47.0 |
  | Transfers into Stage 2 | +4.6 |
  | Transfers into Stage 1 | −5.7 |
  | Remeasurement | −49.9 |
  | Write-offs | −14.7 |
  | Closing | 207.4 |

- **LGD:** economic severity averages 59% before cures. Downturn (2008–11 defaults) is 63%. P(liquidation | default) is 53–55%.
  Judicial states add about 12 points of severity.
- **Scorecard:** AUC 0.84 in-sample, 0.73–0.74 out of time.
- **Sensitivities (Dec 2019):**
  - Downturn LGD: +36%.
  - Severe scenario at 100% weight: +156%, because stress staging also moves loans to Stage 2.
  - Downside-heavy weights (40/10/50): +9.7%.
  - SICR threshold from 3× to 1.5×: +1.5%.

## 4. The five insights that make you sound senior

1. **Weighted ECL > base ECL because of convexity.** The downside adds $59m, while the upside saves only $10m. This is why IFRS 9
   wants multiple scenarios: the loss in the average scenario is not the average loss.
2. **"My 2018 backtest is red, and that's the right answer to discuss."**
   - **Statistical vs material:** with 308,000 loans a binomial test rejects even tiny biases, so materiality matters more than
     significance.
   - **Direction of the error:** the model over-predicts prime Stage 1 loans (0.45% vs 0.24%), which is conservative. It
     under-predicts Stage 2 (9.6% vs 12.2%), which is not conservative and is where I'd recalibrate first.
3. **COVID is the textbook case for an overlay.** Forborne loans were reported as missed payments, so 4% "defaulted" against 0.6%
   predicted, and many later cured. No scenario had 14.8% unemployment. Banks responded with new scenarios plus post-model
   adjustments; a model alone can't absorb a shock like that.
4. **The cliff effect is invisible until it isn't.** In 2019, moving the SICR threshold from 3× to 1.5× barely changes Stage 2
   (2.0% to 2.3%), because rising house prices meant few loans' PDs had doubled. Under stress, the same change moves Stage 2 from
   22% to 94% of the book. That is IFRS 9's pro-cyclicality: stage transfers amplify provisions in a downturn.
5. **India: the floor binds where the model is lowest.** Modelled Stage 1 coverage of 0.10% is below the RBI's 0.25% floor for
   housing loans, so a bank would hold the floor. Stage 2 (4.5% vs 1.5%) and Stage 3 (26% vs 10%) are above their floors.

## 5. Design choices and why (the "why did you…" questions)

| Choice | One-line defence |
|---|---|
| Hazard model over a straight logistic PD | It gives a full monthly term structure under any macro path; lifetime PD needs that, not one 12-month number |
| "Snapshot × horizon" training design | Every input is either known today or follows from the scenario, so no future delinquency has to be simulated |
| Delinquency × horizon terms | A loan 60 days late is very risky next quarter, much less so in three years. The model learns that decay from the data |
| Markov challenger | Simple, transparent and macro-free: if the two disagree wildly, something's wrong |
| Same model for origination and current PD | The SICR ratio then reflects a real change in credit risk, not a difference between two models |
| Prepayment in survival only | Applying it to both PD and EAD would double count |
| Cure-adjusted LGD | About half of 90+ defaults cure, so a liquidation-only LGD overstates loss. The 5% floor guards the other side |
| Loan size and judicial state in LGD | Without them the LTV effect is masked; both are well-documented drivers of US foreclosure cost |
| Default at 3 missed payments (vs 4) | US 90-day convention and IFRS 9's presumption. A strict RBI day-count reading is one month later; it's a config switch |
| Macro data with publication lags | No look-ahead: at 31 Dec, Q4 house prices weren't published yet |
| Severe scenario not weighted | It's a tail stress test; weighting it would bias the "unbiased" estimate IFRS 9 asks for |

## 6. Model answers to the questions you're most likely to get

**"Walk me through IFRS 9 staging."** Stage 1 is performing, with 12 months of expected loss. Stage 2 is a significant increase in
credit risk since origination, with lifetime loss; there is a rebuttable presumption at 30 days past due. Stage 3 is credit-impaired,
with lifetime loss and interest on the net amount. The key word is *since origination*: Stage 2 is about deterioration, not
absolute risk.

**"How do you get the origination PD for a 2006 loan?"** Banks rarely hold it for old loans. I re-run the same hazard model with
origination inputs: the original LTV on the original amortisation schedule, a current status, no modification, and
through-the-cycle macro. Comparing that with today's PD over the same remaining term isolates the deterioration.

**"Why is your Stage 3 coverage only 26–28%?"** These are first-lien loans secured on houses. About half of defaults cure, and
liquidations recover most of the balance. Card or unsecured Stage 3 coverage would be 60–90%.

**"What's the difference between PD in IFRS 9 and Basel?"** Basel IRB uses a through-the-cycle 12-month PD with downturn LGD for
capital. IFRS 9 uses point-in-time, forward-looking, probability-weighted PDs and LGDs over 12 months or the lifetime, with no
regulatory floors or downturn add-ons. The RBI's Indian version adds prudential floors on top.

**"How would you validate this model?"**
- Out-of-time backtests by segment and vintage.
- Discrimination (AUC) and calibration by decile.
- Benchmarking against a challenger (Markov).
- Stage-migration stability.
- Sensitivity to every owned assumption.
- A reconciliation of the provision movement.

I'd add: a recalibration of Stage 2, a monitoring threshold for the backtest gap, and a re-estimation trigger.

**"What would you do differently with more time?"**
- Use state-level house-price indices.
- Make prepayment depend on the scenario.
- Add an explicit overlay framework.
- Recalibrate Stage 2 PDs.

Then port it to an Indian retail book with SMA history and the RBI floors.

**"Where did the data come from, and did you clean it?"** Freddie Mac's public loan-level sample, with free registration. I
parsed it against the official layout and wrote an automated data report. Three discoveries:
- The current release moved a column and flipped the sign on recoveries; I caught this by reconciling losses.
- 117 loans have gaps in their monthly history.
- 12% of loans are missing DTI.

## 7. Weaknesses to own before they're raised

- **House prices:** national HPI understates regional crashes, so LGD and LTV are understated in Nevada and Florida-type markets.
- **Stage 2 calibration:** under-predicted by about 20%.
- **Prepayment:** flat, with no burnout or link to scenarios.
- **EIR:** the note rate is the proxy.
- **Origination PD:** retrospective, not as recorded at the time.
- **Macro data:** latest-vintage revisions, not data as first published.
- **COVID:** the default definition counts forbearance as default.

## 8. If they ask about India

- **Directions:** final RBI ECL Directions issued 27 April 2026, effective 1 April 2027.
- **Scope:** commercial banks only, excluding small finance, payments and local area banks. Cooperative banks are not covered yet.
- **Stages:** three stages, with SICR presumed above 30 days past due. NPA (90+ days) remains the Stage 3 anchor.
- **Floors for housing loans:** 0.25% Stage 1, 1.5% Stage 2, 10% Stage 3 in year one.
- **Transition:** a CET1 add-back phased out by 2031.
- **Mapping to my data:** a month-end Freddie status of 1, 2 and 3 corresponds to SMA-0, SMA-1 and SMA-2. NPA would be status 4
  under strict day counting.
- Details and citations are in [`india-relevance.md`](india-relevance.md).

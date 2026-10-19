# Relevance to India

*Researched October 2026 from the RBI's own publications; sources at the end.*

## Where the RBI stands

- **Final rules are out.** On **27 April 2026** the RBI issued the *Reserve Bank of India (Commercial Banks – Asset
  Classification, Provisioning and Income Recognition) Directions, 2026* [1, 2]. They replace the incurred-loss IRACP
  norms with an IFRS 9-style **expected credit loss** framework **from 1 April 2027**. The draft came out on
  7 October 2025 [3], following a January 2023 discussion paper [4].
- **Who it applies to.** Commercial banks (banking companies, corresponding new banks and SBI) **other than small
  finance banks, payments banks and local area banks** [2, para 4]. All India Financial Institutions get separate
  directions [1]. Cooperative banks, including the UCB I worked with, are **not** covered by these Directions and stay on
  the existing IRACP norms for now. NBFCs that report under Ind AS already measure impairment under Ind AS 109's ECL model.
- **Three stages** [2, para 25]: Stage 1 = 12-month ECL; Stage 2 = significant increase in credit risk (SICR),
  lifetime ECL; Stage 3 = credit-impaired, lifetime ECL.
- **30 DPD SICR presumption** [2, paras 33–36]: rebuttable presumption of SICR when payments are more than 30 days past
  due. Rebuttal needs a Board-approved policy and evidence, and must not be applied mechanically.
- **NPA survives as the Stage 3 anchor** [2, para 8]: a term loan is NPA when interest or principal is overdue for
  more than 90 days, with sub-standard / doubtful / loss ageing [2, para 10]. Stage 3 applies at borrower level [2, para 76].
- **Prudential floors** [2, para 82]. Modelled ECL can't go below these minimums. For **housing loans to individuals**:
  Stage 1 **0.25%**, Stage 2 **1.5%**; Stage 3 **10%** in year 1 (25% on any unsecured portion), 20% / 30% / 40%
  in years 2–4, and 100% after four years. For secured retail generally the figures are 0.40% / 5%.
- **Scenarios and judgement** [2, paras 47–49, 69–72]: unbiased, probability-weighted estimates from multiple
  scenarios, with weights set by historical experience and expert judgement under governance. Historical default
  rates must be adjusted for current and forecast conditions.
- **Overlays** count as general provisions for Tier 2 capital [2, para 75]. Stage 1–2 ECL can count as general
  provisions within limits; Stage 3 ECL is a specific provision.
- **EIR** [2, paras 50–54]: the opening ECL may use the contractual rate, and all loans move to EIR by 31 March 2030.
- **Transition** [2, paras 107–108]: the excess of 1 April 2027 ECL over existing provisions goes to opening retained
  earnings, with an optional CET1 add-back of 4/5, 3/5, 2/5 and 1/5 over FY2027-28 to FY2030-31.

## How Stagecraft maps onto Indian classification

| Freddie Mac status (month-end) | Days overdue (RBI counting) | Indian class [5] | Stagecraft bucket | IFRS 9 / RBI ECL stage |
|---|---|---|---|---|
| 0 | 0 | Standard | Current | Stage 1 (unless SICR) |
| 1 | ~30 | SMA-0 (up to 30 days) | 30 DPD | Stage 2: 30 DPD backstop |
| 2 | ~60 | SMA-1 (31–60) | 60 DPD | Stage 2 |
| 3 | ~90 | SMA-2 (61–90); NPA on day 91 | Default (draft) | Stage 3 |
| 4+, RA | 120+ | NPA (sub-standard → doubtful → loss) | Default | Stage 3 |

Two subtleties worth raising in an interview:

1. **Counting conventions.** Freddie (MBA method) counts *missed payments*. RBI counts *days from the due date*,
   flagged at day-end. At a month-end snapshot, three missed payments are about 90 days overdue: SMA-2 that day,
   NPA the next. Stagecraft's draft default (status ≥ 3) is therefore one month *earlier* than a strict RBI reading
   (status ≥ 4). The config switch `default_definition.min_dpd_status` changes it.
2. **Monthly data hides SMA-0.** An account a few days late that pays before month-end never shows. A bank running
   daily SMA flags sees much more SMA-0 churn than this data does.

## What an Indian bank would do differently

- **The floors bind for prime housing.** Stagecraft's modelled Stage 1 coverage (about 0.04% on the sample) is
  far below the 0.25% floor, so a bank would book the floor. Modelled ECL then matters mainly for Stage 2/3 and for
  riskier products.
- **Macro drivers.** Swap US unemployment/HPI for Indian GDP growth, the repo rate, and property prices (RBI's
  all-India HPI). For agriculture and MSME books, add sector stress indicators.
- **Data.** The monthly SMA/NPA history that banks already report (CRILC, internal MIS) is enough for a Markov
  roll-rate model on day one. The hazard model then needs loan-level origination attributes linked to it.

## Sources

1. RBI Press Release 2026-2027/150, *Reserve Bank issues Directions on Asset Classification, Provisioning and Income
   Recognition for Commercial Banks*, 27 April 2026.
   https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=62628
2. RBI (Commercial Banks – Asset Classification, Provisioning and Income Recognition) Directions, 2026.
   https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=13400 (paragraph numbers as cited)
3. RBI press release on the draft Directions, 7 October 2025.
   https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=61377
4. RBI, *Discussion Paper on Introduction of Expected Credit Loss Framework for Provisioning by Banks*, January 2023.
   https://rbidocs.rbi.org.in/rdocs/Publications/PDFs/DPECL160012023AE79B7B546C94715AA8468B0811096F5.PDF
5. RBI circular RBI/2021-2022/125, DOR.STR.REC.68/21.04.048/2021-22, *Prudential norms on IRACP – clarifications*,
   12 November 2021 (SMA-0/1/2 definitions, day-end flagging).

*Check the RBI pages for later amendments before relying on these details. The floors and transition schedule
are the parts most likely to be revised.*

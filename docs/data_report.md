# Data report

Source folder: `/home/user/StageCraft/data/raw/freddie`

## 1. Row counts

| vintage | loans | loan_months | first | last |
|---|---|---|---|---|
| 2005 | 50,000 | 3,877,176 | 2005-01 | 2026-03 |
| 2006 | 50,000 | 3,203,499 | 2006-01 | 2026-03 |
| 2007 | 50,000 | 3,012,061 | 2006-12 | 2026-03 |
| 2008 | 50,000 | 2,456,298 | 2008-01 | 2026-03 |
| 2009 | 50,000 | 3,160,366 | 2009-01 | 2026-03 |
| 2010 | 50,000 | 3,446,018 | 2010-01 | 2026-03 |
| 2011 | 50,000 | 3,631,696 | 2011-01 | 2026-03 |
| 2012 | 50,000 | 4,510,559 | 2012-01 | 2026-03 |
| 2013 | 50,000 | 4,197,674 | 2013-01 | 2026-03 |
| 2014 | 50,000 | 3,394,276 | 2014-01 | 2026-03 |
| 2015 | 50,000 | 3,467,166 | 2015-01 | 2026-03 |
| 2016 | 50,000 | 3,379,650 | 2016-01 | 2026-03 |
| 2017 | 50,000 | 2,800,219 | 2017-01 | 2026-03 |
| 2018 | 50,000 | 2,059,564 | 2018-01 | 2026-03 |
| 2019 | 50,000 | 1,934,614 | 2019-01 | 2026-03 |

Total: 750,000 loans, 48,530,836 loan-months.

- Duplicate (loan, month) records: 0
- Performance records with no origination record: 0
- Loans with a gap in their monthly history: 117

## 2. Missing values

### Origination file (columns with any missing; 9999/999 codes mapped to null)

| column | missing | missing % |
|---|---|---|
| credit_score | 219 | 0.0292 |
| mi_pct | 5 | 0.0006667 |
| units | 63 | 0.0084 |
| cltv | 27 | 0.0036 |
| dti | 88,364 | 11.78 |
| ltv | 25 | 0.003333 |
| n_borrowers | 85 | 0.01133 |

### Performance file (selected fields)

| column | missing | missing % |
|---|---|---|
| current_upb | 0 | 0 |
| status | 73,730 | 0.1519 |
| loan_age | 0 | 0 |
| rem_months | 138 | 0.0002844 |
| current_rate | 0 | 0 |
| eltv | 0 | 0 |
| mod_flag | 47,608,236 | 98.1 |
| assistance | 48,287,112 | 99.5 |
| deferral_flag | 48,103,573 | 99.12 |

Modification, assistance and deferral flags are blank unless the event applies, so high missing shares there are expected. ELTV is only populated from April 2017. A missing numeric `status` is the `RA` (REO acquired) code.

## 3. Delinquency status codes present

Freddie Mac reports missed payments under the MBA method: 0 = current, 1 = 30-59 days, 2 = 60-89, 3 = 90-119, and so on; `RA` = REO acquisition.

| dlq_raw | len | share % |
|---|---|---|
| 00 | 47,026,373 | 96.9 |
| 01 | 572,797 | 1.18 |
| 02 | 183,421 | 0.3779 |
| 03 | 95,219 | 0.1962 |
| RA | 73,730 | 0.1519 |
| 04 | 69,254 | 0.1427 |
| 05 | 58,785 | 0.1211 |
| 06 | 48,338 | 0.0996 |
| 07 | 41,202 | 0.0849 |
| 08 | 36,170 | 0.07453 |
| 09 | 31,971 | 0.06588 |
| 10 | 28,379 | 0.05848 |
| 11 | 25,226 | 0.05198 |
| 12 | 22,367 | 0.04609 |
| 13 | 19,719 | 0.04063 |

101 distinct codes in total (status values above 14 are grouped out of this table).

## 4. Zero-balance codes (loan terminations)

A loan's last record carries the zero-balance code; the code is set at most once per loan.

| exit_code | meaning | loans | actual loss populated | NSP = 'U' | share ever 90+ / credit event |
|---|---|---|---|---|---|
| 01 | Prepaid or matured (voluntary payoff) | 620,580 | 0 |  | 0.027 |
| 02 | Third-party sale | 2,520 | 0.9702 | 0 | 1 |
| 03 | Short sale or charge-off | 4,077 | 0.9429 | 0 | 1 |
| 09 | REO disposition | 8,625 | 0.9107 | 0 | 1 |
| 15 | Whole-loan sale | 1,092 | 0.9359 | 0 | 1 |
| 16 | Reperforming-loan securitisation | 4,998 | 0 |  | 0.96 |
| 96 | Defect prior to other termination event | 2,306 | 0 |  | 0.5243 |
|  | (still active) | 105,802 | 0 |  | 0.0923 |

## 5. Loss fields

Loss components (net sale proceeds, MI and non-MI recoveries, expenses, delinquent accrued interest, zero-balance removal UPB) are disclosed on the final record of credit-event loans (codes 02, 03, 09, 15). Actual Loss is null for dispositions within three months of the performance cut-off and for defect loans.

- Credit-event loans with Actual Loss and Net Sale Proceeds: 15,165
- Sign convention detected: losses are **positive** (Actual Loss matches the User Guide formula rebuilt from components with that sign for 99.4% of loans). The LGD module applies this sign.

Loss severity by default year (accounting loss, before discounting and cure adjustment):

| default year | credit events | mean loss / UPB at default | loss missing |
|---|---|---|---|
| 2005 | 17 | 0.3246 | 2 |
| 2006 | 98 | 0.4355 | 19 |
| 2007 | 483 | 0.5283 | 69 |
| 2008 | 1,747 | 0.5708 | 240 |
| 2009 | 3,633 | 0.5722 | 327 |
| 2010 | 2,895 | 0.5378 | 220 |
| 2011 | 2,243 | 0.5077 | 136 |
| 2012 | 1,684 | 0.4405 | 76 |
| 2013 | 951 | 0.446 | 17 |
| 2014 | 626 | 0.4444 | 13 |
| 2015 | 468 | 0.4449 | 6 |
| 2016 | 373 | 0.3949 | 3 |
| 2017 | 289 | 0.3159 | 2 |
| 2018 | 240 | 0.3142 | 3 |
| 2019 | 199 | 0.2738 | 2 |
| 2020 | 165 | 0.2218 | 5 |
| 2021 | 80 | 0.4192 | 0 |
| 2022 | 52 | 0.2592 | 2 |
| 2023 | 32 | 0.3289 | 0 |
| 2024 | 35 | 0.3239 | 3 |
| 2025 | 4 | 0.07254 | 3 |

## 6. Macro data (FRED)

- UNRATE monthly, HPI (USSTHPI) quarterly interpolated to monthly, MORTGAGE30US weekly averaged to monthly.
- Common monthly coverage: 1975-01 to 2026-06.
- HPI interpolation: each quarterly value is placed at the middle month of its quarter and log-linearly interpolated (`macro.hpi_monthly`).
- Publication lags applied at each reporting date: unemployment 1 month, HPI 3 months.

## 7. Default flag

Default = first month with status >= 3, REO status, or zero-balance code in 02, 03, 09, 15.

- Loans ever in default: 48,839 (6.5%)
- First flagged by delinquency status: 48,712; by a credit-event code with no prior 90+: 127

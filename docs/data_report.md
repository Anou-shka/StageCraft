# Data report

> **SYNTHETIC DATA.** This report was generated from the bundled synthetic sample
> (`data/sample/freddie`, written by `stagecraft.synth` in the Freddie Mac file format).
> Every number below describes simulated loans, not Freddie Mac loans. Drop the real
> `sample_YYYY.zip` files into `data/raw/freddie/` and rerun `python -m stagecraft.pipeline`
> to regenerate this report on real data.

Source folder: `/home/user/StageCraft/data/sample/freddie`

## 1. Row counts

| vintage | loans | loan_months | first | last |
|---|---|---|---|---|
| 2005 | 800 | 56,744 | 2005-03 | 2024-12 |
| 2006 | 800 | 40,554 | 2006-03 | 2024-12 |
| 2007 | 800 | 36,239 | 2007-03 | 2024-12 |
| 2008 | 800 | 30,472 | 2008-03 | 2024-12 |
| 2009 | 800 | 48,967 | 2009-03 | 2024-12 |
| 2010 | 800 | 53,473 | 2010-03 | 2024-12 |
| 2011 | 800 | 54,720 | 2011-03 | 2024-12 |
| 2012 | 800 | 74,478 | 2012-03 | 2024-12 |
| 2013 | 800 | 66,655 | 2013-03 | 2024-12 |
| 2014 | 800 | 56,741 | 2014-03 | 2024-12 |
| 2015 | 800 | 60,974 | 2015-03 | 2024-12 |
| 2016 | 800 | 60,632 | 2016-03 | 2024-12 |
| 2017 | 800 | 49,173 | 2017-03 | 2024-12 |
| 2018 | 800 | 34,413 | 2018-03 | 2024-12 |
| 2019 | 800 | 36,832 | 2019-03 | 2024-12 |

Total: 12,000 loans, 761,067 loan-months.

- Duplicate (loan, month) records: 0
- Performance records with no origination record: 0
- Loans with a gap in their monthly history: 0

## 2. Missing values

### Origination file (columns with any missing; 9999/999 codes mapped to null)

| column | missing | missing % |
|---|---|---|
| credit_score | 65 | 0.5417 |
| dti | 114 | 0.95 |

### Performance file (selected fields)

| column | missing | missing % |
|---|---|---|
| current_upb | 0 | 0 |
| status | 1,006 | 0.1322 |
| loan_age | 0 | 0 |
| rem_months | 0 | 0 |
| current_rate | 0 | 0 |
| eltv | 385,993 | 50.72 |
| mod_flag | 743,320 | 97.67 |
| assistance | 759,579 | 99.8 |
| deferral_flag | 756,037 | 99.34 |

Modification, assistance and deferral flags are blank unless the event applies, so high missing shares there are expected. ELTV is only populated from April 2017. A missing numeric `status` is the `RA` (REO acquired) code.

## 3. Delinquency status codes present

Freddie Mac reports missed payments under the MBA method: 0 = current, 1 = 30-59 days, 2 = 60-89, 3 = 90-119, and so on; `RA` = REO acquisition.

| dlq_raw | len | share % |
|---|---|---|
| 0 | 742,446 | 97.55 |
| 1 | 3,934 | 0.5169 |
| 2 | 1,425 | 0.1872 |
| 3 | 1,062 | 0.1395 |
| 4 | 1,008 | 0.1324 |
| RA | 1,006 | 0.1322 |
| 6 | 954 | 0.1254 |
| 5 | 953 | 0.1252 |
| 7 | 879 | 0.1155 |
| 8 | 781 | 0.1026 |
| 9 | 691 | 0.09079 |
| 10 | 622 | 0.08173 |
| 11 | 563 | 0.07398 |
| 12 | 491 | 0.06451 |
| 13 | 409 | 0.05374 |

81 distinct codes in total (status values above 14 are grouped out of this table).

## 4. Zero-balance codes (loan terminations)

A loan's last record carries the zero-balance code; the code is set at most once per loan.

| exit_code | meaning | loans | actual loss populated | NSP = 'U' | share ever 90+ / credit event |
|---|---|---|---|---|---|
| 01 | Prepaid or matured (voluntary payoff) | 8,656 | 0 |  | 0.03119 |
| 02 | Third-party sale | 36 | 1 | 0.02778 | 1 |
| 03 | Short sale or charge-off | 99 | 0.9798 | 0.0404 | 1 |
| 09 | REO disposition | 197 | 0.9949 | 0.005076 | 1 |
| 15 | Whole-loan sale | 23 | 1 | 0.04348 | 1 |
| 16 | Reperforming-loan securitisation | 14 | 0 |  | 1 |
| 96 | Defect prior to other termination event | 17 | 0 |  | 0 |
|  | (still active) | 2,958 | 0 |  | 0.1007 |

## 5. Loss fields

Loss components (net sale proceeds, MI and non-MI recoveries, expenses, delinquent accrued interest, zero-balance removal UPB) are disclosed on the final record of credit-event loans (codes 02, 03, 09, 15). Actual Loss is null for dispositions within three months of the performance cut-off and for defect loans.

- Credit-event loans with Actual Loss and Net Sale Proceeds: 348
- Sign convention detected: losses are **negative** (Actual Loss matches the User Guide formula rebuilt from components with that sign for 100.0% of loans). The LGD module applies this sign.

Loss severity by default year (accounting loss, before discounting and cure adjustment):

| default year | credit events | mean loss / UPB at default | loss missing |
|---|---|---|---|
| 2005 | 3 | 0.09274 | 0 |
| 2006 | 11 | 0.06489 | 0 |
| 2007 | 23 | 0.1355 | 0 |
| 2008 | 38 | 0.1782 | 0 |
| 2009 | 40 | 0.2325 | 1 |
| 2010 | 24 | 0.1662 | 0 |
| 2011 | 13 | 0.1768 | 0 |
| 2012 | 16 | 0.09731 | 0 |
| 2013 | 9 | 0.05603 | 0 |
| 2014 | 11 | 0.08351 | 0 |
| 2015 | 17 | 0.1417 | 0 |
| 2016 | 20 | 0.07427 | 0 |
| 2017 | 14 | 0.0694 | 0 |
| 2018 | 16 | 0.06076 | 0 |
| 2019 | 15 | 0.03175 | 1 |
| 2020 | 45 | 0.006002 | 0 |
| 2021 | 25 | 0.005254 | 0 |
| 2022 | 10 | 0.01035 | 0 |
| 2023 | 5 | 0.009727 | 1 |

## 6. Macro data (FRED)

- UNRATE monthly, HPI (USSTHPI) quarterly interpolated to monthly, MORTGAGE30US weekly averaged to monthly.
- Common monthly coverage: 1975-01 to 2026-06.
- HPI interpolation: each quarterly value is placed at the middle month of its quarter and log-linearly interpolated (`macro.hpi_monthly`).
- Publication lags applied at each reporting date: unemployment 1 month, HPI 3 months.

## 7. Default flag

Default = first month with status >= 3, REO status, or zero-balance code in 02, 03, 09, 15.

- Loans ever in default: 937 (7.8%)
- First flagged by delinquency status: 937; by a credit-event code with no prior 90+: 0

# Data quality report — GMSC `cs-training.csv`

Source file sha256: `1bd46da486a5708c58c7b01a034fae2a13b327f6f7b62ea7ba4fe3b5824b24ac`
Rows: 150,000  |  Columns: 11

## Target (`SeriousDlqin2yrs`)
Counts: {0: 139974, 1: 10026}  |  default rate: 6.6840%

## Missing values
| Column | Missing | % |
|---|---|---|
| MonthlyIncome | 29,731 | 19.82% |
| NumberOfDependents | 3,924 | 2.62% |

Missing `MonthlyIncome` is not harmless: where it is missing, `DebtRatio` has a median of 1159.0 versus 0.296 where income is present, i.e. it behaves like an absolute amount rather than a ratio. Default rate is 5.61% (income missing) vs 6.95% (income present).

## Invalid / suspicious values
- Exact duplicate rows: 609
- Sentinel codes 96/98 in past-due columns: {'NumberOfTime30-59DaysPastDueNotWorse': {96: 5, 98: 264}, 'NumberOfTime60-89DaysPastDueNotWorse': {96: 5, 98: 264}, 'NumberOfTimes90DaysLate': {96: 5, 98: 264}} (rows where all three columns carry a sentinel: 269)
- age < 18: 1  |  age > 100: 13
- Utilization > 1: 3,321  |  > 10: 241
- DebtRatio > 1: 35,137  |  MonthlyIncome == 0: 1,634

## Outliers (no clipping applied at this stage)
| Column | p1 | p99 | max | beyond 3×IQR |
|---|---|---|---|---|
| RevolvingUtilizationOfUnsecuredLines | 0 | 1.093 | 5.071e+04 | 339 |
| age | 24 | 87 | 109 | 0 |
| NumberOfTime30-59DaysPastDueNotWorse | 0 | 4 | 98 | 23,982 |
| DebtRatio | 0 | 4979 | 3.297e+05 | 30,457 |
| MonthlyIncome | 0 | 2.5e+04 | 3.009e+06 | 1,557 |
| NumberOfOpenCreditLinesAndLoans | 0 | 24 | 58 | 442 |
| NumberOfTimes90DaysLate | 0 | 3 | 98 | 8,338 |
| NumberRealEstateLoansOrLines | 0 | 4 | 54 | 209 |
| NumberOfTime60-89DaysPastDueNotWorse | 0 | 2 | 98 | 7,604 |
| NumberOfDependents | 0 | 4 | 20 | 991 |

## Cleaning applied (deterministic, learns nothing from data)
- rows_in: 150,000
- rows_dropped_age_lt_18: 1
- duplicate_rows_dropped: 609
- sentinel_cells_set_to_nan: 675
- rows_with_sentinel: 225
- rows_out: 149,390

## Dataset representativeness and leakage notes
- US consumer credit data (2011). Not Indian, not MSME. Results say nothing about Indian borrowers.
- `cs-test.csv` has no labels (target column empty), so it cannot be used for evaluation; a labelled 80/20 train/test split is carved out of `cs-training.csv` (validation = 5-fold CV inside train).
- No timestamps or applicant ids: temporal splitting is impossible, and exact-duplicate removal cannot distinguish a true duplicate from two similar applicants.
- The past-due count columns carry no observation-window definition for the 90-day count in the data dictionary; any overlap with the 2-year target window cannot be checked from this data. Treat their predictive strength with caution.
- Outlier clipping, imputation and scaling are fit on the training split only (Phase 2 pipeline).

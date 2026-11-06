# Source data dictionary — Give Me Some Credit (from attached Data_Dictionary.xls)

Source: Kaggle "Give Me Some Credit" competition. License/terms: Kaggle competition rules apply; check before any redistribution. Population: US consumer borrowers (not Indian, not MSME).

| Variable | Description (as given) | Type (as given) |
|---|---|---|
| SeriousDlqin2yrs | Person experienced 90 days past due delinquency or worse (**target**) | Y/N |
| RevolvingUtilizationOfUnsecuredLines | Total balance on credit cards and personal lines of credit (excl. real estate and installment debt such as car loans) divided by the sum of credit limits | percentage |
| age | Age of borrower in years | integer |
| NumberOfTime30-59DaysPastDueNotWorse | Times borrower has been 30–59 days past due but no worse in the last 2 years | integer |
| DebtRatio | Monthly debt payments, alimony, living costs divided by monthly gross income | percentage |
| MonthlyIncome | Monthly income | real |
| NumberOfOpenCreditLinesAndLoans | Number of open loans (installment, e.g. car loan or mortgage) and lines of credit (e.g. credit cards) | integer |
| NumberOfTimes90DaysLate | Times borrower has been 90 days or more past due | integer |
| NumberRealEstateLoansOrLines | Number of mortgage and real estate loans including home-equity lines of credit | integer |
| NumberOfTime60-89DaysPastDueNotWorse | Times borrower has been 60–89 days past due but no worse in the last 2 years | integer |
| NumberOfDependents | Number of dependents in family excluding themselves (spouse, children, etc.) | integer |

Notes: "percentage" in the sheet may in practice be a ratio (0–1+); to be verified against the data. Currency of `MonthlyIncome` is not stated in the dictionary.

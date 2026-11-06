# ML methodology (as implemented; numbers from `models/model-…-20261105193551.json`)

**Data:** Kaggle *Give Me Some Credit* `cs-training.csv` (US consumer credit, 2011). `cs-test.csv` has no labels → unusable for evaluation.
**Cleaning (row-level only):** 1 invalid age dropped, 609 exact duplicates dropped, 675 sentinel cells (96/98) in past-due counts → NaN. 149,390 rows, default rate 6.70%.
**Split (as requested):** stratified **80/20** train/test, seed 42: train 119,512 (8,007 defaults), test 29,878 (2,002 defaults). Dataset `gmsc-v1-d816fcae-split8020`.
No separate validation set: all selection uses **5-fold CV inside the 80% train set**; the 20% test set is scored exactly once.
**Features:** 16 (see `feature_dictionary.md`). Winsorising caps, imputers and scalers are fitted on training folds only.

## Candidates (out-of-fold on train)
| Model | OOF ROC-AUC | OOF PR-AUC |
|---|---|---|
| Logistic regression (class-weighted) | 0.8557 | 0.3747 |
| **HistGradientBoosting** (tuned: lr 0.05, depth 3, min-leaf 100, L2 1.0) | **0.8646** | **0.3959** |
| HistGradientBoosting + **SMOTE** (own implementation, applied only inside each training fold) | 0.8533 | 0.3657 |

**SMOTE did not help** (it lowered PR-AUC by ~0.03), so the selected model is plain gradient boosting. Selection metric: OOF PR-AUC.
**Calibration:** isotonic regression fitted on out-of-fold train predictions. **Threshold:** 0.2339 = argmax F1 on calibrated OOF train predictions.
**Risk bands:** LOW < 5%; HIGH ≥ 23.4% (the flag threshold); MODERATE between.

## Results
| Evaluation | ROC-AUC | PR-AUC | Precision | Recall | F1 | Accuracy | Brier |
|---|---|---|---|---|---|---|---|
| 5-fold CV (OOF, calibrated) | 0.8652 | 0.3900 | 0.401 | 0.496 | 0.443 | 0.917 | 0.0491 |
| Train (in-sample, not a performance claim) | 0.8726 | 0.4104 | 0.410 | 0.509 | 0.454 | 0.918 | 0.0483 |
| **Held-out test (20%)** | **0.8666** | **0.4096** | 0.414 | 0.519 | 0.461 | 0.9185 | 0.0483 |

Test confusion matrix @0.2339: TN 26,405 · FP 1,471 · FN 963 · TP 1,039; specificity 0.947, FPR 5.3%, FNR 48.1%.
Always predicting "no default" scores 93.3% accuracy, so accuracy is not a headline; the model misses ~48% of defaulters at this threshold.

## Explainability (SHAP status)
The `shap` package could not be installed in the build environment, so **the `shap` library is not used**. Instead `backend/ml/explain.py`
computes **Shapley values of the deployed (calibrated) model** by permutation sampling against 25 training-row background samples:
exactly additive (base + contributions = prediction, tested), same features/order as the model, real inputs, with a reported standard error.
Units are probability points. Top global drivers (mean |contribution|): total late-payment events 2.9 pp, credit utilisation 2.6 pp, age 0.8 pp.

## Deviations from the brief
| Requested | Status |
|---|---|
| XGBoost | **Not trained** — package unavailable. Code path in `train.py` auto-enables an `xgboost_smote` candidate (imblearn Pipeline) when `xgboost` + `imbalanced-learn` are installed. **Untested.** Gradient boosting here is scikit-learn's HistGradientBoosting. |
| SMOTE via imblearn Pipeline | Own tested SMOTE implementation inside CV folds (never on test data). |
| SHAP library | Own exact-additive Shapley estimator (above). |
| Validation split | Replaced by CV inside train, per the 80/20 request. |
| Temporal split | Impossible: no timestamps. |

## Limitations
US 2011 consumer data, not Indian/MSME. `NumberOfTimes90DaysLate` has no stated window and may leak the target. Age is an input (fairness concern).
Isotonic calibration is fitted on train OOF; the test reliability table is in the Model page. Explanations are model contributions, not causal effects.

# Predicted Score Estimates for chr21:22527963-27527963

Default region grouping: 2.5 Mb.

These estimates use a chr21 GATK regression model trained from the flattened
AdvancedScorer history. The raw model underestimates the exact nearby config:

- Nearby actual region: `chr21:22565159-27565159`
- Center distance from target: ~37 kb
- Exact nearby actual score: `96.01`
- Exact nearby raw model prediction at target: `91.53`
- Local calibration offset: `+4.48`

Because the target and nearest history overlap almost completely, the calibrated
estimate is more useful than the raw global model estimate.

| config | raw model | calibrated estimate | estimated core | complete | fp | quality | fp/target | region FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `gatk_best_predicted_chr21_22527963_27527963.conf` | 91.33 | 95.81 | 56.79 | 15.00 | 13.36 | 6.17 | 4.43 | 976 |
| `gatk_best_predicted_stable_chr21_22527963_27527963.conf` | 90.45 | 94.93 | 56.33 | 15.00 | 13.02 | 6.10 | 4.38 | 965 |
| `gatk_best_predicted_quality_chr21_22527963_27527963.conf` | 91.34 | 95.82 | 56.66 | 15.00 | 13.41 | 6.26 | 4.39 | 967 |
| `gatk_nearby_chr21_22565159_27565159.conf` | 91.53 | 96.01 | 56.90 | 15.00 | 13.61 | 6.03 | 4.46 | 983 |

Recommendation:

1. Run `gatk_best_predicted_quality_chr21_22527963_27527963.conf` if you want
   the best estimated upside.
2. Run `gatk_best_predicted_chr21_22527963_27527963.conf` as the primary balanced
   candidate.
3. Keep `gatk_nearby_chr21_22565159_27565159.conf` as the anchor/baseline.

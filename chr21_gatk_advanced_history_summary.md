# chr21 GATK AdvancedScorer History

Generated from `/root/minos/rounds.json`.

- Rows: 283 scored chr21 GATK/newgatk/oldgatk instances
- CSV: `/root/minos/chr21_gatk_advanced_history.csv`
- JSONL: `/root/minos/chr21_gatk_advanced_history.jsonl`
- Score min/median/max: 38.99 / 82.14 / 97.06
- Score p10/p90: 67.57 / 93.12

## Columns To Optimize

- `score_100` / `computed_advanced_score`: final target score.
- `core_points`: 60-point Core F1 contribution.
- `completeness_points`: 15-point recall/coverage contribution.
- `fp_points`: 15-point assessed false-positive and call-count contribution.
- `quality_points`: 10-point Ti/Tv and Het/Hom ratio contribution.
- `overcall_penalty`, `fp_per_target`, `region_fp_total`: full-region overcall guardrail.
- `runtime_seconds`: retained as metadata only; not an optimization metric.

## Top Rows

| score | region | label | core | complete | fp | quality | overcall |
|---:|---|---|---:|---:|---:|---:|---:|
| 97.06 | chr21:16768853-21768853 | oldgatk | 59.94 | 15.00 | 15.00 | 7.12 | 0.00 |
| 97.01 | chr21:25970849-30970849 | newgatk | 59.94 | 15.00 | 15.00 | 7.07 | 0.00 |
| 96.93 | chr21:14677141-19677141 | gatk | 59.94 | 15.00 | 15.00 | 6.99 | 0.00 |
| 96.79 | chr21:29286010-34286010 | newgatk | 59.94 | 15.00 | 15.00 | 6.85 | 0.00 |
| 96.74 | chr21:29286010-34286010 | gatk | 59.94 | 15.00 | 15.00 | 6.80 | 0.00 |
| 96.67 | chr21:15284883-20284883 | gatk | 59.94 | 15.00 | 15.00 | 6.73 | 0.00 |
| 96.67 | chr21:15284883-20284883 | newgatk | 59.94 | 15.00 | 15.00 | 6.73 | 0.00 |
| 96.64 | chr21:15284883-20284883 | oldgatk | 59.94 | 15.00 | 15.00 | 6.70 | 0.00 |
| 96.14 | chr21:15424354-20424354 | newgatk | 59.94 | 15.00 | 15.00 | 6.20 | 0.00 |
| 96.07 | chr21:15731433-20731433 | newgatk | 59.94 | 15.00 | 15.00 | 6.13 | 0.00 |

## Closest Row To Current Target Center

- Target center used here: `chr21:22527963-27527963` center `25027963`
- Closest historical row: `chr21:22565159-27565159`
- Score: `96.01`
- Component points: core `59.94`, completeness `15.00`, fp `15.00`, quality `6.07`, overcall `0.00`

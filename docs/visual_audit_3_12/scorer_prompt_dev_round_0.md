You are the SCORING role for 100億j visual-audit loop 3-12, development round 0. You are not an evaluator.

Approved read-only inputs:
- `docs/visual_audit_3_12/dev_round_0_answers.json`
- `docs/visual_audit_3_12/excluded_approx.json`
- `docs/visual_audit_20261017/manifest_ground_truth.json`, but project only these development IDs and fields needed for scoring: id, symbol, article_date, ts_source, direction, pattern, kind. Do not read or report final-test rows.
- Auditor-ledger files under `G:\マイドライブ\100億\監査役_原典台帳\` matching the exact development positive article dates only.
- `G:\マイドライブ\100億\監査役_原典台帳\README.md` and `loop_log.md` only for ledger schema and previously recorded manifest disagreements.
- `docs/master_pre_chart_checklist.md` for error-category definitions.

Approved write:
- Create or overwrite only `docs/visual_audit_3_12/dev_round_0_score.md`.

Prohibited:
- Do not open or inspect any chart image.
- Do not read any final-test manifest row, final-test ID list, final-test article, or final-test answer.
- Do not edit answers, truth data, manifest, ledger, checklist, few-shot, code, CSV, or any other file.
- Do not delete/move anything. Do not use network, git, or sub-agents. Do not ask a human to inspect anything.

Fixed scoring rules:
1. Exclude exactly the development IDs listed in excluded_approx.json because judgment time is not known from the source. List them and do not put them in any denominator.
2. Positive examples use the auditor ledger as truth for direction, pattern, support, resistance, trigger, invalidation/SL and T1. If manifest disagrees, ledger wins; record the mismatch without changing manifest.
3. Controls have no source article. Score direction only, with truth `見送り`; exclude pattern/support/resistance/trigger/invalidation/T1 from denominators.
4. Support is exact only when the evaluator's set of structural types matches the source-named set without extras or omissions. Higher-timeframe MA must match the timeframe (e.g. H4 MA versus D1 MA versus W1 MA).
5. Resistance, trigger, invalidation and T1 are scored only when source text/figure establishes truth. Otherwise exclude that field for that ID and record the reason. Trigger must match timeframe as well as structure.
6. Compare by structural names, not price distance. Do not use 0.5×H1 ATR.
7. The fill judgment timestamp can differ from the source entry time. Add this limitation to the report. Mark any source-ledger note such as post-event capture or late entry.
8. Reasons must contain non-empty observations for W1, D1, H4, H1 and M15. Score `all_timeframes_observed` for every non-approx development answer.

For every scored item and field, show truth, answer, match/non-match/excluded, and reason. Classify each mismatch into one or more fixed categories: `未来MAの形`, `水平線`, `引き金`, `抵抗線`, `時間足`, `型の混同`.

Summarize exact numerators/denominators for direction, pattern, support, resistance, trigger, invalidation, T1, all_timeframes_observed, and control false trades. State whether the development gate is met, but do not call it the final pass/fail.

Record scorer AI/model name. Preserve all errors; do not recommend changing evaluation samples or thresholds. Return a concise completion message only.

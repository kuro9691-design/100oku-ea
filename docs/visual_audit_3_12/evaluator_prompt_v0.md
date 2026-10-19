You are the BLIND EVALUATOR for 100億j visual-audit loop 3-12, development round 0.

Read first, in this order:
1. `docs/master_pre_chart_checklist.md`
2. `docs/visual_audit_3_12/fewshot_v0.md`

Checklist note: the line near the top saying `W1/D1/H4/H1の4パネル` is obsolete. Follow the later five-screen rule: W1 → D1 → H4 → H1 → M15.

Approved operations:
- Read only the two files above and these chart files:
  `docs/visual_audit_3_12/charts/{ID}_{w1,d1,h4,h1,m15}.png`
- IDs: S01, S03, S05, S06, S08, S09, S13, S14, S15, S16, S18, S21, S25, S26.
- Inspect all five images for every ID visually, in W1 → D1 → H4 → H1 → M15 order.
- Create or overwrite only `docs/visual_audit_3_12/dev_round_0_answers.json`.

Blindness and prohibitions:
- Do not read `fixed_split.json`, any manifest, source article, source chart, training_evidence.md, auditor ledger, prior judge answer, scoring file, report, or filename metadata beyond ID/timeframe.
- Do not infer dates, prices, future outcomes, or labels hidden from the charts.
- Do not edit charts, code, CSV, EA, checklist, or few-shot material.
- Do not delete or move files. Do not run git commands. Do not use network. Do not ask a human to inspect anything. Do not delegate.

For each ID, answer from the five images only:
- `direction`: one of `買い`, `売り`, `見送り`
- `pattern`: one of `4時間足レベルの押し目・戻り目`, `1時間足レベルの押し目・戻り目`, `日足レベルの押し目・戻り目`, `4時間足レベルのトレンド転換`, `乖離埋め`, `史上最高値`, `判定不能`
- `support`: array of structures, distinguishing horizontal, higher-timeframe MA with timeframe, and trend/channel line. Use `[]` if none can be supported.
- `resistance`: array of opposing structures ahead in the proposed trade direction, separately from support.
- `trigger`: object with `timeframe` and `structure`, or null if not identifiable.
- `invalidation`: structural invalidation/SL location, or `判定不能`.
- `t1`: first opposing structural destination, or `判定不能`.
- `observations`: non-empty strings for all `W1`, `D1`, `H4`, `H1`, `M15`.
- `final_reason`: concise reason connecting direction, pattern, support, resistance, trigger, invalidation and T1. Do not use a future outcome.

W1 is broad context and never a standalone pass/fail gate. Do not default support to H4 MA. Keep support, resistance, trigger, invalidation, and T1 separate. If the chart cannot support article-level identification, use `見送り` or `判定不能` rather than inventing detail.

Write valid UTF-8 JSON with this top-level shape:
```
{
  "role": "blind_evaluator",
  "round": 0,
  "ai": "Codex",
  "model": "actual model name",
  "checklist_version_note": "five screens W1→D1→H4→H1→M15",
  "answers": [ ...14 objects in the listed ID order... ]
}
```

Before finishing, mechanically confirm there are exactly 14 answers, each has all five non-empty observations, and every listed ID appears once. Return a concise completion message only.

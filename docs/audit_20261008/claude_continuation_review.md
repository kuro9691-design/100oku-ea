# Claude続き作業の確認

確認日: 2026-10-08  
対象報告: `100億j_share/報告_20261008_執行仕様と執行修正.md`

## 結論

Claudeの作業は、指定された範囲内で実装・テストされており、執行時点の混入を減らす修正として妥当である。独立実行した48件のユニットテストは全件通過した。戦略条件・閾値・価格CSVは変更されていない。

ただし、これは「A〜Gを原典どおりに再現できた」ことを意味しない。原典との照合前に解決が必要な注文取消し規則と候補入口の未決定が残っている。実口座・OOS・閾値調整は行われていない。

## 独立確認済み

- `oku100/pipeline.py`、`oku100/backtest.py`、`oku100/distribution.py` の差分を、`oku100_backup_20261008/` と照合。変更は報告された5項目に対応している。
  - 逆指値のギャップ約定を始値に補正
  - 約定足自身のSL/TP判定と、M15による順序解決
  - 採点・SL/TP構造を注文時点の確定足へ固定
  - 集計側を確定済み上位足の解決経路に統一
  - strict/actionable の候補判定関数を共有化
- 実行: `python -B -X utf8 -m unittest tests.test_pipeline tests.test_indicators tests.test_leak tests.test_execution_spec tests.test_stop_gap_execution tests.test_optimize -v`
  - 48件すべて成功（ログ: `docs/audit_20261008/claude_continuation_tests.log`）。
- 現在の `pipeline.py` / `backtest.py` / `distribution.py` のSHA-256は `probes_after_fix.json` の記録と一致。
- `data/d1.csv`、`data/h4.csv`、`data/h1.csv`、`btc_candidate_indicators.csv` の現在のSHA-256も同記録と一致。`m15.csv` は同JSONに作業前のハッシュが残されていないため、今回の確認では「現状値の取得」までに留まる。

## 残る重要事項

1. 未約定注文の有効期限・取消し条件は未定義のまま。注文時SLを先に越えた候補が、厳格114件中35件ある。原典の実例（特に2026-03-04の取消し）と照合して決める必要がある。
2. strict（A〜F）と actionable（60点+D）のどちらを候補の定義とするか未決定。判定関数は共通化されたが、既定入口は依然として異なる。
3. `oku100/cli.py backtest` はM15を読み込まず `run_backtest(..., m15=None)` を呼ぶ。この経路では順序が必要な約定足を保守的な曖昧SLとして扱う。M15付きの検証値とCLI出力は同一ではない。
4. 同じH1足で買い・売り注文がともに約定し得る場合、`_decide` は点数の高い方向を選ぶ。実際に約定した方向との対応は未解決である。
5. 修正後の候補数・勝率などの全期間再計数は、Claude報告の結果を読んだが、今回の確認では30〜40分かかる全期間再実行まではしていない。これらは採否根拠にしない。

## 次の順序

原典チャートの取消し実例を少数（まず2026-03-04を含む）で照合し、注文が無効になる条件を文章で固定する。その後にだけ、取消しを一つの変更として実装・テストする。数値成績による条件選択はしない。

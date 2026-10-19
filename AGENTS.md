# 100億j Codex Instructions

- **最初に読む正本**: Googleドライブ「100億」の `CONTEXT.md`・`PROGRESS.md`（PCからは `G:\マイドライブ\100億\`）。運用ルールの正本は同じフォルダの `運用ルール.md`。このAGENTS.mdと食い違ったら、そちらが正しい（2026-10-19 MANABU決定）。

- run_queue節約設定: Notion指示キューはSQL禁止・PowerShellがrows/viewで次の1件を選んでCodexへ渡し、通常はDriveのCONTEXT/PROGRESSと現在地末尾10行・決定ログだけを読み、コード変更時だけ全テストを行う。

## run_queueのCodex連続消化ルール（2026-10-18、MANABU指示）

- 各指示の作業前に、Googleドライブ「100億」（`G:\マイドライブ\100億\`）の
  `CONTEXT.md`・`PROGRESS.md` と、Notion「100億 > 現在地」を読む。
- 指示に書かれた定義・対象・例を固定する。結果を見て例を差し替え・追加・除外したり、
  定義や閾値を動かしたりしない。
- ファイル・ディレクトリの削除、`git push`、MT4実口座に関わる操作をしない。
- 各指示の理由付き報告は `C:\Users\user\Documents\100億j_share\` と
  Notion「100億 > 報告」の両方に置く。
- `run_queue` は1指示ごとに新しい `codex exec` セッションを使い、未着手が空になるまで
  作成順に連続処理する。90分以上止まった実行中指示は未着手へ戻し、メモに
  「中断のため再実行」と記録する。利用上限時も未着手へ戻してその回を終了する。
- 全テストは `python -m unittest discover -s tests -t .` で実行する。

## 役割分担：実行はCodex、指示と評価はClaude（2026-10-19、MANABU決定）

- **Codex（実行役）**: 指示キューの消化、原典解析、データ変換・品質確認、チャート生成、
  型別判定、バックテスト、集計、報告の作成。Codex内でも正解作成役・盲検判定役・採点役を分け、
  盲検判定役には正解データを渡さない。
- **Claude（監査役）**: 指示を書く（`100億j_share/指示_*.md` と Notion指示キューへの登録）、
  Codexの報告を原典への忠実性で評価する。Claudeは指示キューの行を実行せず、コード・データも変更しない。
- 指示の内容に疑問・矛盾・原典との食い違いがあれば、Codexは推測で進めず、状態を「要MANABU判断」にして
  メモに理由を書く（監査役が次の指示で解消する）。
- 監査役の評価は報告と正解表に基づく。Codexは、監査役が検証できるよう、条件・乱数シード・対象一覧・
  生データの置き場所を報告に必ず書く。

## サブエージェントへの委譲(2026-07-27追加、btc_all_articles.csv誤削除事故を受けて)

サブエージェントにタスクを委譲する際は、以下を必ずプロンプトに明示的に含めること。
「AGENTS.mdを読め」では不十分で、制約そのものを渡す。

- 事前承認済みの操作範囲
- 要確認の操作範囲(特に「削除は禁止。必要なら報告して停止せよ」)
- 委譲元がblindであるべき情報(正解データ等)に触れてはならない場合、その旨

サブエージェントの行動は委譲元の責任である。制約を渡さずに委譲した結果の
事故は、委譲元の管理不足として扱う。

## 外部アクセス依存データの保護(2026-07-27追加)

外部アクセス(Webクロール等)なしに再生成できないデータは、必ずgit管理下に
置くこと。ローカルデータのみから決定的に再生成できるファイルは対象外。

## 人間への質問の原則(2026-07-27追加)

人間に対して「画面に何が表示されたか」「どう見えたか」といった目視観察の報告を
求めてはならない。代わりに、以下を徹底する。

- すべての実行結果(標準出力・標準エラー)をログファイルに記録する
- 起動の成否はheartbeatファイル等で機械的に確認する
- 確認したいことがあれば、ログを自分で読んで判断する

人間に質問してよいのは、以下に限る。
- 判断・意思決定(どちらの方針で進めるか等)
- 承認が必要な操作(削除、公開範囲の変更等)
- 物理的に人間しかできない操作の依頼(`.bat`の初回起動、ブラウザ認証等)

「依頼」と「観察結果の報告要求」は別物である。起動を依頼するのは可、
その結果どう見えたかを聞くのは不可。

## 指示ファイルの確認(2026-07-26追加)

会話の開始時、および「指示確認」と言われた際は、
`C:\Users\user\Documents\100億j_share\` を確認し、未読の`指示_*.md`ファイルが
あれば読んでから作業を開始すること。

報告も同フォルダに`報告_YYYYMMDD_*.md`として書き出すこと
(チャットへの長文貼り付けではなく、ファイルで受け渡す)。

## 承認範囲(2026-07-26、MANABU承認)

以下は事前承認済み。実行前に都度の確認は不要でそのまま実行してよい:

1. `100oku-charts`リポジトリへのチャート画像push(`charts/`配下のPNGのみ、
   `.gitignore`の除外対象が`git status`に現れていないことを確認した上で。
   ファイル名は日付ベースのみ、条件名・閾値・帯ラベル・勝敗を含めない)
2. `100億j_share/`への報告ファイルの書き出し
3. 読み取り専用の操作全般(ファイル読み込み・集計・件数確認・統計計算)
4. `charts/`配下へのチャート画像の新規生成とコピー
5. `docs/pending_hypotheses.md`への追記(既存記述の削除・改変を伴わない追記のみ)

以下は事前承認の対象外。実行前に必ず停止して報告すること
(「取り返しがつかない」または「公開範囲が変わる」ため):

1. ファイル・ディレクトリの削除(`git rm`を含む)
2. リポジトリの可視性変更(Public/Private切り替え)
3. `charts/`以外を公開リポジトリに追加すること(`.md`・コード・CSV・PDFは
   内容にかかわらず要確認)
4. `.gitignore`の除外対象を減らす変更
5. 既存のdocs内容の削除・大幅な書き換え
6. MT4の実口座に関わる操作全般
7. force push、履歴の書き換え

判断に迷った場合、上記いずれにも明記がなく「取り返しがつくか」「公開範囲が
変わるか」のどちらかに引っかかるものは確認する側に倒す。ただし単に慎重を期す
ための確認は上記1〜5の日常作業では不要。

## 最優先事項:検証順序の絶対則(PH-30/PH-31の失敗から確定、2026-07-22)

全エージェント(Codexを含む)は、他のどのルールよりも先に以下を守ること。
詳細・経緯は `skills/100oku-ea-skill/SKILL.md`「検証規律(プロジェクト確定原則)」を参照
(このセクションは要点のみ。参照リンクを辿らなくても以下の2点は必ず守ること)。

- **数値結果だけでEA条件の採否を判断しない。** 定義の忠実性(原典チャートとの一致)を
  先に確認し、確定してから実装・統計検証に進む(定義の忠実性 → 実装 → 統計、の順序を
  逆にしない)。統計が支持していても、原典と一致していない点があればそう指摘する。
- **チャート画像が生成されたら、必ず目で確認する。** 数値レポートだけで判断を終えない。
  確認する際は必ず `docs/master_pre_chart_checklist.md` を先に開き、11項目に照らして
  見る(「見て気づく」のではなく「リストに照らして確認する」の順序)。

## Google Drive共有フォルダ(2026-07-26追加)

`C:\Users\user\Documents\100億j_share\` は、ユーザーがGoogle Drive経由で画像を直接確認する
ための軽量共有フォルダ。**チャート画像を新規生成したら、必ずこのフォルダの
`generated\` にもコピーを置くこと**(元のフォルダへの生成に加えて、こちらにも複製する。
移動ではなくコピー)。原典記事のチャート画像は `source_charts\` に置く。

## GitHubチャート共有リポジトリ(2026-07-26追加)

`C:\Users\user\Documents\100oku-charts\`(GitHub: `aimanabu9691-art/100oku-charts`、
public、`main`ブランチ)は、Claude(チャット側)が`raw.githubusercontent.com`経由で
チャート画像を直接確認するための公開リポジトリ。**チャートを新規生成したら、
`C:\Users\user\Documents\100oku-charts\charts\` にもコピーしてpushすること**
(元プロジェクト内には作らない。移動ではなくコピー)。

**絶対にpushしてはいけないもの**(`.gitignore`で除外済みだが、新規ファイル追加時も
必ず確認すること): `docs/codex_examples/`配下、原典ソースPDF・その抜粋要約、
EAソースコード(`*.mq4`/`*.ex4`/`*.mqh`)、`oku100/`・`scripts/`のPythonパイプライン、
`data/`配下のCSV、`docs/*.md`(pending_hypotheses.md・SKILL・チェックリスト類)、
MT4履歴ファイル・バックテスト結果JSON。**入れてよいのは生成済み4パネルチャート画像
(PNG)のみ**で、ファイル名にも条件名・閾値を含めないこと(例: `bandD`のような
分類ラベルは不可。日付ベースの命名にする)。

## Always Read First
Before starting work in this project, read these files:

- `docs/codex_rules.md`
- `docs/mt4_backtest_worklog.md`
- `docs/H4_knowledge_consolidation_spec_1.md`
- `docs/master_pre_chart_checklist.md`(チャート監査・候補チェックは、まずこのファイルを
  読んでから開始すること)

## Core Rules
- Do not modify existing EA, CSV, or Python files unless the user explicitly asks for that exact change.
- Prefer read-only inspection, aggregation, and reporting.
- Keep verification notes, worklogs, and project rules under `docs\`.
- Change only one variable at a time.
- Do not tune thresholds to match desired results. Report numbers only.
- Do not propose manual review of more than 2,000 candidates.

## Current Focus
MT4 backtest verification. Next major task: convert `data\h1.csv` to MT4 `.hst` format and compare BuyEA MT4 behavior against the Python baseline.

## Codex監査役の判定例(few-shot教材)

監査判定時は `docs/codex_examples/*/INDEX.md` を必ず参照すること。
各フォルダは原典のリアルトレード1件(通貨ペア_日付)で、INDEX.mdに
監査5項目(`docs/codex_auditor_checklist.md`)と画像の対応表がある。

判定例は今後追加される。参照時は特定フォルダ名を決め打ちせず、
`codex_examples/` 配下の全INDEX.mdを対象とすること。

- 命名規則: `{通貨ペア小文字}_{YYYYMMDD}` (例: usdjpy_20190612)

# AGENTS.md

Cursor Cloud Agents 向けの作業ルール。アプリ固有のルールはプロジェクト側で追記する。

## 編集禁止（読み取り専用）

- `docs/source-of-truth/` 配下はソース・オブ・トゥルース。AI は読んでよいが、編集・削除・リネーム・移動は禁止。
- フロントマターに `ai.editable: false`（または `ai_editable: false`）があるファイルも同様。
- 内容変更が必要なら Issue で人間に依頼し、自分では触らない。

## タスク管理

- タスクと完了基準は **GitHub Issue** のみ。着手前に対象 Issue を読む（`gh issue view`）。
- Issue の **Blocked by** に未完了の依存がある場合は着手しない。
- セッション引き継ぎは Issue / PR の本文とコメントで行う。リポジトリ内の progress ファイルは使わない。

## 完了の定義

- Issue のクローズは、`verifier` が Issue の **検証** 欄のコマンドを実行して通ったあとだけ。
- 自分で完了と主張した直後は `verifier` を起動する。

## 調査

- ウェブ調査は親が直接 scrape / WebFetch / Firecrawl せず、`web-reader` に委譲する。
- 調査が終わったら、親が `docs/web-reader/` にマークダウンを残す。`web-reader` は読み取り専用なので自分では書けない。Cursor 公式を `cursor-guide` で読んだ場合も同じ場所へ残す。
- ファイル名は `YYYY-MM-DD-短い英語slug.md`。claims / sources / gaps を残し、ページ全文は置かない。置き方は [docs/web-reader/README.md](docs/web-reader/README.md)。
- このディレクトリは調査メモであり正本ではない。実装の判断は ADR / ARCHITECTURE / source-of-truth に書く。

## Cursor Cloud specific instructions

- 依存関係は Build の `install`（`.cursor/install.sh`）で入れる。開発サーバーは無いので `start` / `terminals` は使わない。
- Python は uv。`uv pip` は禁止。`pyproject.toml` があるときは `uv run pytest` などで検証する。
- `OPENROUTER_API_KEY` は [Cloud Agents の Secrets](https://cursor.com/dashboard/cloud-agents) に Runtime Secret として置く。コミットしない。Cloud では Podman secret の代わりにこの環境変数を使う。
- データ本文は同梱しない。fetch は準備ステップであり、本ランは `data/` だけを読む。
- 既定の検証はライブ API を叩かない。有料呼び出しが必要な作業は Issue の検証欄に明示があるときだけ。

## CI バッジ

- CI ワークフロー（`.github/workflows/`）を追加・変更したら、README 先頭付近にそのワークフローの状況バッジを必ず出す。無ければ追加する。
- 例: `![CI](https://github.com/<owner>/<repo>/actions/workflows/<file>.yml/badge.svg)`

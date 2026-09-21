# Jev プロンプト実験

![CI](https://github.com/gnkm/jev-prompts/actions/workflows/ci.yml/badge.svg)

Jev に 3 つの課題を与え、精度の評価をおこなう。
課題解決にあたって、Jev にはいくつかのプロンプトを与え、プロンプトの効果を評価できるようにする。

成果物は CLI（Typer）と `results/` の markdown レポートである。結果の把握は markdown を読む。
図が必要な箇所は画像を生成してそのファイルから参照する。Web UI は提供しない。
表の処理は Polars を使う。

Python パッケージ `jev_prompts` の骨格（uv / pytest / Ruff / Typer / Polars）はある。CLI と集計の本実装は後続。
パッケージは `report → stats → metrics → runners → prompts → clients → data → config` の一方向レイヤで、Import Linter が逆向きの import を止める。
ケース台帳は `case_id` / split / gold / content_hash / 抽出シードを Polars で扱う。本文は同梱しない、fetch は後続。
GitHub Actions は Biome、pytest、Ruff、Import Linter、reuse lint を `main` と pull request で実行する。ライブ API は既定の CI に載せない。

## セットアップ

Python 3.12 と [uv](https://docs.astral.sh/uv/) を使う。`uv pip` は使わない。

```bash
uv python install 3.12
uv sync
```

テストと lint:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run lint-imports
uv run reuse lint
```

## データ

本文は同梱しない。`data/raw/` は gitignore し、配布元からの fetch は後続の Issue で足す。
Git に入るのはケース台帳（`data/cases/` の `case_id` / split / gold / content_hash / 抽出シード）だけである。
抽出は課題あたりランダム + 境界、gold で層化した dev / test を小さなフィクスチャで再現する。
テスト用の合成本文は実行時に組み立て、データセット本文はリポジトリに置かない。

## 比較用 LLM

比較用 LLM は GPT-5.6 Luna（条件 L1 / L2）と Claude Sonnet 5（条件 L3）。
評価設計書の L1 / L2 に L3 を足し、実験は 8 条件である。選定の正本は
[ADR-0002](docs/adr/competitor-llm.md)、実装上の境界は [ARCHITECTURE.md](ARCHITECTURE.md)。

| 条件 | モデル | モデル ID | 固定プロバイダ |
| --- | --- | --- | --- |
| L1 / L2 | GPT-5.6 Luna | `openai/gpt-5.6-luna` | OpenAI |
| L3 | Claude Sonnet 5 | `anthropic/claude-sonnet-5` | Anthropic |

OpenRouter で呼び、`provider.order` を上表のプロバイダに固定する。
`allow_fallbacks` は false、`require_parameters` は true、`data_collection` は deny。
エイリアスは使わない。

## 評価の統計

同じケースを条件 A 対 B1 のように 2 条件で比べるときは、当たり外れの差に McNemar、指標の幅にブートストラップ、複数回の判定に Holm を使う。解説は [docs/statistical-methods.md](docs/statistical-methods.md)、位置づけは [ARCHITECTURE.md](ARCHITECTURE.md) の統計節。

## コントリビューション

ブランチ命名とコミット規約は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## ライセンス

ディレクトリごとにライセンスが異なります。REUSE の SPDX 識別子をファイルに付け、全文は `LICENSES/` に置きます。検証は `uv run reuse lint` です。

- `src/`: MIT
- `prompts/`: CC0-1.0
- `results/`: CC-BY-4.0

その他のリポジトリファイル（テスト、ドキュメント、設定など）は MIT です。
GitHub のサイドバーはルートの MIT のみを表示しますが、MIT が全体に及ぶわけではありません。
元データは同梱しておらず、各データセットのライセンスは `DATA_LICENSES.md` を参照ください。

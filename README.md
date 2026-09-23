# Jev プロンプト実験

![CI](https://github.com/gnkm/jev-prompts/actions/workflows/ci.yml/badge.svg)

## 目的

[Jev 向けのプロンプト作法](docs/source-of-truth/jev-prompt-guide.md)が、
精度と confidence にどれだけ効くかを測る。

## 課題概要

3 種類の課題を準備した。
これらに異なるプロンプトを与え、その影響を測定した。

| 課題 | データセット | 課題概要 |
| --- | --- | --- |
| Choice(順序なし多値分類) | [BANKING77](https://huggingface.co/datasets/PolyAI/banking77) | 銀行の顧客メッセージから、77 種の問い合わせ意図を判定する |
| Score(順序あり分類) | [Amazon ESCI](https://github.com/amazon-science/esci-data) | 検索語と商品から、一致・代替・補完・無関係の関連度を判定する |
| Noul(二値分類) | [SMS Spam Collection](https://archive.ics.uci.edu/dataset/228/sms+spam+collection) | SMS 本文から、スパムかどうかを判定する |

## 結論

[Jev 向けのプロンプト作法](docs/source-of-truth/jev-prompt-guide.md)は、どの課題でも同じように正しいわけではない。
ガイドどおりに書けば精度が上がる、とは言えず、効く要素は課題のタイプで分かれた。

| 課題 | 効いた要素 | 効かなかった要素 |
| --- | --- | --- |
| Choice | なし。ガイドに沿っても LLM 流でも精度はほぼ同じ | 選択肢同士の区別、質問文、判断に関係ない入力 |
| Score | 段階の定義。隣り合う段階を状況として区別して書く | 質問文、判断に関係ない入力 |
| Noul | 質問を否定形にしない | 条件の定義の細部、判断に関係ない入力 |

ガイドが重視する confidence は、ガイドに沿ったプロンプトでも確信度の高い誤答を減らさなかった。
素朴な LLM と同等以上の精度をより低いコストと遅延で出せるかは、本測定では判定できなかった。

数値・信頼区間・誤答の内訳は [results/report.md](results/report.md)。

## ドキュメントガイド

| 目的 | ドキュメント |
| --- | --- |
| プロンプトの効果を知る | [results/report.md](results/report.md) |
| 実験を手元で再現する | 本ドキュメントの「再現」セクション |
| 本システムを開発する | [ARCHITECTURE.md](ARCHITECTURE.md) と [CONTRIBUTING.md](CONTRIBUTING.md) |

主指標と合格ラインは [評価設計書](docs/source-of-truth/design-of-evaluation.md)。
プロンプト条件の差分は [prompts/README.md](prompts/README.md)。
比較用 LLM の選定は [ADR-0002](docs/adr/competitor-llm.md)。

## 成果物

- 課題 3 式（Choice / Score / Noul）: `data/cases/choice.jsonl`、`data/cases/score.jsonl`、`data/cases/noul.jsonl`。課題の定義は評価設計書
- 実験結果: `results/report.md`（本文は結果を見て書く）、`results/tables.md`（表）、`results/figures/`
- プロンプト: `prompts/`
- 推論用コード: `src/jev_prompts/clients/`、`src/jev_prompts/runners/`
- 精度評価用コード: `src/jev_prompts/metrics/`、`src/jev_prompts/stats/`、`src/jev_prompts/report/`
- テストコード: `tests/`
- CI 設定: `.github/workflows/ci.yml`
- 使用方法のドキュメント: この README の再現、[ARCHITECTURE.md](ARCHITECTURE.md)、[CONTRIBUTING.md](CONTRIBUTING.md)
- ライセンス全文: `LICENSES/`。ディレクトリとの対応は `REUSE.toml`。データセットの帰属は [DATA_LICENSES.md](DATA_LICENSES.md)

## 再現方法

Python 3.12 と [uv](https://docs.astral.sh/uv/) を使う。

```bash
uv python install 3.12
uv sync
```

コードが読むキーは環境変数 `OPENROUTER_API_KEY` だけである。リポジトリに置かない。
`.env` は gitignore 済みで、プログラムは `.env` を読まない。

本文とは、モデルに渡す入力である。Choice は顧客のクエリ、Score は検索語と商品のタイトル・説明、Noul は SMS のメッセージである。正解ラベル（gold）ではない。
本文は同梱しない。`data/raw/` は gitignore する。Git に入る台帳は `data/cases/` の識別子、split、gold、content_hash、抽出シードだけである。

準備と実行を混ぜない。配布元からの取得はクローン後（または台帳を変えるとき）に一度だけ行い、本ランは `data/` だけを読む。
ハッシュが台帳と一致しない、台帳が無い、または空なら失敗する。暗黙の再取得はしない。

```bash
# 準備（Hugging Face / GitHub / UCI から data/raw へ。API キーは不要）
uv run python -m jev_prompts fetch
# 同等の薄い入口: uv run python scripts/fetch_data.py

# 台帳抽出（本文は書かない。課題あたり test 60 / dev 40）
uv run python -m jev_prompts extract
# 同等の薄い入口: uv run python scripts/extract_cases.py

# 実行（OPENROUTER_API_KEY と本文が要る。無ければ非ゼロ終了）
uv run python -m jev_prompts preflight --split test
uv run python -m jev_prompts run --split test
uv run python -m jev_prompts fanout
uv run python -m jev_prompts prices

# 表と図の再生成（report.md は上書きしない。API キーは不要）
uv run python -m jev_prompts report
```

キーが要るのは `preflight` / `run` / `fanout` / `prices`。要らないのは `fetch` / `extract` / `report`。
ライブ API は既定の CI に載せない。ランナー、ログ、エンドポイントの境界は [ARCHITECTURE.md](ARCHITECTURE.md)。

## ライセンス

ディレクトリごとにライセンスが異なります。REUSE の SPDX 識別子をファイルに付け、全文は `LICENSES/` に置きます。検証は `uv run reuse lint` です。

- `src/`: MIT
- `prompts/`: CC0-1.0
- `results/`: CC-BY-4.0

その他のリポジトリファイル（テスト、ドキュメント、設定など）は MIT です。
GitHub のサイドバーはルートの MIT のみを表示しますが、MIT が全体に及ぶわけではありません。
元データは同梱しておらず、各データセットのライセンスは `DATA_LICENSES.md` を参照ください。
ブランチ命名とコミット規約は [CONTRIBUTING.md](CONTRIBUTING.md)。

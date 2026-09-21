<!--
SPDX-FileCopyrightText: 2026 gnkm

SPDX-License-Identifier: CC-BY-4.0
-->

# 測定結果

`results/` に置くのは測定値と、そこから作った markdown / 図だけである。入力本文は置かない。
公開行（`PublishedRecord`）に入力本文のフィールドは無い。再集計用のフルログは `data/logs/` に置き、このディレクトリにはコピーしない。
`figures/` の SVG は matplotlib の生成物であり、Biome の対象外である。

`python -m jev_prompts report`（または `scripts/write_report.py`）が `published.jsonl` を読み、`report.md` と `figures/` を書く。中身は指標マトリクス、較正（表と reliability diagram）、コスト × 精度（表と散布図）である。生成 markdown から図ファイルへリンクする。Web UI は無い。

`python -m jev_prompts findings` が同じ公開行から H1〜H4 の判定と A の誤答内訳を `findings.md` に書く。`python -m jev_prompts prices` が測定日の単価を `prices.md` に書く。`a_error_review.jsonl` は目視した task / case_id / 失敗モードだけである。いずれも入力本文は置かない。

これらは TypeSafe の API が返した出力をこちらで集計したもので、CC BY 4.0 で公開する。
評価の再現検証のための公開であり、モデルの学習・蒸留用途を意図しない。

データセット本文の扱いと帰属はリポジトリルートの `DATA_LICENSES.md` を参照する。

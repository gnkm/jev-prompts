---
title: BANKING77 の 77 意図ラベル
queried at: 2026-09-21
agent: web-reader
query: PolyAI BANKING77 の公式 77 カテゴリ名と、文書化された混同ペア。
---

# BANKING77 の 77 意図ラベル

調査日 2026-09-21。正本ではなく、その時点の公開データセット定義の記録。
カタログの意図名・件数はこれに合わせる。説明文は設計書に従いカタログ側で書く。

## claims

- 公式のカテゴリ配列は 77 件。`Refund_not_showing_up` は先頭 R が大文字、`reverted_card_payment?` は末尾に `?` がある。
- PolyAI の `categories.json` の並びと、Hugging Face の ClassLabel（アルファベット順、0=`activate_my_card`）は文字列集合が同じで、順序だけが違う。
- Hugging Face データセットカードに混同ペア表は無い。
- 論文側の例: reverted top-up と failed top-up、`card_arrival` と `card_delivery_estimate`。
- 設計書の `transaction_fee_charged` は公式 77 に無い。近い公式名は `transfer_fee_charged`。

## sources

- https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/categories.json
- https://huggingface.co/datasets/PolyAI/banking77
- https://huggingface.co/papers/2003.04807
- https://aclanthology.org/2022.insights-1.19.pdf

## gaps

- Casanueva et al. 2020 と Edwards et al. 2022 の混同表の PDF 全文は未取得。
- 公式配布物に 77 意図の相互区別説明は無い。

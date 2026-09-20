# データセットのライセンスと出典

このリポジトリは、評価に用いた 3 つの公開データセットの**本文を同梱していません**。
`scripts/fetch_data.py` が各配布元から取得し、`data/cases/*.jsonl` に記録したケース ID
とハッシュで同一のサブセットを再現します。

`results/` に含まれるのは測定値のみで、入力本文は含みません。

---

## 1. BANKING77

| 項目 | 内容 |
| --- | --- |
| 配布元 | PolyAI — https://huggingface.co/datasets/PolyAI/banking77 |
| ライセンス | CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/) |
| 規模 | オンラインバンキングの問い合わせ 13,083 件、77 意図、英語 |
| 用途 | 課題 1（Choice：意図分類） |

**引用**

> Iñigo Casanueva, Tadas Temčinas, Daniela Gerz, Matthew Henderson, Ivan Vulić.
> *Efficient Intent Detection with Dual Sentence Encoders.*
> Proceedings of the 2nd Workshop on NLP for ConversationalAI, ACL 2020.

**このリポジトリで加えた変更**

- テストスプリットから 100 件を抽出（ランダム 50 件＋混同しやすい意図ペア 50 件）
- 意図ラベルを段階番号ではなく選択肢名としてそのまま使用
- 本文の改変なし。本文の再配布なし

---

## 2. Shopping Queries Dataset (Amazon ESCI)

| 項目 | 内容 |
| --- | --- |
| 配布元 | Amazon Science — https://github.com/amazon-science/esci-data |
| ライセンス | Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0) |
| 規模 | クエリ×商品の関連度判定。英語・日本語・スペイン語 |
| 用途 | 課題 2（Score：関連度 4 段階） |

**引用**

> Chandan K. Reddy, Lluís Màrquez, Fran Valero, Nikhil Rao, Hugo Zaragoza,
> Sambaran Bandyopadhyay, Arnab Biswas, Anlu Xing, Karthik Subbian.
> *Shopping Queries Dataset: A Large-Scale ESCI Benchmark for Improving Product Search.*
> arXiv:2206.06588, 2022.

**このリポジトリで加えた変更**

- 英語（locale = `us`）のみを使用
- 100 件を抽出（ランダム 50 件＋ S / C のペア 50 件）
- 関連度ラベルを段階番号に対応（I=0, C=1, S=2, E=3）。KDD Cup の gain 順に従い
  E > S > C > I を順序尺度として扱う。この前提は厳密には自明ではない
- 商品情報は `title` と `description` のみを使用（条件 C を除く）
- 本文の改変なし。本文の再配布なし

データ本体を同梱しないため、Apache-2.0 のライセンス全文と NOTICE ファイルは
本リポジトリに含めていない。

---

## 3. SMS Spam Collection

| 項目 | 内容 |
| --- | --- |
| 配布元 | UCI Machine Learning Repository — https://archive.ics.uci.edu/dataset/228/sms+spam+collection |
| ライセンス | CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/) |
| 規模 | SMS 5,574 件、spam / ham の 2 値ラベル、英語 |
| 用途 | 課題 3（Noul：yes/no 判定） |

**引用**

> Tiago A. Almeida, José María Gómez Hidalgo, Akebo Yamakami.
> *Contributions to the Study of SMS Spam Filtering: New Collection and Results.*
> Proceedings of the 2011 ACM Symposium on Document Engineering (DOCENG'11).
>
> データセット: Almeida, T. and Gómez Hidalgo, J. (2011). SMS Spam Collection.
> UCI Machine Learning Repository.

**このリポジトリで加えた変更**

- 100 件を抽出（ランダム 50 件＋境界ケース 50 件）
- 本文の改変なし。本文の再配布なし

**取り扱い上の注意**

本データセットは実在の利用者が受信した SMS を含む。記事やドキュメントに実例を
掲載する際は、電話番号・URL・氏名を伏せ字にすること。`results/` には本文を
含めていないため、この措置は掲載物のみに適用される。

---

## 測定結果の扱い

`results/` 以下の測定値は、TypeSafe の API が返した出力をこちらで集計したもので、
CC BY 4.0 で公開している。詳細は `results/README.md` を参照。

これらは**評価の再現検証のための公開であり、モデルの学習・蒸留用途を意図しない**。

---

## 確認した日付

上記のライセンス表記は 2026-09-21 時点で各配布元のライセンス記載を確認したもの。
配布元が表記を変更している可能性があるため、再利用の際は原典を確認すること。

## 連絡先

記載の誤りを見つけた場合は Issue を立ててください。

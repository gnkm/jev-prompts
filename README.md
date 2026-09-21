# Jev プロンプト実験

Jev に 3 つの課題を与え、精度の評価をおこなう。
課題解決にあたって、Jev にはいくつかのプロンプトを与え、プロンプトの効果を評価できるようにする。

成果物は CLI（Typer）と `results/` の markdown レポートである。結果の把握は markdown を読む。
図が必要な箇所は画像を生成してそのファイルから参照する。Web UI は提供しない。
表の処理は Polars を使う。

## 評価の統計

同じケースを条件 A 対 B1 のように 2 条件で比べるときは、当たり外れの差に McNemar、指標の幅にブートストラップ、複数回の判定に Holm を使う。解説は [docs/statistical-methods.md](docs/statistical-methods.md)、位置づけは [ARCHITECTURE.md](ARCHITECTURE.md) の統計節。

## コントリビューション

ブランチ命名とコミット規約は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## ライセンス

ディレクトリごとにライセンスが異なります。具体的には以下のとおりです。

- src/: MIT
- prompts/: CC0 1.0
- results/: CC BY 4.0

GitHub のサイドバーはルートの MIT のみを表示しますが、MIT が全体に及ぶわけではありません。
元データは同梱しておらず、各データセットのライセンスは `DATA_LICENSES.md` を参照ください。

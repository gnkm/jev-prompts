# web-reader 調査メモ

外部ドキュメントを読んだ結果の置き場。正本ではない。実装の判断は
`docs/source-of-truth/`、`docs/adr/`、`ARCHITECTURE.md` に書く。

## 運用

1. 親は scrape / WebFetch / Firecrawl を直接使わず、`web-reader` に委譲する。
2. `web-reader` は読み取り専用なので、このディレクトリへは書かない。
3. 親は返答を受け取ったら、このディレクトリにマークダウンを残してから実装判断に進む。
4. Cursor 公式ドキュメントを `cursor-guide` で読んだ場合も、同じ場所に残す。

## ファイル名

`YYYY-MM-DD-短い英語slug.md`

同じテーマを再調査したら日付の新しいファイルを足す。古いファイルは消さず、
新しいほうの冒頭で「いつ時点の調査を更新したか」を書く。

## 各ファイルに書くこと

- フロントマター: `title` / `queried at` / `agent` / `query`
- `claims`: 確認できた事実
- `sources`: 出典 URL
- `gaps`: 確認できなかったこと
- ページ全文や生 markdown は置かない

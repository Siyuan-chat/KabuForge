---
doc_id: changelog
version: 1
locale: ja_JP
---

# 変更履歴

## 未公開：現在のソースのライセンスと GitHub ナビゲーション

プロジェクト所有の資料にはコミット `3bdbb7e1b68de53fcb243abb92cd851801dcb7be` から AGPL-3.0-only を適用します。
元の MIT 通知と外部貢献の出所を NOTICE / PROJECT_LICENSING.md に保持します。
既存 v0.1.0-rc.1、v0.1.0 Release、tag、wheel/sdist 添付物とチェックサムは
MIT のまま変更しません。パッケージ版は 0.1.0rc1 のままで、ローカルビルドは
検証専用です。今後の AGPL 配布には新しい版が必要です。実行時依存と API は
変更しません。三言語の機能証拠、研究境界、引用、ナビゲーション、コミュニティ
フォームと文書検査を追加します。字標は固定された OFL Noto Sans のアウトラインへ
変更しました。鉄砧は保持しています。フォントソフトは OFL のままで同梱しません。

<!-- section:contract -->
## 契約

## 0.1.0-rc.1

local package CLI、制限 MCP adapter、型付け因子・戦略 registry、local Agent audit receipt、既定 R0/R1 catalog、明示的 R2 paper opt-in、予約済みで無効な R3 approval/order interface を導入し、公開 RC は公開 package と非公開のローカル workspace を分離し、公開ファクターの source identity を固定します。

<!-- section:evidence -->
## 根拠

既知の制限：Agent に real broker submission はありません。`--expose-reserved-external` は無効 stub のみを露出します。job は in-process daemon thread であり、再起動時に QUEUED/RUNNING job は `KF_JOB_INTERRUPTED` を伴う `FAILED` になり、自動 recovery/replay はありません。lookahead check は timestamp gate のみです。

# AGENTS.md

## エージェントへの作業ルール

### 環境・実行

- Python は常に `./venv/bin/python3` を使う
- 依存追加後は `requirements.txt` に反映する
- `.env` は **絶対に読み込み・確認・変更・出力を行わないこと**（ユーザーから毎回の指示がなくても、このルールを事前情報として厳守する）
- 変更を行った際は、**必ず関連する doc（ドキュメント）をデフォルトで更新すること**
- `cache/` ・ `data/` 配下の実データは **変更しない**

---

## 作業開始前のチェック

```bash
# 構文エラーがないことを確認
./venv/bin/python3 -m py_compile src/*.py *.py
```

---

## コード変更時の鉄則

### 1. 戻り値の型を変えない

既存関数の戻り値の型を変える場合は、**呼び出し箇所をすべて同時に修正する**。
タプルを返す関数をdictに変えると、アンパックしている呼び出し側が即座に壊れる。

### 2. 破壊的変更の前にバックアップ

既存ロジックを大きく書き換える場合は、元の関数を `_legacy` サフィックスで残してから新実装を追加する。

### 3. フォールバックを壊さない

API呼び出しのフォールバックチェーン（メイン→サブ→キャッシュ）は、
途中を変更しても**全チェーンが動作すること**を確認する。

---

## PR・コミット前のチェックリスト

```bash
# 1. 構文エラーなし
./venv/bin/python3 -m py_compile src/*.py *.py

# 2. 想定する処理が通る（dry-runがあれば使う）
./venv/bin/python3 <entry_point>.py --dry-run

# 3. 新規モジュールにdocstringがある
grep -L '"""' src/*.py
```

---

## よくあるバグパターンと対処

| エラーメッセージ | 原因 | 対処 |
| --- | --- | --- |
| `'str' object has no attribute 'get'` | タプルをdictとして扱っている | アンパック `x, y = func()` に修正 |
| `ArbitraryTypeWarning: any is not a Python type` | `any`（組み込み関数）を型ヒントに使っている | `from typing import Any` に変更 |
| `FutureWarning: default value changed` | ライブラリのデフォルト変更 | 該当引数を明示的に指定する |
| `429 RESOURCE_EXHAUSTED` | API無料枠の上限 | フォールバックAPIを使う／キャッシュを確認する |
| `413 Request Too Large` | ペイロードがAPI上限を超過 | テキストを削減してから送る |

---

## ドキュメント更新ルール

コードを変更した場合、以下も更新すること:

- 関数シグネチャ変更 → `docs/` または docstring を更新
- 新しい環境変数追加 → `.env.example` に追記
- 新しい依存追加 → `requirements.txt` に追記
- CLIの引数変更 → `README.md` の使い方セクションを更新

---

## プロジェクト固有のコンテキスト

このプロジェクト（stock_analyze）の詳細は以下を参照:

- アーキテクチャ: `docs/architecture.md`
- APIの優先順位・フォールバック: `docs/api-guide.md`
- 既知の問題: `docs/troubleshooting.md`

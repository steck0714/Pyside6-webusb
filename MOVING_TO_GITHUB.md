# このzipをGitHubのチェックアウトへ移す手順

このzip(`v.0.0.5b3/`)は**PyPI配布物の中身**であり、`.github/workflows/`のような
GitHub専用ファイルは含まれていません(そもそもPyPIのsdist/whlには不要なため)。
実際の運用(このzipを解凍してGitHub側のコードへ上書きしていく)を想定した、
一度きりの手順メモです。

## 1. 既存チェックアウトへ同期する

`.git/`や`.github/`など、このzipに含まれないものを消さないよう、`rsync`で
差分だけ反映するのが安全です(単純な上書きコピーは、このzipに無いファイル
——`.github/workflows/`等——を消してしまう心配はありませんが、`.git/`を
`--exclude`し忘れると事故のもとです)。

```bash
rsync -av --exclude='.git' --exclude='.github' \
    ./v.0.0.5b3/ /path/to/your/pyside6-webusb-checkout/
```

## 2. 新規追加ファイルを確認する

このリリースで新しく増えたファイルは以下の4つです。`git status`で
`Untracked files`として出るはずなので、`git add`を忘れないでください。

- `.gitignore`(今回初めて同梱。詳細はCHANGELOG参照)
- `src/pyside6_webusb/i18n.py`
- `tests/test_i18n.py`
- `tests/test_chooser_dialog.py`
- `scripts/verify_test_suite.py`
- 本ファイル(`MOVING_TO_GITHUB.md`)

## 3. コミット・タグ

RELEASE_NOTES.mdの運用どおり、GitHub側のタグは`v0.0.5b3`、`_version.py`/
`pyproject.toml`側は`0.0.5.post7`です(この2つが一致していなくて正しい、
という前提そのものはRELEASE_NOTES.mdの過去のズレ修正の経緯を参照)。

```bash
git add -A
git commit -m "v0.0.5b3 (0.0.5.post7): i18n(en/ja/zh)、extra_guard_js、バグ修正2件"
git tag v0.0.5b3
git push && git push --tags
```

## 4. コミット前に一度、動作確認スクリプトを走らせる

```bash
python scripts/verify_test_suite.py
```

pytest一括実行だけでなく、各`tests/test_*.py`の直接実行・Node・tscもまとめて
確認します(詳細はCHANGELOGの`scripts/verify_test_suite.py`の項目を参照)。

## 5. `native/pyside6_webusb_accel/`(Rust拡張)を触っている場合

今回`Cargo.toml`のpyo3を`0.27.2`→`0.29.0`へ上げました
(GHSA-chgr-c6px-7xpp/GHSA-36hh-v3qg-5jq4への対応、CHANGELOG参照)。
**この変更はこの環境ではビルド確認できていません**(手元のrustcが1.75.0で、
pyo3-ffi 0.29.0の要求するrustc>=1.83に届いていないため)。GitHub Actions側の
Rustツールチェーン、または手元の`rustup`環境で一度

```bash
cd native/pyside6_webusb_accel && cargo build --release
# もしくは
maturin develop
```

を実行し、問題なくビルドできることを確認してから他のブランチへ反映してください。

## 6. GitHubのCode scanning alertsで見せてもらった2件について

`.github/workflows/restore-pypi.yml`と`.github/workflows/github-actions-publish-pypi.yml`の
「Workflow does not contain permissions」(CWE-275)は、このzipに実体が無いため
直接修正できていません。どちらも、ワークフロー冒頭(またはジョブ単位)に

```yaml
permissions:
  contents: read
```

を追加するだけで解消するはずです(PyPIへのアップロードをTrusted Publishing/OIDC
経由に変えている場合のみ、追加で`id-token: write`が要ります)。実際の2ファイルを
共有してもらえれば、こちらで直接編集して返せます。

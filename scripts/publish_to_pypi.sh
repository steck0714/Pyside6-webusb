#!/usr/bin/env bash
# dist/ 内の pyside6-webusb 全バージョンを PyPI (または --test で TestPyPI) へ
# アップロードするためのスクリプトです。APIトークンはこの場で入力してもらい、
# ファイルには保存しません。
set -euo pipefail
cd "$(dirname "$0")"

REPO_URL="https://upload.pypi.org/legacy/"
REPO_NAME="PyPI"
if [[ "${1:-}" == "--test" ]]; then
    REPO_URL="https://test.pypi.org/legacy/"
    REPO_NAME="TestPyPI"
fi

if ! python3 -m twine --version >/dev/null 2>&1; then
    echo "twine が見つかりません。先に次を実行してください: pip install --upgrade twine"
    exit 1
fi

echo "アップロード先: ${REPO_NAME} (${REPO_URL})"
echo "対象ファイル数: $(ls dist/*.whl dist/*.tar.gz 2>/dev/null | wc -l | tr -d ' ')"
read -r -s -p "PyPI APIトークン (pypi-... / 入力は非表示): " PYPI_TOKEN
echo
if [[ -z "${PYPI_TOKEN}" ]]; then
    echo "トークンが空です。中止します。"
    exit 1
fi

python3 -m twine upload \
    --repository-url "${REPO_URL}" \
    --username "__token__" \
    --password "${PYPI_TOKEN}" \
    --skip-existing \
    dist/*.whl dist/*.tar.gz

echo "完了しました。${REPO_NAME} 上のプロジェクトページを確認してください。"

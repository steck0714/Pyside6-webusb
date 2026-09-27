#!/usr/bin/env pwsh
<#
.SYNOPSIS
    dist/ 内の pyside6-webusb 全バージョンを PyPI (または -Test で TestPyPI) へ
    アップロードします。

.DESCRIPTION
    🆕 v0.0.6: scripts/publish_to_pypi.sh (bash版) のPowerShell移植。本パッケージの
    実機検証(checklog.md/checklog2.md)はWindows実機も含むため、bash/WSL/Git Bash
    に頼らずWindowsのネイティブなシェルだけで公開作業を完結できるようにする狙い。
    ロジック(twineの有無確認 → 対象ファイル数の表示 → APIトークンを非表示入力 →
    twine upload --skip-existing)はbash版と完全に同じにしてあり、どちらを使っても
    結果は変わらない。

    APIトークンはこの場で入力してもらい、ファイルには一切保存しません
    (bash版の`read -s`と同じ考え方——PowerShellでは`Read-Host -AsSecureString`)。

.PARAMETER Test
    指定するとTestPyPI (test.pypi.org) へアップロードします。省略時は本番のPyPIへ。

.EXAMPLE
    pwsh ./scripts/publish_to_pypi.ps1
    pwsh ./scripts/publish_to_pypi.ps1 -Test
#>
param(
    [switch]$Test
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if ($Test) {
    $RepoUrl = "https://test.pypi.org/legacy/"
    $RepoName = "TestPyPI"
} else {
    $RepoUrl = "https://upload.pypi.org/legacy/"
    $RepoName = "PyPI"
}

# 🔍 bash版と同じく`python3`ではなく`python`を使う: Windows版Pythonの公式
# インストーラは既定で`python`だけをPATHへ登録し、`python3`という名前のコマンドは
# 通常存在しない(`py`ランチャーはあるが、こちらは`python`で揃えた方が
# READMEの他のWindows向け手順と一貫する)。
python -m twine --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "twine が見つかりません。先に次を実行してください: pip install --upgrade twine"
    exit 1
}

Write-Host "アップロード先: $RepoName ($RepoUrl)"
$distFiles = @(Get-ChildItem -Path "dist" -Filter "*.whl" -ErrorAction SilentlyContinue) +
             @(Get-ChildItem -Path "dist" -Filter "*.tar.gz" -ErrorAction SilentlyContinue)
Write-Host "対象ファイル数: $($distFiles.Count)"

$secureToken = Read-Host -Prompt "PyPI APIトークン (pypi-... / 入力は非表示)" -AsSecureString
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $PypiToken = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
} finally {
    # 🛡️ SecureStringから平文へ変換するために確保したアンマネージドメモリは
    # 明示的に解放する(.NETのSecureString APIの定石。解放を怠ると平文の
    # トークンがプロセスのメモリ上に残り続ける時間が延びてしまう)。
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

if ([string]::IsNullOrEmpty($PypiToken)) {
    Write-Host "トークンが空です。中止します。"
    exit 1
}

if ($distFiles.Count -eq 0) {
    Write-Host "dist/ に .whl / .tar.gz が見つかりません。先にビルドしてください (例: python -m build)。"
    exit 1
}

# 🔍 bash版は`dist/*.whl dist/*.tar.gz`とグロブをそのまま渡している(bashシェル
# 自身が展開してからtwineへ渡す)。PowerShellが外部コマンド(python経由のtwine)へ
# 渡す引数中のワイルドカードを常に展開するとは限らない——挙動をシェルや
# twine自身の内部グロブ処理に委ねず、上で既に列挙済みの$distFilesの実際の
# フルパスをそのまま渡すことで、bash版と実質的に同じ「dist内の.whl/.tar.gzを
# 全部」という意味を確実にする。
python -m twine upload `
    --repository-url $RepoUrl `
    --username "__token__" `
    --password $PypiToken `
    --skip-existing `
    $distFiles.FullName

Write-Host "完了しました。$RepoName 上のプロジェクトページを確認してください。"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_test_suite.py
=====================
🆕 v0.0.5b3: 「このリポジトリのテストファイル自体がちゃんと機能しているか」を
一括確認するためのヘルスチェックスクリプト。

なぜ必要か: `pytest tests/` が緑になることと、README/CHANGELOGが謳う
「`python tests/test_X.py` の直接実行でも動く」が本当に成り立っていることは、
別々の確認が要る。実際、tests/test_virtual.py は他の全テストファイルが持つ
sys.path.insert(...)のブートストラップを欠いたまま(=pytest実行時はconftest.py
が肩代わりするため誰も気づかない状態で)0.0.5.post6まで存在し続けていた
(v0.0.5b3で修正 — 本CHANGELOG/コミット参照)。このスクリプトはそのクラスの
「pytestでは緑だが実際には壊れている」を機械的に検出する。

想定される使い方(GitHubのチェックアウトへ移した直後、コミット前の最終確認として):
    python scripts/verify_test_suite.py
    python scripts/verify_test_suite.py --save-report verify_test_suite_report.json

確認する項目:
  1. 実行環境そのもの(PySide6/pyusb/libusb等) -- pyside6_webusb.diagnostics経由。
  2. pytest一括実行(tests/ + security_audit/) -- 通常のCI相当の確認。
  3. tests/配下の各test_*.pyの「python file.py」による直接実行 -- pytest経由では
     見えない、上記のクラスの問題を検出する。pytest.importorskipをモジュール
     トップレベルで使っているファイル(例: test_rust_accel.py -- Rust拡張が
     未ビルドの環境ではpytest経由でしか綺麗にスキップできない設計)は自動検出して
     この確認の対象外にする(失敗ではなく「pytest専用」として区別する)。
  4. tests/test_polyfill.js (Node.js) -- nodeが無い環境ではスキップとして扱う。
  5. types/ 配下のTypeScript型定義チェック(tsc --strict --noEmit) -- tscが
     無い環境ではスキップとして扱う。

終了コード: 全項目がPASS(またはツール不在によるやむを得ないSKIP)なら0、
1つでも真の失敗があれば1。CIの最終ゲートとしてそのまま使える想定。
"""
import argparse
import json
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TESTS_DIR = os.path.join(REPO_ROOT, "tests")
SECURITY_AUDIT_DIR = os.path.join(REPO_ROOT, "security_audit")
TYPES_DIR = os.path.join(REPO_ROOT, "types")
SRC_DIR = os.path.join(REPO_ROOT, "src")


def _run(cmd, cwd=None, env=None, timeout=180):
    """subprocessをまとめて実行し、(returncode, stdout+stderr結合, elapsed_sec)を返す。
    ツール自体が無い(FileNotFoundError)場合はreturncode=Noneを返す
    -- 「失敗」と「そもそも呼べない」を呼び出し元で区別できるようにするため。"""
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, env=env, timeout=timeout,
            capture_output=True, text=True,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or ""), time.monotonic() - t0
    except FileNotFoundError:
        return None, f"コマンドが見つかりません: {cmd[0]}", time.monotonic() - t0
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        return -1, out + f"\n[TIMEOUT after {timeout}s]", time.monotonic() - t0


def _tool_available(name):
    from shutil import which
    return which(name) is not None


def _is_pytest_only(path):
    """モジュールのトップレベル(関数やクラスの中ではなく、行頭に字下げが無い
    箇所)でpytest.importorskip/pytest.skipを呼んでいるファイルは、素のpython
    実行では(そのpytest専用の例外がモジュールimport自体を止めてしまうため)
    綺麗にスキップできない設計だと判断し、直接実行チェックの対象から外す
    (test_rust_accel.py用に導入したが、将来似た作りのファイルが増えても
    手動でリストを更新せずに済むよう、ハードコードではなくこの簡易
    ヒューリスティックで判定する)。"""
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
    except OSError:
        return False
    for line in src.splitlines():
        if line.startswith((" ", "\t")):
            continue  # 字下げされている = 関数/クラス内のスキップなので対象外
        if "pytest.importorskip" in line or "pytest.skip(" in line:
            return True
    return False


def check_environment():
    print("=" * 70)
    print("[1/5] 実行環境の診断 (pyside6_webusb.diagnostics)")
    print("=" * 70)
    sys.path.insert(0, SRC_DIR)
    try:
        from pyside6_webusb.diagnostics import environment_report, format_environment_report
    except Exception as e:
        print(f"  診断モジュール自体のimportに失敗: {e}")
        return {"name": "environment", "status": "FAIL", "detail": str(e)}
    report = environment_report()
    print(format_environment_report(report))
    status = "FAIL" if report["problems"] else "PASS"
    return {"name": "environment", "status": status, "report": report}


def check_pytest_suite():
    print()
    print("=" * 70)
    print("[2/5] pytest一括実行 (tests/ + security_audit/)")
    print("=" * 70)
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    code, output, elapsed = _run(
        [sys.executable, "-m", "pytest", "tests/", "security_audit/", "-q"],
        cwd=REPO_ROOT, env=env, timeout=300,
    )
    print(output.strip())
    if code is None:
        return {"name": "pytest", "status": "SKIP", "detail": "pytest not installed", "elapsed": elapsed}
    return {"name": "pytest", "status": "PASS" if code == 0 else "FAIL", "returncode": code, "elapsed": elapsed}


def check_direct_execution():
    print()
    print("=" * 70)
    print("[3/5] 各tests/test_*.pyの直接実行 (python tests/test_X.py)")
    print("=" * 70)
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)  # あえて未設定から始め、各ファイル自身の
    # オフスクリーンフォールバックが本当に機能しているかも一緒に確認する。
    env["PYTHONIOENCODING"] = "utf-8"
    results = []
    for fname in sorted(os.listdir(TESTS_DIR)):
        if not (fname.startswith("test_") and fname.endswith(".py")):
            continue
        path = os.path.join(TESTS_DIR, fname)
        if _is_pytest_only(path):
            print(f"  SKIP  {fname}  (pytest.importorskip等を使用 -- pytest経由でのみ意図的に動く設計)")
            results.append({"file": fname, "status": "SKIP", "detail": "pytest-only by design"})
            continue
        code, output, elapsed = _run([sys.executable, path], cwd=REPO_ROOT, env=env, timeout=90)
        ok = code == 0
        print(f"  {'PASS' if ok else 'FAIL'}  {fname}  ({elapsed:.2f}s)")
        if not ok:
            print("    " + "\n    ".join(output.strip().splitlines()[-8:]))
        results.append({"file": fname, "status": "PASS" if ok else "FAIL", "returncode": code, "elapsed": elapsed})
    overall = "FAIL" if any(r["status"] == "FAIL" for r in results) else "PASS"
    return {"name": "direct_execution", "status": overall, "files": results}


def check_node_polyfill_test():
    print()
    print("=" * 70)
    print("[4/5] tests/test_polyfill.js (Node.js)")
    print("=" * 70)
    if not _tool_available("node"):
        print("  SKIP  node が見つかりません(このリポジトリのPython側には影響しません)")
        return {"name": "node_polyfill", "status": "SKIP", "detail": "node not found"}
    code, output, _ = _run(
        [sys.executable, "tests/extract_polyfill_js.py"], cwd=REPO_ROOT, timeout=30,
    )
    if code not in (0, None):
        print(output)
        return {"name": "node_polyfill", "status": "FAIL", "detail": "extract_polyfill_js.py failed"}
    code, output, elapsed = _run(["node", "tests/test_polyfill.js"], cwd=REPO_ROOT, timeout=60)
    print(output.strip())
    return {"name": "node_polyfill", "status": "PASS" if code == 0 else "FAIL", "elapsed": elapsed}


def check_typescript_types():
    print()
    print("=" * 70)
    print("[5/5] TypeScript型定義チェック (types/, tsc --strict --noEmit)")
    print("=" * 70)
    if not _tool_available("tsc"):
        print("  SKIP  tsc が見つかりません(npm i -g typescript 等で導入できます)")
        return {"name": "typescript", "status": "SKIP", "detail": "tsc not found"}
    ts_files = sorted(f for f in os.listdir(TYPES_DIR) if f.endswith(".ts"))
    code, output, elapsed = _run(["tsc", "--strict", "--noEmit", *ts_files], cwd=TYPES_DIR, timeout=60)
    if output.strip():
        print(output.strip())
    return {"name": "typescript", "status": "PASS" if code == 0 else "FAIL", "elapsed": elapsed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-report", metavar="PATH", help="結果をJSONとしても書き出す")
    args = parser.parse_args()

    results = [
        check_environment(),
        check_pytest_suite(),
        check_direct_execution(),
        check_node_polyfill_test(),
        check_typescript_types(),
    ]

    print()
    print("=" * 70)
    print("まとめ")
    print("=" * 70)
    for r in results:
        print(f"  {r['status']:<5} {r['name']}")

    if args.save_report:
        with open(args.save_report, "w", encoding="utf-8") as f:
            json.dump({"results": results}, f, ensure_ascii=False, indent=2)
        print(f"\n詳細レポートを書き出しました: {args.save_report}")

    failed = [r for r in results if r["status"] == "FAIL"]
    if failed:
        print(f"\n{len(failed)}件のFAILがあります: {', '.join(r['name'] for r in failed)}")
        return 1
    print("\n全項目PASS(またはツール不在によるやむを得ないSKIP)です。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

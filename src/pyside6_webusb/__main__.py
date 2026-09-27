# -*- coding: utf-8 -*-
"""🆕 v0.0.5a0: `python -m pyside6_webusb` のエントリポイント。

環境診断レポート(diagnostics.environment_report())をテキストで表示する。
問題が検出された場合は終了コード1、無ければ0を返す——CI上で
「このジョブのPySide6/libusbセットアップは壊れていないか」をワンライナーで
確認するのにも使える想定(`python -m pyside6_webusb || echo "environment broken"`)。

🆕 v0.0.5.post3: `--json` を付けると、上記の人間向けテキストの代わりに
environment_report()の辞書をそのままJSONとして標準出力に書き出す。CI側で
このレポート自体をアーティファクトとして保存したり、problems配列をテキスト
パースに頼らずプログラムから直接読んだりできるようにするための拡張——
終了コードの意味(問題があれば1、無ければ0)はテキストモードと同じ。

🆕 v0.0.5b3: `--lang en`/`--lang=ja`/`-l zh` でレポートの表示言語を切り替えられる
(pyside6_webusb.i18n.SUPPORTED_LOCALES)。省略時の既定は従来どおり日本語
(diagnostics.environment_report()のdocstring参照)——このオプションを追加しても
既存の呼び出し(引数無し)の出力は一切変わらない。

🆕 v0.0.6: `--check-native-messaging path/to/manifest.json`(短縮形 `-n`)を
付けると、通常の環境診断の代わりにnative_messaging.validate_native_messaging_manifest()
でそのmanifest.jsonを静的検査する(fox-webusb等のnative messagingホストの
登録ファイル向け。詳細はnative_messaging.pyのモジュールdocstring参照)。
`--lang`/`--json`はこちらのモードでも同じ意味で効く。終了コードの意味も
既存の環境診断モードと同じ(問題があれば1、無ければ0)。

⚠️ argv=Noneのときsys.argv[1:]へフォールバックしているのは飾りではない:
`pyside6-webusb-doctor`はsetuptoolsが生成する実際のコンソールスクリプトで、
中身は`sys.exit(main())`——つまりargvを渡さずmain()を呼ぶ(実際に生成された
スクリプトを読んで確認済み)。ここでフォールバックしないと、コマンドラインで
`pyside6-webusb-doctor --json`と打っても、そのものずばりの`--json`が
main()に一切届かず常に無視されてしまう。
"""
import json
import sys

from .diagnostics import environment_report, format_environment_report


def _extract_lang(argv):
    """--lang/-l の値を argv から取り出す(あれば)。'--lang=ja' 形式と
    '--lang ja' 形式の両方に対応する。値が省略されている、または認識できない
    ロケール名の場合は i18n.normalize_locale() が既定値へ静かにフォール
    バックするため、ここでは値そのものの妥当性は検証しない。"""
    for i, tok in enumerate(argv):
        if tok.startswith("--lang="):
            return tok.split("=", 1)[1]
        if tok in ("--lang", "-l") and i + 1 < len(argv):
            return argv[i + 1]
    return None


def _extract_native_messaging_manifest_path(argv):
    """🆕 v0.0.6: --check-native-messaging/-n の値(manifest.jsonのパス)を
    argvから取り出す(あれば)。_extract_lang()と全く同じ、
    '--check-native-messaging=path'/'--check-native-messaging path'の
    両対応。"""
    for i, tok in enumerate(argv):
        if tok.startswith("--check-native-messaging="):
            return tok.split("=", 1)[1]
        if tok in ("--check-native-messaging", "-n") and i + 1 < len(argv):
            return argv[i + 1]
    return None


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    lang = _extract_lang(argv)

    manifest_path = _extract_native_messaging_manifest_path(argv)
    if manifest_path is not None:
        # 🆕 v0.0.6: 通常の環境診断とは別モード。native_messaging.pyの
        # モジュールdocstring参照。
        from .native_messaging import format_manifest_check, validate_native_messaging_manifest
        problems, warnings = validate_native_messaging_manifest(manifest_path, locale=lang)
        if "--json" in argv:
            print(json.dumps(
                {"path": manifest_path, "problems": problems, "warnings": warnings},
                ensure_ascii=False, indent=2,
            ))
        else:
            print(format_manifest_check(manifest_path, problems, warnings, locale=lang))
        return 1 if problems else 0

    report = environment_report(locale=lang)
    if "--json" in argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_environment_report(report))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

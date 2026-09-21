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


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    report = environment_report()
    if "--json" in argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_environment_report(report))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

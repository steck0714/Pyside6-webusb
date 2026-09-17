# -*- coding: utf-8 -*-
"""🆕 v0.0.5a0: `python -m pyside6_webusb` のエントリポイント。

環境診断レポート(diagnostics.environment_report())をテキストで表示する。
問題が検出された場合は終了コード1、無ければ0を返す——CI上で
「このジョブのPySide6/libusbセットアップは壊れていないか」をワンライナーで
確認するのにも使える想定(`python -m pyside6_webusb || echo "environment broken"`)。
"""
import sys

from .diagnostics import environment_report, format_environment_report


def main(argv=None) -> int:
    report = environment_report()
    print(format_environment_report(report))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

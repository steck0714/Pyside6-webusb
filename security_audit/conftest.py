# -*- coding: utf-8 -*-
"""security_audit/ 用のpytest設定。tests/conftest.pyと同じ役割・同じ方式を踏襲する:
pip install不要でsrc/レイアウトのパッケージをimportできるようにし、DISPLAYの無い
ヘッドレス環境ではQT_QPA_PLATFORM=offscreenへ自動フォールバックする(QApplication([])の
ディスプレイ接続失敗はPythonの例外ではなくプロセスクラッシュになるため、生成前に
検知して回避する必要がある)。

tests/ と security_audit/ は独立したディレクトリなので、pytestはこのconftest.pyを
tests/conftest.pyとは別に読み込む。内容は意図的にtests/conftest.pyと同一にしてある。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

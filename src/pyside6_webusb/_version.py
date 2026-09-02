# -*- coding: utf-8 -*-
"""バージョン文字列の単一の情報源。

__init__.py と bridge.py の両方がこの値を必要とする
(bridge.py側は v0.0.4b2 で追加した isAvailable() のF12デバッグ情報に含める)。
__init__.py は bridge.py を import するため、bridge.py 側が
`from . import __version__` のように __init__.py から逆に import しようとすると
循環importになる。両者がこの独立した小さなモジュールから読む形にすることで
それを避けている。"""

__version__ = "0.0.4b2"

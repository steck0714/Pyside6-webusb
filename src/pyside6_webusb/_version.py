# -*- coding: utf-8 -*-
"""バージョン文字列の単一の情報源。

__init__.py と bridge.py の両方がこの値を必要とする
(bridge.py側は v0.0.4b2 で追加した isAvailable() のF12デバッグ情報に含める)。
__init__.py は bridge.py を import するため、bridge.py 側が
`from . import __version__` のように __init__.py から逆に import しようとすると
循環importになる。両者がこの独立した小さなモジュールから読む形にすることで
それを避けている。"""


# (履歴)0.0.6: そのリリースはalpha/beta反復(a1〜b3のようなzip限定のプレリリース
# タグ)でも、同じ0.0.xマイナー内の追従修正(.postN)でもなく、意図的に
# 素のPEP 440リリース番号のみ("0.0.6"、接尾辞なし)にしている——ユーザーからの
# 明示的な指示による。zip/sdist/whlの全てで同じ"0.0.6"を使う(post番号は
# 付けない)。次にこの0.0.6系列へ追従修正が必要になった場合は、これまでどおり
# 0.0.6.post1のように.postNを付けて後方から追う。
# 🆕 v0.0.6a(配布版 0.0.6.post1): 開発中の呼び名(zip名・GitHubリリースのラベル)は
# "v0.0.6a"、実際にsdist/whl/_version.py/pyproject.tomlの全てで名乗るバージョンは
# PEP 440の "0.0.6.post1"(0.0.6の追従リリース。"0.0.6a0"は0.0.6より古い扱いに
# なるため、0.0.6のあとに出す版としては使えない)。CHANGELOG/RELEASE_NOTESの
# 二本立て運用の規約どおり。
__version__ = "0.0.6.post1"

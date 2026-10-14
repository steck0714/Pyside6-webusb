# -*- coding: utf-8 -*-
"""pyproject.toml の依存宣言のテスト (🆕 0.0.6.post2)。

PySide6 6.12でQtWebEngineがPySide6-Addonsから別配布物PySide6-WebEngineへ分離された。
開発用venvに`pip install PySide6`(メタパッケージ)で入れるとWebEngineも一緒に入るため
テストは通るが、`pip install pyside6-webusb`だけのクリーン環境ではQtWebEngineが無く
import時に失敗する、という種類の不具合は、通常のテストでは見つけられない。
そのため依存宣言そのものをここで固定する。"""
import os
import re
import sys

import pytest

try:
    import tomllib
except ImportError:  # Python 3.9/3.10
    tomllib = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_project():
    path = os.path.join(ROOT, "pyproject.toml")
    if not os.path.exists(path):
        pytest.skip("pyproject.toml is not available (installed copy of the tests)")
    if tomllib is None:
        pytest.skip("tomllib requires Python 3.11+")
    with open(path, "rb") as f:
        return tomllib.load(f)["project"]


def _norm(req):
    return re.sub(r"[-_.]+", "-", req.split(";")[0].strip().lower())


def test_qtwebengine_is_pulled_in_through_the_addons_webengine_extra():
    deps = _load_project()["dependencies"]
    addons = [d for d in deps if _norm(d).startswith("pyside6-addons")]
    assert addons, deps
    assert "[webengine]" in addons[0].lower().replace(" ", ""), (
        "PySide6 6.12+ ships QtWebEngine in the separate PySide6-WebEngine package; "
        "PySide6-Addons[webengine] is the official way to get it: " + addons[0])


def test_pyside6_webengine_is_not_a_direct_dependency():
    """PyPIにはPySide6-WebEngineの6.12.0.140のほかに0.0.1のプレースホルダがあり、
    直接依存にすると解決時にそちらを拾う恐れがある。"""
    deps = _load_project()["dependencies"]
    assert not [d for d in deps if _norm(d).startswith("pyside6-webengine")], deps


def test_pyproject_version_matches_the_package_version():
    import pyside6_webusb
    assert _load_project()["version"] == pyside6_webusb.__version__


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

# Copyright (C) 2026 Гаврилов Алексей Александрович
# SPDX-License-Identifier: GPL-3.0-or-later
"""Версия - одна константа (чек-лист владельца, п. 9): окно программы = latest.json (её пишет build.sh) =
«Стало» в установщике."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_version_same_in_window_build_and_installer():
    from shchelchok import __version__ as v
    assert re.fullmatch(r"\d+\.\d+\.\d+", v)
    build = read("tools", "wine", "build.sh")
    # версию сборка берёт из shchelchok/__init__.py и падает, если в аргументе другая - номер живёт в ОДНОМ месте
    assert "shchelchok/__init__.py" in build and 'V=${1:-$VV}' in build, "build.sh берёт версию не из программы"
    assert '[ "$V" = "$VV" ]' in build, "build.sh не сверяет версию с программой"
    m = re.search(r'DEMO_OLD, DEMO_NEW = "([\d.]+)", "([\d.]+)"', read("loader", "loader.py"))
    assert m and m.group(2) == v, "в установщике «Стало» - другая версия"


def test_readme_mentions_version():
    from shchelchok import __version__ as v
    assert v in read("README.md"), "в README нет раздела про текущую версию"

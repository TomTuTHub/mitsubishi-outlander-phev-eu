"""Schluessel- und Platzhalter-Paritaet von strings.json, en.json, de.json, ja.json."""
import json
import re
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "mitsubishi_outlander_phev_eu"
FILES = ["strings.json", "translations/en.json", "translations/de.json", "translations/ja.json"]
_PH = re.compile(r"\{[^{}]*\}")


def _flat(d, prefix=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, prefix + k + "."))
        else:
            out[prefix + k] = v
    return out


def _load(name):
    return _flat(json.loads((_PKG / name).read_text(encoding="utf-8")))


def test_key_sets_identical():
    ref = set(_load("translations/en.json"))
    for name in FILES:
        assert set(_load(name)) == ref, name


def test_placeholders_identical():
    ref = _load("translations/en.json")
    for name in FILES:
        data = _load(name)
        for key, val in ref.items():
            assert sorted(_PH.findall(data[key])) == sorted(_PH.findall(val)), (name, key)


def test_no_empty_values():
    for name in FILES:
        assert all(v.strip() for v in _load(name).values()), name

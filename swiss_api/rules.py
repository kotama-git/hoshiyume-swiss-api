"""Versioned HOSHIYUME astrology rules, kept separately from calculation code."""

import json
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any


RULES_PATH = Path(__file__).with_name("rules") / "astrology_rules_v1.json"


@lru_cache(maxsize=1)
def current_rules() -> dict[str, Any]:
    with RULES_PATH.open(encoding="utf-8") as source:
        rules = json.load(source)
    required = {"rules_version", "zodiac_system", "house_system", "orb_profile", "bodies", "aspects", "signs"}
    if not required.issubset(rules):
        raise RuntimeError("astrology rules configuration is incomplete")
    if len(rules["signs"]) != 12 or len({sign["id"] for sign in rules["signs"]}) != 12:
        raise RuntimeError("astrology rules must define twelve unique signs")
    if len({aspect["id"] for aspect in rules["aspects"]}) != len(rules["aspects"]):
        raise RuntimeError("astrology rules must define unique aspect identifiers")
    return rules


def rules_sha256() -> str:
    return sha256(RULES_PATH.read_bytes()).hexdigest()

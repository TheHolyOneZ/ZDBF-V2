# SPDX-License-Identifier: Apache-2.0
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from migrate_v1 import convert_cron, convert_weekday_field, dump_toml

from zdbf.core.config import Config, Settings


def test_weekday_conversion():
    assert convert_weekday_field("*") == "*"
    assert convert_weekday_field("0") == "1"
    assert convert_weekday_field("6") == "0"
    assert convert_weekday_field("0-4") == "1,2,3,4,5"
    assert convert_weekday_field("5,6") == "0,6"
    assert convert_weekday_field("*/3") == "0,1,4"
    assert convert_cron("30 9 * * 0-4") == "30 9 * * 1,2,3,4,5"


def test_dump_toml_roundtrip():
    data = Settings().model_dump()
    data["bot"]["prefix"] = '?"quoted'
    settings, _ = Config.parse(dump_toml(data))
    assert settings.bot.prefix == '?"quoted'
    assert len(settings.status.rotation) == len(data["status"]["rotation"])

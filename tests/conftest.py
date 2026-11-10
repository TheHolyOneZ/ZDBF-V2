# SPDX-License-Identifier: Apache-2.0

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("DISCORD_TOKEN", "BOT_OWNER_ID", "SHARD_COUNT", "SHARD_IDS", "ZDBF_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path

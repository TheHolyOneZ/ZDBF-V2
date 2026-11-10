# SPDX-License-Identifier: Apache-2.0
import pytest

from zdbf.core.config import Config, ConfigError


def test_default_template_is_valid():
    settings, _ = Config.parse(Config.default_template())
    assert settings.bot.prefix == "!"
    assert settings.modules.cluster is False


def test_ensure_exists_and_load(tmp_cwd):
    cfg = Config()
    assert cfg.ensure_exists() is True
    cfg.load()
    assert cfg.get("bot.prefix") == "!"
    assert cfg.get("prefix") == "!"
    assert cfg.get("missing.key", 5) == 5


def test_invalid_values_are_reported(tmp_cwd):
    (tmp_cwd / "config.toml").write_text('[bot]\nprefix = ""\n[status]\ninterval = 1\n')
    with pytest.raises(ConfigError) as exc:
        Config().load()
    assert "bot.prefix" in str(exc.value) and "status.interval" in str(exc.value)


def test_unknown_key_in_framework_section_rejected():
    with pytest.raises(ConfigError):
        Config.parse("[bot]\nprefx = '!'\n")


def test_extension_sections_allowed(tmp_cwd):
    (tmp_cwd / "config.toml").write_text('[weather]\napi_key = "x"\n')
    cfg = Config().load()
    assert cfg.get("weather.api_key") == "x"


async def test_overrides_persist_and_validate(tmp_cwd):
    cfg = Config().load()
    await cfg.set("backup.max_per_guild", 50)
    assert Config().load().get("backup.max_per_guild") == 50
    with pytest.raises(ConfigError):
        await cfg.set("backup.max_per_guild", -1)
    assert cfg.get("backup.max_per_guild") == 50
    assert await cfg.unset("backup.max_per_guild")
    assert cfg.get("backup.max_per_guild") == 25


def test_secrets_from_env(tmp_cwd, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", " abc ")
    monkeypatch.setenv("BOT_OWNER_ID", "1, 2")
    monkeypatch.setenv("SHARD_IDS", "0,1")
    cfg = Config().load()
    assert cfg.secrets.token == "abc"
    assert cfg.owner_ids == {1, 2}
    assert cfg.secrets.shard_ids == [0, 1]

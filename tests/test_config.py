"""The startup guards are the only thing standing between a typo and an
unauthenticated finance API on the public internet. Test them like it."""
import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.config import ConfigError, Settings

BASE = dict(table_name="summarylogs", connection_string="", account_name="acct",
            api_key="", cors_origins=[], cache_ttl=60, dedup_strategy="latest")

def cfg(**kw):
    return Settings(**{**BASE, **kw})

# --- local is permissive on purpose ---
def test_local_allows_no_key_and_no_cors():
    cfg(environment="local").validate()

def test_local_accepts_connection_string():
    cfg(environment="local", connection_string="x", account_name="").validate()

# --- deployed is not ---
@pytest.mark.parametrize("env", ["dev", "test", "prod"])
def test_deployed_requires_api_key(env):
    with pytest.raises(ConfigError, match="API_KEY is required"):
        cfg(environment=env, cors_origins=["https://recon.example.com"]).validate()

def test_deployed_rejects_short_key():
    with pytest.raises(ConfigError, match="at least 24"):
        cfg(environment="prod", api_key="short",
            cors_origins=["https://recon.example.com"]).validate()

def test_deployed_requires_cors():
    with pytest.raises(ConfigError, match="CORS_ORIGINS is required"):
        cfg(environment="prod", api_key="k" * 32).validate()

def test_deployed_rejects_wildcard_cors():
    with pytest.raises(ConfigError, match="cannot be '\\*'"):
        cfg(environment="prod", api_key="k" * 32, cors_origins=["*"]).validate()

def test_deployed_valid_config_passes():
    cfg(environment="prod", api_key="k" * 32,
        cors_origins=["https://recon.example.com"]).validate()

# --- general ---
def test_missing_credential_rejected():
    with pytest.raises(ConfigError, match="AZURE_STORAGE"):
        cfg(environment="local", account_name="").validate()

def test_bad_dedup_strategy_rejected():
    with pytest.raises(ConfigError, match="DEDUP_STRATEGY"):
        cfg(environment="local", dedup_strategy="average").validate()

def test_bad_environment_rejected():
    with pytest.raises(ConfigError, match="ENVIRONMENT"):
        cfg(environment="staging").validate()

def test_managed_identity_detected():
    assert cfg(environment="prod", account_name="a").uses_managed_identity is True
    assert cfg(environment="prod", connection_string="c").uses_managed_identity is False
    assert cfg(environment="prod", account_name="your-storage-account").table_endpoint \
        == "https://your-storage-account.table.core.windows.net/"

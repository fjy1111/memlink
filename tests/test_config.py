from pathlib import Path

import pytest
from pydantic import ValidationError

from agentipc.config import AgentIPCConfig, load_config


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "agentipc"
    / "resources"
    / "configs"
    / "default.yaml"
)


def test_default_config_constructs_with_expected_values() -> None:
    config = AgentIPCConfig()

    assert config.random_seed == 42
    assert config.state_root == Path(".agentipc/state")
    assert config.memory_root == Path(".agentipc/memory")
    assert config.artifact_root == Path(".agentipc/artifacts")
    assert config.results_root == Path("results")
    assert config.llm_provider == "mock"
    assert config.embedding_provider == "hash"


def test_default_yaml_maps_to_same_model_values() -> None:
    from_yaml = load_config(DEFAULT_CONFIG_PATH)
    from_defaults = AgentIPCConfig()

    assert from_yaml == from_defaults
    assert set(from_yaml.model_fields_set) == set(AgentIPCConfig.model_fields)


def test_config_does_not_require_api_key_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    config = load_config(DEFAULT_CONFIG_PATH)

    assert config.llm_provider == "mock"
    assert config.embedding_provider == "hash"


def test_invalid_critical_config_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentIPCConfig(llm_provider="")

    with pytest.raises(ValidationError):
        AgentIPCConfig(embedding_provider="")

    with pytest.raises(ValidationError):
        AgentIPCConfig(random_seed=-1)


def test_unknown_config_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentIPCConfig.model_validate({"unexpected": True})

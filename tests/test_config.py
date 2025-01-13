"""This is a code that performs several tests for the settings loader.
"""
from __future__ import annotations

import copy
import os
import tempfile
from pathlib import Path

import pytest

from sed.core.config import complete_dictionary
from sed.core.config import ConfigError
from sed.core.config import load_config
from sed.core.config import parse_config
from sed.core.config import save_config

test_dir = os.path.dirname(__file__)
test_config_dir = Path(f"{test_dir}/data/loader/")
config_paths = test_config_dir.glob("*/*.yaml")

default_config_keys = [
    "binning",
    "histogram",
]
default_binning_keys = [
    "hist_mode",
    "mode",
    "pbar",
    "threads_per_worker",
    "threadpool_API",
]
default_histogram_keys = [
    "bins",
    "axes",
    "ranges",
]


def test_default_config() -> None:
    """Test the config loader for the default config."""
    config = parse_config(config={}, folder_config={}, user_config={}, system_config={})
    assert isinstance(config, dict)
    for key in default_config_keys:
        assert key in config.keys()
    for key in default_binning_keys:
        assert key in config["binning"].keys()
    for key in default_histogram_keys:
        assert key in config["histogram"].keys()


def test_load_dict() -> None:
    """Test the config loader for a dict."""
    config_dict = {"test_entry": True}
    config = parse_config(config_dict, verify_config=False)
    assert isinstance(config, dict)
    for key in default_config_keys:
        assert key in config.keys()
    assert config["test_entry"] is True


def test_load_does_not_modify() -> None:
    """Test that the loader does not modify the source dictionaries."""
    config_dict = {"test_entry": True}
    config_copy = copy.deepcopy(config_dict)
    folder_dict = {"a": 5, "b": {"c": 7}}
    folder_copy = copy.deepcopy(folder_dict)
    user_dict = {"test_entry2": False}
    user_copy = copy.deepcopy(user_dict)
    system_dict = {"a": 3, "b": {"c": 9, "d": 13}}
    system_copy = copy.deepcopy(system_dict)
    default_dict = {"a": 1, "b": {"c": 13}, "c": {"e": 11}}
    default_copy = copy.deepcopy(default_dict)

    parse_config(
        config_dict,
        folder_dict,
        user_dict,
        system_dict,
        default_dict,
        verify_config=False,
    )
    assert config_dict == config_copy
    assert folder_dict == folder_copy
    assert user_dict == user_copy
    assert system_dict == system_copy
    assert default_dict == default_copy


def test_load_config() -> None:
    """Test if the config loader can handle json and yaml files."""
    config_json = load_config(
        f"{test_dir}/data/config/config.json",
    )
    config_yaml = load_config(
        f"{test_dir}/data/config/config.yaml",
    )
    assert config_json == config_yaml


def test_load_config_raise() -> None:
    """Test if the config loader raises an error for a wrong file type."""
    with pytest.raises(TypeError):
        load_config(f"{test_dir}/../README.md")


def test_complete_dictionary() -> None:
    """Test the merging of a config and a default config dict"""
    dict1 = {"key1": 1, "key2": 2, "nesteddict": {"key4": 4}}
    dict2 = {"key1": 2, "key3": 3, "nesteddict": {"key5": 5}}
    dict3 = complete_dictionary(dictionary=dict1, base_dictionary=dict2)
    assert isinstance(dict3, dict)
    for key in ["key1", "key2", "key3", "nesteddict"]:
        assert key in dict3
    for key in ["key4", "key5"]:
        assert key in dict3["nesteddict"]
    assert dict3["key1"] == 1


def test_complete_dictionary_raise() -> None:
    """Test that the complete_dictionary function raises if the dicts conflict."""
    dict1 = {"key1": 1, "key2": 2, "nesteddict": 3}
    dict2 = {"key1": 2, "key3": 3, "nesteddict": {"key5": 5}}
    with pytest.raises(ValueError):
        complete_dictionary(dictionary=dict1, base_dictionary=dict2)


def test_save_dict() -> None:
    """Test the config saver for a dict."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        for ext in ["yaml", "json"]:
            filename = tmpdirname + "/.sed_config." + ext
            config_dict = {"test_entry": True}
            save_config(config_dict, filename)
            assert Path(filename).exists()
            config = load_config(filename)
            assert config == config_dict
            config_dict = {"test_entry2": False}
            save_config(config_dict, filename)
            config = load_config(filename)
            assert {"test_entry", "test_entry2"}.issubset(config.keys())
            config_dict = {"test_entry2": False}
            save_config(config_dict, filename, overwrite=True)
            config = load_config(filename)
            assert "test_entry" not in config.keys()


@pytest.mark.parametrize("config_path", config_paths)
def test_config_model_valid(config_path) -> None:
    """Test the config model for a valid config."""
    config = parse_config(
        config_path,
        folder_config={},
        user_config={},
        system_config={},
        verify_config=True,
    )
    assert config is not None


def test_invalid_config_extra_field():
    """Test that an invalid config with an extra field fails validation."""
    default_config = parse_config(
        folder_config={},
        user_config={},
        system_config={},
        verify_config=True,
    )
    invalid_config = default_config.copy()
    invalid_config["extra_field"] = "extra_value"
    with pytest.raises(ConfigError):
        parse_config(
            invalid_config,
            folder_config={},
            user_config={},
            system_config={},
            verify_config=True,
        )


def test_invalid_config_missing_field():
    """Test that an invalid config with a missing required field fails validation."""
    default_config = parse_config(
        folder_config={},
        user_config={},
        system_config={},
        verify_config=True,
    )
    invalid_config = default_config.copy()
    del invalid_config["core"]["loader"]
    with pytest.raises(ConfigError):
        parse_config(
            folder_config={},
            user_config={},
            system_config={},
            default_config=invalid_config,
            verify_config=True,
        )


def test_invalid_config_wrong_values():
    """Test that the validators for certain fields fails validation if not fulfilled."""
    default_config = parse_config(
        folder_config={},
        user_config={},
        system_config={},
        verify_config=True,
    )
    invalid_config = default_config.copy()
    invalid_config["core"]["loader"] = "nonexistent"
    with pytest.raises(ConfigError) as e:
        parse_config(
            folder_config={},
            user_config={},
            system_config={},
            default_config=invalid_config,
            verify_config=True,
        )
    assert "Invalid loader nonexistent. Available loaders are:" in str(e.value)
    invalid_config = default_config.copy()
    invalid_config["core"]["copy_tool"] = {}
    invalid_config["core"]["copy_tool"]["source"] = "./"
    invalid_config["core"]["copy_tool"]["dest"] = "./"
    invalid_config["core"]["copy_tool"]["gid"] = 9999
    with pytest.raises(ConfigError) as e:
        parse_config(
            folder_config={},
            user_config={},
            system_config={},
            default_config=invalid_config,
            verify_config=True,
        )
    assert "Invalid value 9999 for gid. Group not found." in str(e.value)

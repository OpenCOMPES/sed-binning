"""This is a code that performs several tests for the settings loader.
"""
from __future__ import annotations

import copy
import os
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from sed.core.config import complete_dictionary
from sed.core.config import load_config
from sed.core.config import parse_config
from sed.core.config import read_env_var
from sed.core.config import save_config
from sed.core.config import save_env_var
from sed.core.config import USER_CONFIG_PATH

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
    with pytest.raises(ValidationError):
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
    with pytest.raises(ValidationError):
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
    with pytest.raises(ValidationError) as e:
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
    with pytest.raises(ValidationError) as e:
        parse_config(
            folder_config={},
            user_config={},
            system_config={},
            default_config=invalid_config,
            verify_config=True,
        )
    assert "Invalid value 9999 for gid. Group not found." in str(e.value)


def test_env_var_read_write(tmp_path, monkeypatch):
    """Test reading and writing environment variables."""
    # Mock USER_CONFIG_PATH to use a temporary directory
    monkeypatch.setattr("sed.core.config.USER_CONFIG_PATH", tmp_path)

    # Test writing a new variable
    save_env_var("TEST_VAR", "test_value")
    assert read_env_var("TEST_VAR") == "test_value"

    # Test writing multiple variables
    save_env_var("TEST_VAR2", "test_value2")
    assert read_env_var("TEST_VAR") == "test_value"
    assert read_env_var("TEST_VAR2") == "test_value2"

    # Test overwriting an existing variable
    save_env_var("TEST_VAR", "new_value")
    assert read_env_var("TEST_VAR") == "new_value"
    assert read_env_var("TEST_VAR2") == "test_value2"  # Other variables unchanged

    # Test reading non-existent variable
    assert read_env_var("NON_EXISTENT_VAR") is None


def test_env_var_read_no_file(tmp_path, monkeypatch):
    """Test reading environment variables when .env file doesn't exist."""
    # Mock USER_CONFIG_PATH to use an empty temporary directory
    monkeypatch.setattr("sed.core.config.USER_CONFIG_PATH", tmp_path)

    # Test reading from non-existent file
    assert read_env_var("TEST_VAR") is None


def test_env_var_special_characters():
    """Test reading and writing environment variables with special characters."""
    test_cases = {
        "TEST_URL": "http://example.com/path?query=value",
        "TEST_PATH": "/path/to/something/with/spaces and special=chars",
        "TEST_QUOTES": "value with 'single' and \"double\" quotes",
    }

    for var_name, value in test_cases.items():
        save_env_var(var_name, value)
        assert read_env_var(var_name) == value


@pytest.fixture
def cleanup_env_files():
    """Cleanup any .env files before and after tests"""
    # Clean up any existing .env files
    for path in [Path(".env"), USER_CONFIG_PATH / ".env"]:
        if path.exists():
            path.unlink()

    yield

    # Clean up after tests
    for path in [Path(".env"), USER_CONFIG_PATH / ".env"]:
        if path.exists():
            path.unlink()


def test_env_var_precedence(cleanup_env_files):  # noqa: ARG001
    """Test that environment variables are read in correct order of precedence"""
    # Set up test values in different locations
    os.environ["TEST_VAR"] = "os_value"

    with open(".env", "w") as f:
        f.write("TEST_VAR=local_value\n")

    save_env_var("TEST_VAR", "user_value")  # Saves to USER_CONFIG_PATH

    # Should get OS value first
    assert read_env_var("TEST_VAR") == "os_value"

    # Remove from OS env and should get local value
    del os.environ["TEST_VAR"]
    assert read_env_var("TEST_VAR") == "local_value"

    # Remove local .env and should get user config value
    Path(".env").unlink()
    assert read_env_var("TEST_VAR") == "user_value"

    # Remove user config and should get None
    (USER_CONFIG_PATH / ".env").unlink()
    assert read_env_var("TEST_VAR") is None


def test_env_var_save_and_load(cleanup_env_files):  # noqa: ARG001
    """Test saving and loading environment variables"""
    # Save a variable
    save_env_var("TEST_VAR", "test_value")

    # Should be able to read it back
    assert read_env_var("TEST_VAR") == "test_value"

    # Save another variable - should preserve existing ones
    save_env_var("OTHER_VAR", "other_value")
    assert read_env_var("TEST_VAR") == "test_value"
    assert read_env_var("OTHER_VAR") == "other_value"


def test_env_var_not_found(cleanup_env_files):  # noqa: ARG001
    """Test behavior when environment variable is not found"""
    assert read_env_var("NONEXISTENT_VAR") is None


def test_env_file_format(cleanup_env_files):  # noqa: ARG001
    """Test that .env file parsing handles different formats correctly"""
    with open(".env", "w") as f:
        f.write(
            """
                TEST_VAR=value1
                SPACES_VAR  =  value2
                EMPTY_VAR=
                #COMMENT=value3
                INVALID_LINE
                """,
        )

    assert read_env_var("TEST_VAR") == "value1"
    assert read_env_var("SPACES_VAR") == "value2"
    assert read_env_var("EMPTY_VAR") == ""
    assert read_env_var("COMMENT") is None

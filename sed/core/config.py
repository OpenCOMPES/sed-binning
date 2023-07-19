"""This module contains a config library for loading yaml/json files into dicts
"""
import json
import os
from importlib.util import find_spec
from pathlib import Path
from typing import Union

import yaml

package_dir = os.path.dirname(find_spec("sed").origin)


def parse_config(
    config: Union[dict, str] = None,
    folder_config: Union[dict, str] = None,
    user_config: Union[dict, str] = None,
    default_config: Union[
        dict,
        str,
    ] = f"{package_dir}/config/default.yaml",
    verbose: bool = True,
) -> dict:
    """Load the config dictionary from a file, or pass the provided config dictionary.

    Args:
        config (Union[dict, str], optional): config dictionary or file path.
                Files can be *json* or *yaml*. Defaults to None.
        folder_config (Union[ dict, str, ], optional): folder-based config dictionary
            or file path. The loaded dictionary is completed with the folder-based values,
            taking preference over user- and default values. Defaults to the file
            "sed_config.yaml" in the current working directory.
        user_config (Union[ dict, str, ], optional): user-based config dictionary
            or file path. The loaded dictionary is completed with the user-based values,
            taking preference over default values. Defaults to the file ".sed/config.yaml"
            in the current user's home directory.
        default_config (Union[ dict, str, ], optional): default config dictionary
            or file path. The loaded dictionary is completed with the default values.
            Defaults to *package_dir*/config/default.yaml".
        verbose (bool, optional): Option to report loaded config files. Defaults to True.
    Raises:
        TypeError: Raised if the provided file is neither *json* nor *yaml*.
        FileNotFoundError: Raised if the provided file is not found.

    Returns:
        dict: Loaded and possibly completed config dictionary.
    """
    used_config_files = []

    if config is None:
        config = {}

    if isinstance(config, dict):
        config_dict = config
    else:
        config_dict = load_config(config)
        used_config_files.append(str(Path(config).resolve()))

    folder_dict: dict = None
    if isinstance(folder_config, dict):
        folder_dict = folder_config
    else:
        if folder_config is None:
            folder_config = "./sed_config.yaml"
        if Path(folder_config).exists():
            folder_dict = load_config(folder_config)
            used_config_files.append(str(Path(folder_config).resolve()))

    user_dict: dict = None
    if isinstance(user_config, dict):
        user_dict = user_config
    else:
        if user_config is None:
            user_config = str(
                Path.home().joinpath(".sed").joinpath("config.yaml"),
            )
        if Path(user_config).exists():
            user_dict = load_config(user_config)
            used_config_files.append(str(Path(user_config).resolve()))

    if isinstance(default_config, dict):
        default_dict = default_config
    else:
        default_dict = load_config(default_config)
        used_config_files.append(str(Path(default_config).resolve()))

    if folder_dict is not None:
        config_dict = complete_dictionary(
            dictionary=config_dict,
            base_dictionary=folder_dict,
        )
    if user_dict is not None:
        config_dict = complete_dictionary(
            dictionary=config_dict,
            base_dictionary=user_dict,
        )
    config_dict = complete_dictionary(
        dictionary=config_dict,
        base_dictionary=default_dict,
    )

    if verbose:
        print("Configuration loaded from the following configuration files:")
        for file in used_config_files:
            print(f"[{file}]")

    return config_dict


def load_config(config_path: str) -> dict:
    """Loads config parameter files.

    Args:
        config_path (str): Path to the config file. Json or Yaml format are supported.

    Raises:
        FileNotFoundError: Raised if the config file cannot be found.
        TypeError: Raised if the provided file is neither *json* nor *yaml*.

    Returns:
        dict: loaded config dictionary
    """
    config_file = Path(config_path)
    if not config_file.is_file():
        raise FileNotFoundError(
            f"could not find the configuration file: {config_file}",
        )

    if config_file.suffix == ".json":
        with open(config_file, encoding="utf-8") as stream:
            config_dict = json.load(stream)
    elif config_file.suffix == ".yaml":
        with open(config_file, encoding="utf-8") as stream:
            config_dict = yaml.safe_load(stream)
    else:
        raise TypeError("config file must be of type json or yaml!")

    return config_dict


def complete_dictionary(dictionary: dict, base_dictionary: dict) -> dict:
    """Iteratively completes a dictionary from a base dictionary, by adding keys that are missing
    in the dictionary, and are present in the base dictionary.

    Args:
        dictionary (dict): the dictionary to be completed.
        base_dictionary (dict): the base dictionary.

    Returns:
        dict: the completed (merged) dictionary
    """
    for k, v in base_dictionary.items():
        if isinstance(v, dict):
            if k not in dictionary.keys():
                dictionary[k] = v
            else:
                if not isinstance(dictionary[k], dict):
                    raise ValueError(
                        f"Cannot merge dictionaries. Mismatch on Key {k}: {dictionary[k]}, {v}.",
                    )
                dictionary[k] = complete_dictionary(dictionary[k], v)
        else:
            if k not in dictionary.keys():
                dictionary[k] = v

    return dictionary

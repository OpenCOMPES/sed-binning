"""
This module contains the DataFrameCreator class which provides functionality for creating pandas
DataFrames from HDF5 files with multiple channels.

The DataFrameCreator class provides methods for getting channels associated with specified formats,
checking if 'group_name' and converting to 'index_key' and 'dataset_key' if so, returning
a h5 dataset for a given channel name, computing the index for the 'per_electron' data,
returning a pandas DataFrame for a given channel name of type [per electron], [per pulse],
and [per train], validating if the index and dataset keys for all channels in config exist
in the h5 file, and creating pandas DataFrames for the given file.

Typical usage example:

    df_creator = DataFrameCreator(config_dataframe)
    dataframe = df_creator.create_dataframe_per_file(file_path)
"""
from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
from pandas import concat
from pandas import DataFrame
from pandas import Index
from pandas import MultiIndex
from pandas import Series

from sed.loader.fel.utils import get_channels


class DataFrameCreator:
    """
    Utility class for creating pandas DataFrames from HDF5 files with multiple channels.
    """

    def __init__(self, config_dataframe: dict, h5_path: Path) -> None:
        """
        Initializes the DataFrameCreator class.

        Args:
            config_dataframe (dict): The configuration dictionary with only the dataframe key.
        """
        self.h5_file: h5py.File = h5py.File(h5_path, "r")
        self.failed_files_error: list[str] = []
        self.multi_index = get_channels(index=True)
        self._config = config_dataframe

    def get_index_dataset_key(self, channel: str) -> tuple[str, str]:
        """
        Checks if 'group_name' and converts to 'index_key' and 'dataset_key' if so.

        Args:
            channel (str): The name of the channel.

        Returns:
            tuple[str, str]: Outputs a tuple of 'index_key' and 'dataset_key'.

        Raises:
            ValueError: If neither 'group_name' nor both 'index_key' and 'dataset_key' are provided.
        """
        channel_config = self._config["channels"][channel]

        if "group_name" in channel_config:
            index_key = channel_config["group_name"] + "index"
            if channel == "timeStamp":
                dataset_key = channel_config["group_name"] + "time"
            else:
                dataset_key = channel_config["group_name"] + "value"
            return index_key, dataset_key
        if "index_key" in channel_config and "dataset_key" in channel_config:
            return channel_config["index_key"], channel_config["dataset_key"]

        raise ValueError(
            "For channel:",
            channel,
            "Provide either both 'index_key' and 'dataset_key'.",
            "or 'group_name' (parses only 'index' and 'value' or 'time' keys.)",
        )

    def get_dataset_array(
        self,
        channel: str,
        slice_: bool = False,
    ) -> tuple[Index, h5py.Dataset]:
        """
        Returns a numpy array for a given channel name.

        Args:
            channel (str): The name of the channel.
            slice (bool): If True, applies slicing on the dataset.

        Returns:
            tuple[Index, h5py.Dataset]: A tuple containing the train ID Index and the numpy array
            for the channel's data.
        """
        # Get the data from the necessary h5 file and channel
        index_key, dataset_key = self.get_index_dataset_key(channel)

        key = Index(self.h5_file[index_key], name="trainId")  # macrobunch
        dataset = self.h5_file[dataset_key]

        if slice_:
            slice_index = self._config["channels"][channel].get("slice", None)
            if slice_index is not None:
                dataset = np.take(dataset, slice_index, axis=1)
        # If np_array is size zero, fill with NaNs
        if dataset.shape[0] == 0:
            # Fill the np_array with NaN values of the same shape as train_id
            dataset = np.full_like(key, np.nan, dtype=np.double)

        return key, dataset

    def pulse_index(self, offset: int) -> tuple[MultiIndex, slice | np.ndarray]:
        """
        Computes the index for the 'per_electron' data.

        Args:
            offset (int): The offset value.

        Returns:
            tuple[MultiIndex, np.ndarray]: A tuple containing the computed MultiIndex and
            the indexer.
        """
        index_train, dataset_pulse = self.get_dataset_array("pulseId", slice_=True)
        index_train_ravel = np.repeat(index_train, dataset_pulse.shape[1])
        pulse_ravel = dataset_pulse.ravel().astype(int) - offset
        microbunches = MultiIndex.from_arrays((index_train_ravel, pulse_ravel)).dropna()
        # Only sort if necessary
        indexer: slice | np.ndarray = slice(None)
        if not microbunches.is_monotonic_increasing:
            microbunches, indexer = microbunches.sort_values(return_indexer=True)
        electron_counts = microbunches.value_counts(sort=False).values
        electrons = np.concatenate([np.arange(count) for count in electron_counts])
        return (
            MultiIndex.from_arrays(
                (index_train_ravel, pulse_ravel[indexer], electrons),
                names=self.multi_index,
            ),
            indexer,
        )

    @property
    def df_electron(self) -> DataFrame:
        """
        Returns a pandas DataFrame for a given channel name of type [per electron].

        Returns:
            DataFrame: The pandas DataFrame for the 'per_electron' channel's data.
        """
        offset = self._config["ubid_offset"]
        # Index
        index, indexer = self.pulse_index(offset)

        # Data logic
        channels = get_channels(self._config["channels"], "per_electron")
        slice_index = [self._config["channels"][channel].get("slice", None) for channel in channels]
        dataset_keys = [self.get_index_dataset_key(channel)[1] for channel in channels]
        all_keys_same = all(key == dataset_keys[0] for key in dataset_keys)

        if all_keys_same:
            _, dataset = self.get_dataset_array(channels[0])
            sliced_dataset = np.take(dataset, slice_index, axis=1)
            raveled_dataset = sliced_dataset.reshape(
                (-1, sliced_dataset.shape[1]),
            )

            dataframe = DataFrame(raveled_dataset[indexer], index=index, columns=channels)

        else:  # 3x slower
            series = {channel: self.get_dataset_array(channel)[1].ravel() for channel in channels}
            dataframe = concat(series, axis=1)[indexer]

        drop_vals = np.arange(-offset, 0)
        return dataframe.dropna().drop(index=drop_vals, level="pulseId", errors="ignore")

    @property
    def df_pulse(self) -> DataFrame:
        """
        Returns a pandas DataFrame for a given channel name of type [per pulse].

        Returns:
            DataFrame: The pandas DataFrame for the 'per_pulse' channel's data.
        """
        series = []
        channels = get_channels(self._config["channels"], "per_pulse")
        for channel in channels:
            # get slice
            key, dataset = self.get_dataset_array(channel, slice_=True)
            index = MultiIndex.from_product(
                (key, np.arange(0, dataset.shape[1]), [0]),
                names=self.multi_index,
            )
            series.append(Series(dataset[()].ravel(), index=index, name=channel))

        return concat(series, axis=1)  # much faster when concatenating similarly indexed data first

    @property
    def df_train(self) -> DataFrame:
        """
        Returns a pandas DataFrame for a given channel name of type [per train].

        Returns:
            DataFrame: The pandas DataFrame for the 'per_train' channel's data.
        """
        series = []

        channels = get_channels(self._config["channels"], "per_train")

        for channel in channels:
            key, dataset = self.get_dataset_array(channel, slice_=True)
            index = MultiIndex.from_product(
                (key, [0], [0]),
                names=self.multi_index,
            )
            if channel == "dldAux":
                aux_channels = self._config["channels"]["dldAux"]["dldAuxChannels"].items()
                for name, slice_aux in aux_channels:
                    series.append(Series(dataset[: key.size, slice_aux], index, name=name))
            else:
                series.append(Series(dataset, index, name=channel))

        return concat(series, axis=1)

    def validate_channel_keys(self) -> None:
        """
        Validates if the index and dataset keys for all channels in config exist in the h5 file.

        Raises:
            KeyError: If the index or dataset keys do not exist in the file.
        """
        for channel in self._config["channels"]:
            index_key, dataset_key = self.get_index_dataset_key(channel)
            if index_key not in self.h5_file:
                raise KeyError(f"Index key '{index_key}' doesn't exist in the file.")
            if dataset_key not in self.h5_file:
                raise KeyError(f"Dataset key '{dataset_key}' doesn't exist in the file.")

    @property
    def df(self) -> DataFrame:
        """
        Joins the 'per_electron', 'per_pulse', and 'per_train' using join operation,
        returning a single dataframe.

        Returns:
            DataFrame: The combined pandas DataFrame.
        """

        self.validate_channel_keys()
        return (
            self.df_electron.join(self.df_pulse, on=self.multi_index, how="outer")
            .join(self.df_train, on=self.multi_index, how="outer")
            .sort_index()
        )

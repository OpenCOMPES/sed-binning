"""
This module implements the flash data loader.
The raw hdf5 data is saved into parquet files and loaded as a dask dataframe.
If there are multiple files, the NaNs are forward filled.
"""
import os
from functools import reduce
from itertools import compress
from pathlib import Path
from typing import cast
from typing import List
from typing import Sequence
from typing import Tuple
from typing import Union

import dask.dataframe as dd
import h5py
import numpy as np
from joblib import delayed
from joblib import Parallel
from pandas import DataFrame
from pandas import MultiIndex
from pandas import Series

from sed.loader.base.loader import BaseLoader
from sed.loader.flash.metadata import get_metadata
from sed.loader.flash.utils import gather_flash_files
from sed.loader.flash.utils import initialize_paths
from sed.loader.flash.utils import parse_h5_keys


class FlashLoader(BaseLoader):
    """
    The class generates multiindexed multidimensional pandas dataframes
    from the new FLASH dataformat resolved by both macro and microbunches
    alongside electrons.
    """

    __name__ = "flash"

    supported_file_types = ["h5", "parquet"]

    def __init__(self, config: dict) -> None:

        super().__init__(config=config)
        self.index_per_electron: MultiIndex = None
        self.index_per_pulse: MultiIndex = None
        self.parquet_names: List[Path] = []
        self.failed_files_error: List[str] = []

    @property
    def available_channels(self) -> List:
        """Returns the channel names that are available for use,
        excluding pulseId, defined by the json file"""
        available_channels = list(self._config["dataframe"]["channels"].keys())
        available_channels.remove("pulseId")
        return available_channels

    @property
    def channels_per_pulse(self) -> List:
        """Returns a list of channels with per_pulse format,
        including all auxillary channels"""
        channels_per_pulse = []
        for key in self.available_channels:
            if (
                self._config["dataframe"]["channels"][key]["format"]
                == "per_pulse"
            ):
                if key == "dldAux":
                    for aux_key in self._config["dataframe"]["channels"][key][
                        "dldAuxChannels"
                    ].keys():
                        channels_per_pulse.append(aux_key)
                else:
                    channels_per_pulse.append(key)
        return channels_per_pulse

    @property
    def channels_per_electron(self) -> List:
        """Returns a list of channels with per_electron format"""
        return [
            key
            for key in self.available_channels
            if self._config["dataframe"]["channels"][key]["format"]
            == "per_electron"
        ]

    @property
    def channels_per_train(self) -> List:
        """Returns a list of channels with per_train format"""
        return [
            key
            for key in self.available_channels
            if self._config["dataframe"]["channels"][key]["format"]
            == "per_train"
        ]

    def reset_multi_index(self) -> None:
        """Resets the index per pulse and electron"""
        self.index_per_electron = None
        self.index_per_pulse = None

    def create_multi_index_per_electron(self, h5_file: h5py.File) -> None:
        """Creates an index per electron using pulseId
        for usage with the electron resolved pandas dataframe"""

        # Macrobunch IDs obtained from the pulseId channel
        [train_id, np_array] = self.create_numpy_array_per_channel(
            h5_file,
            "pulseId",
        )

        # Create a series with the macrobunches as index and
        # microbunches as values
        macrobunches = (
            Series(
                (np_array[i] for i in train_id.index),
                name="pulseId",
                index=train_id,
            )
            - self._config["dataframe"]["ubid_offset"]
        )

        # Explode dataframe to get all microbunch vales per macrobunch,
        # remove NaN values and convert to type int
        microbunches = macrobunches.explode().dropna().astype(int)

        # Create temporary index values
        index_temp = MultiIndex.from_arrays(
            (microbunches.index, microbunches.values),
            names=["trainId", "pulseId"],
        )

        # Calculate the electron counts per pulseId
        # unique preserves the order of appearance
        electron_counts = index_temp.value_counts()[index_temp.unique()].values

        # Series object for indexing with electrons
        electrons = (
            Series(
                [
                    np.arange(electron_counts[i])
                    for i in range(electron_counts.size)
                ],
            )
            .explode()
            .astype(int)
        )

        # Create a pandas multiindex using the exploded datasets
        self.index_per_electron = MultiIndex.from_arrays(
            (microbunches.index, microbunches.values, electrons),
            names=["trainId", "pulseId", "electronId"],
        )

    def create_multi_index_per_pulse(self, train_id, np_array) -> None:
        """Creates an index per pulse using a pulse resovled channel's
        macrobunch ID, for usage with the pulse resolved pandas dataframe"""

        # Create a pandas multiindex, useful to compare electron and
        # pulse resolved dataframes
        self.index_per_pulse = MultiIndex.from_product(
            (train_id, np.arange(0, np_array.shape[1])),
            names=["trainId", "pulseId"],
        )

    def create_numpy_array_per_channel(
        self,
        h5_file: h5py.File,
        channel: str,
    ) -> Tuple[Series, np.ndarray]:
        """Returns a numpy Array for a given channel name for a given file"""
        # Get the data from the necessary h5 file and channel
        group = cast(
            h5py.Group,
            h5_file[
                self._config["dataframe"]["channels"][channel]["group_name"]
            ],
        )
        channel_dict = self._config["dataframe"]["channels"][
            channel
        ]  # channel parameters

        train_id = Series(group["index"], name="trainId")  # macrobunch
        # unpacks the timeStamp or value
        if channel == "timeStamp":
            np_array = cast(h5py.Dataset, group["time"])[()]
        else:
            np_array = cast(h5py.Dataset, group["value"])[()]
        np_array = cast(np.ndarray, np_array)
        # Uses predefined axis and slice from the json file
        # to choose correct dimension for necessary channel
        if "slice" in channel_dict:
            np_array = np.take(
                np_array,
                channel_dict["slice"],
                axis=1,
            )
        return train_id, np_array

    def create_dataframe_per_electron(
        self,
        np_array,
        train_id,
        channel,
    ) -> DataFrame:
        """Returns a pandas DataFrame for a given channel name of type [per electron]"""
        # The microbunch resolved data is exploded and
        # converted to dataframe, afterwhich the MultiIndex is set
        # The NaN values are dropped, alongside the
        # pulseId = 0 (meaningless)
        return (
            Series((np_array[i] for i in train_id.index), name=channel)
            .explode()
            .dropna()
            .to_frame()
            .set_index(self.index_per_electron)
            .drop(
                index=cast(
                    List[int],
                    np.arange(-self._config["dataframe"]["ubid_offset"], 0),
                ),
                level=1,
                errors="ignore",
            )
        )

    def create_dataframe_per_pulse(
        self,
        np_array,
        train_id,
        channel,
        channel_dict,
    ) -> DataFrame:
        """Returns a pandas DataFrame for a given channel name of type [per pulse]"""
        # Special case for auxillary channels which checks the channel
        # dictionary for correct slices and creates a multicolumn
        # pandas dataframe
        if channel == "dldAux":
            # The macrobunch resolved data is repeated 499 times to be
            # compared to electron resolved data for each auxillary channel
            # and converted to a multicolumn dataframe
            data_frames = (
                Series(
                    (np_array[i, value] for i in train_id.index),
                    name=key,
                    index=train_id,
                ).to_frame()
                for key, value in channel_dict["dldAuxChannels"].items()
            )

            # Multiindex set and combined dataframe returned
            data = reduce(DataFrame.combine_first, data_frames)

        else:
            # For all other pulse resolved channels, macrobunch resolved
            # data is exploded to a dataframe and the MultiIndex set

            # Creates the index_per_pulse for the given channel
            self.create_multi_index_per_pulse(train_id, np_array)
            data = (
                Series((np_array[i] for i in train_id.index), name=channel)
                .explode()
                .to_frame()
                .set_index(self.index_per_pulse)
            )

        return data

    def create_dataframe_per_train(
        self,
        np_array,
        train_id,
        channel,
    ) -> DataFrame:
        """Returns a pandas DataFrame for a given channel name of type [per train]"""
        return (
            Series((np_array[i] for i in train_id.index), name=channel)
            .to_frame()
            .set_index(train_id)
        )

    def create_dataframe_per_channel(
        self,
        h5_file: h5py.File,
        channel: str,
    ) -> Union[Series, DataFrame]:
        """Returns a pandas DataFrame for a given channel name for
        a given file. The Dataframe contains the MultiIndex and returns
        depending on the channel's format"""
        [train_id, np_array] = self.create_numpy_array_per_channel(
            h5_file,
            channel,
        )  # numpy Array created
        channel_dict = self._config["dataframe"]["channels"][
            channel
        ]  # channel parameters

        # If np_array is size zero, fill with NaNs
        if np_array.size == 0:
            np_array = np.full_like(train_id, np.nan, dtype=np.double)
            data = Series(
                (np_array[i] for i in train_id.index),
                name=channel,
                index=train_id,
            )

        # Electron resolved data is treated here
        if channel_dict["format"] == "per_electron":
            # Creates the index_per_electron if it does not exist for a given file
            if self.index_per_electron is None:
                self.create_multi_index_per_electron(h5_file)

            data = self.create_dataframe_per_electron(
                np_array,
                train_id,
                channel,
            )

        # Pulse resolved data is treated here
        elif channel_dict["format"] == "per_pulse":
            data = self.create_dataframe_per_pulse(
                np_array,
                train_id,
                channel,
                channel_dict,
            )

        # Train resolved data is treated here
        elif channel_dict["format"] == "per_train":
            data = self.create_dataframe_per_train(np_array, train_id, channel)

        else:
            raise ValueError(
                channel
                + "has an undefined format. Available formats are \
                per_pulse, per_electron and per_train",
            )

        return data

    def concatenate_channels(
        self,
        h5_file: h5py.File,
    ) -> Union[Series, DataFrame]:
        """Returns a concatenated pandas DataFrame for either all pulse,
        train or electron resolved channels."""
        all_keys = parse_h5_keys(h5_file)  # Parses all channels present

        # Check for if the provided group_name actually exists in the file
        for channel in self._config["dataframe"]["channels"]:
            if channel == "timeStamp":
                group_name = (
                    self._config["dataframe"]["channels"][channel][
                        "group_name"
                    ]
                    + "time"
                )
            else:
                group_name = (
                    self._config["dataframe"]["channels"][channel][
                        "group_name"
                    ]
                    + "value"
                )

            if group_name not in all_keys:
                raise ValueError(
                    f"The group_name for channel {channel} does not exist.",
                )

        data_frames = (
            self.create_dataframe_per_channel(h5_file, each)
            for each in self.available_channels
        )
        return reduce(
            lambda left, right: left.join(right, how="outer"),
            data_frames,
        )

    def create_dataframe_per_file(
        self,
        file_path: Path,
    ) -> Union[Series, DataFrame]:
        """Returns two pandas DataFrames constructed for the given file.
        The DataFrames contains the datasets from the iterable in the
        order opposite to specified by channel names. One DataFrame is
        pulse resolved and the other electron resolved.
        """
        # Loads h5 file and creates two dataframes
        with h5py.File(file_path, "r") as h5_file:
            self.reset_multi_index()  # Reset MultiIndexes for next file
            return self.concatenate_channels(h5_file)

    def h5_to_parquet(self, h5_path: Path, parquet_path: Path) -> None:
        """Uses the createDataFramePerFile method and saves
        the dataframes to a parquet file."""
        try:
            (
                self.create_dataframe_per_file(h5_path)
                .reset_index(level=["trainId", "pulseId", "electronId"])
                .to_parquet(parquet_path, index=False)
            )
        except ValueError as failed_string_error:
            self.failed_files_error.append(
                f"{parquet_path}: {failed_string_error}",
            )
            self.parquet_names.remove(parquet_path)

    def fill_na(
        self,
        dataframes: List,
    ) -> dd.DataFrame:
        """Routine to fill the NaN values with intrafile forward filling."""
        channels: List[str] = self.channels_per_pulse + self.channels_per_train
        for i, _ in enumerate(dataframes):
            dataframes[i][channels] = dataframes[i][channels].fillna(
                method="ffill",
            )

        # This loop forward fills between the consective files.
        # The first run file will have NaNs, unless another run
        # before it has been defined.
        for i in range(1, len(dataframes)):
            # Take only pulse channels
            subset = dataframes[i][channels]
            # Find which column(s) contain NaNs.
            is_null = subset.loc[0].isnull().values.compute()
            # Statement executed if there is more than one NaN value in the
            # first row from all columns
            if is_null.sum() > 0:
                # Select channel names with only NaNs
                channels_to_overwrite = list(compress(channels, is_null[0]))
                # Get the values for those channels from previous file
                values = dataframes[i - 1][channels].tail(1).values[0]
                # Extract channels_to_overwrite from values and create a dictionary
                fill_dict = dict(zip(channels, values))
                fill_dict = {
                    k: v
                    for k, v in fill_dict.items()
                    if k in channels_to_overwrite
                }
                # Fill all NaNs by those values
                dataframes[i][channels_to_overwrite] = subset[
                    channels_to_overwrite
                ].fillna(fill_dict)

        return dd.concat(dataframes)

    def parse_metadata(
        self,
        files: Sequence[str],  # pylint: disable=unused-argument
    ) -> dict:
        """Dummy

        Args:
            files (Sequence[str]): _description_

        Returns:
            dict: _description_
        """
        return {}

    def get_count_rate(
        self,
        fids: Sequence[int] = None,
        **kwds,
    ):
        return None, None

    def get_elapsed_time(self, fids=None, **kwds):
        return None

    def read_dataframe(
        self,
        files: Sequence[str] = None,
        folder: str = None,
        ftype: str = "h5",
        metadata: dict = None,
        collect_metadata: bool = False,
        runs: Sequence[int] = None,
        **kwds,
    ) -> Tuple[dd.DataFrame, dict]:
        """
        Read express data from the DAQ, generating a parquet in between.

        Args:
            files (Sequence[str], optional): A list of specific file names to read.
            Defaults to None.
            folder (str, optional): The directory where the raw data files are located.
            Defaults to None.
            ftype (str, optional): The file extension type. Defaults to "h5".
            metadata (dict, optional): Additional metadata. Defaults to None.
            collect_metadata (bool, optional): Whether to collect metadata.
            Defaults to False.
            runs (Sequence[int], optional): A list of specific run numbers to read.
            Defaults to None.

        Returns:
            Tuple[dd.DataFrame, dict]: A tuple containing the concatenated DataFrame
            and metadata.

        Raises:
            ValueError: If neither 'runs' nor 'files'/'folder' is provided.
            FileNotFoundError: If the conversion fails for some files or no
            data is available.
        """

        # Check if a specific folder is provided
        if folder:
            parquet_path = "processed/parquet"
            data_parquet_dir = folder.joinpath(parquet_path)
            if not data_parquet_dir.exists():
                os.mkdir(data_parquet_dir)

        # If folder is not provided, initialize paths from the configuration
        if not folder:
            data_raw_dir, data_parquet_dir = initialize_paths(
                self._config["dataframe"],
            )
            folder = data_raw_dir

        # Create a per_file directory
        temp_parquet_dir = data_parquet_dir.joinpath("per_file")
        os.makedirs(temp_parquet_dir, exist_ok=True)

        all_files = []
        if files:
            all_files = [Path(folder + file) for file in files]
        elif runs:
            # Prepare a list of names for the runs to read and parquets to write
            runs = runs if isinstance(runs, list) else [runs]

            for run in runs:
                run_files = gather_flash_files(
                    run,
                    self._config["dataframe"]["daq"],
                    folder,
                    extension=ftype,
                )
                all_files.extend(run_files)
        else:
            raise ValueError(
                "At least one of 'runs' or 'files'/'folder' must be provided.",
            )

        parquet_name = f"{temp_parquet_dir}/"
        self.parquet_names = [
            Path(parquet_name + file.stem) for file in all_files
        ]
        missing_files: List[Path] = []
        missing_parquet_names: List[Path] = []

        # Only read and write files which were not read already
        for i, parquet_file in enumerate(self.parquet_names):
            if not parquet_file.exists():
                missing_files.append(all_files[i])
                missing_parquet_names.append(parquet_file)

        print(
            f"Reading files: {len(missing_files)} new files of {len(all_files)} total.",
        )

        self.reset_multi_index()  # Initializes the indices for h5_to_parquet

        # Run self.h5_to_parquet in parallel
        if len(missing_files) > 0:
            Parallel(n_jobs=len(missing_files), verbose=10)(
                delayed(self.h5_to_parquet)(h5_path, parquet_path)
                for h5_path, parquet_path in zip(
                    missing_files,
                    missing_parquet_names,
                )
            )

        if self.failed_files_error:
            raise FileNotFoundError(
                "Conversion failed for the following files: \n"
                + "\n".join(self.failed_files_error),
            )

        print("All files converted successfully!")

        if len(self.parquet_names) == 0:
            raise ValueError(
                "No data available. Probably failed reading all h5 files",
            )

        print(
            f"Loading {len(self.parquet_names)} dataframes. Failed reading "
            f"{len(all_files)-len(self.parquet_names)} files.",
        )
        # Read all parquet files using dask and concatenate into one dataframe
        # after filling
        dataframe = self.fill_na(
            [
                dd.read_parquet(parquet_file)
                for parquet_file in self.parquet_names
            ],
        )
        dataframe = dataframe.dropna(subset=self.channels_per_electron)

        if collect_metadata:
            metadata = get_metadata(
                beamtime_id=self._config["dataframe"]["beamtime_id"],
                runs=runs,
                metadata=self.metadata,
            )
        else:
            metadata = self.metadata

        return dataframe, metadata


LOADER = FlashLoader

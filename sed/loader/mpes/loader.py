"""
module sed.loader.mpes, code for loading hdf5 files delayed into a dask dataframe.
Mostly ported from https://github.com/mpes-kit/mpes.
@author: L. Rettig
"""
from __future__ import annotations

import datetime
import glob
import json
import os
from typing import Any
from collections.abc import Sequence
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import urlopen

import dask
import dask.array as da
import dask.dataframe as ddf
import h5py
import numpy as np
import scipy.interpolate as sint
from natsort import natsorted

from sed.loader.base.loader import BaseLoader


def hdf5_to_dataframe(
    files: Sequence[str],
    channels: dict[str, Any] = None,
    time_stamps: bool = False,
    time_stamp_alias: str = "timeStamps",
    ms_markers_group: str = "msMarkers",
    first_event_time_stamp_key: str = "FirstEventTimeStamp",
    **kwds,
) -> ddf.DataFrame:
    """Function to read a selection of hdf5-files, and generate a delayed dask
    dataframe from provided groups in the files. Optionally, aliases can be defined.

    Args:
        files (List[str]): A list of the file paths to load.
        channels (dict[str, str], optional): hdf5 channels names to load. Each entry in the dict
            should contain the keys "format" and "groupName". Defaults to load all groups
            containing "Stream", and to read the attribute "Name" from each group.
        time_stamps (bool, optional): Option to calculate time stamps. Defaults to
            False.
        time_stamp_alias (str): Alias name for the timestamp column.
            Defaults to "timeStamps".
        ms_markers_group (str): h5 column containing timestamp information.
            Defaults to "msMarkers".
        first_event_time_stamp_key (str): h5 attribute containing the start
            timestamp of a file. Defaults to "FirstEventTimeStamp".

    Returns:
        ddf.DataFrame: The delayed Dask DataFrame
    """
    # Read a file to parse the file structure
    test_fid = kwds.pop("test_fid", 0)
    test_proc = h5py.File(files[test_fid])

    if channels is None:
        channels = get_groups_and_aliases(
            h5file=test_proc,
            seach_pattern="Stream",
        )

    channel_list = [channel for channel in channels.values()]
    column_names = [name for name in channels.keys()]

    if time_stamps:
        column_names.append(time_stamp_alias)

    test_array = hdf5_to_array(
        h5file=test_proc,
        channels=channel_list,
        time_stamps=time_stamps,
        ms_markers_group=ms_markers_group,
        first_event_time_stamp_key=first_event_time_stamp_key,
    )

    # Delay-read all files
    arrays = [
        da.from_delayed(
            dask.delayed(hdf5_to_array)(
                h5file=h5py.File(f),
                channels=channel_list,
                time_stamps=time_stamps,
                ms_markers_group=ms_markers_group,
                first_event_time_stamp_key=first_event_time_stamp_key,
            ),
            dtype=test_array.dtype,
            shape=(test_array.shape[0], np.nan),
        )
        for f in files
    ]
    array_stack = da.concatenate(arrays, axis=1).T

    return ddf.from_dask_array(array_stack, columns=column_names)


def hdf5_to_timed_dataframe(
    files: Sequence[str],
    channels: dict[str, Any] = None,
    time_stamps: bool = False,
    time_stamp_alias: str = "timeStamps",
    ms_markers_group: str = "msMarkers",
    first_event_time_stamp_key: str = "FirstEventTimeStamp",
    **kwds,
) -> ddf.DataFrame:
    """Function to read a selection of hdf5-files, and generate a delayed dask
    dataframe from provided groups in the files. Optionally, aliases can be defined.
    Returns a dataframe for evenly spaced time intervals.

    Args:
        files (List[str]): A list of the file paths to load.
        channels (dict[str, str], optional): hdf5 channels names to load. Each entry in the dict
            should contain the keys "format" and "groupName". Defaults to load all groups
            containing "Stream", and to read the attribute "Name" from each group.
        time_stamps (bool, optional): Option to calculate time stamps. Defaults to
            False.
        time_stamp_alias (str): Alias name for the timestamp column.
            Defaults to "timeStamps".
        ms_markers_group (str): h5 column containing timestamp information.
            Defaults to "msMarkers".
        first_event_time_stamp_key (str): h5 attribute containing the start
            timestamp of a file. Defaults to "FirstEventTimeStamp".

    Returns:
        ddf.DataFrame: The delayed Dask DataFrame
    """
    # Read a file to parse the file structure
    test_fid = kwds.pop("test_fid", 0)
    test_proc = h5py.File(files[test_fid])

    if channels is None:
        channels = get_groups_and_aliases(
            h5file=test_proc,
            seach_pattern="Stream",
        )

    channel_list = [channel for channel in channels.values()]
    column_names = [name for name in channels.keys()]

    if time_stamps:
        column_names.append(time_stamp_alias)

    test_array = hdf5_to_timed_array(
        h5file=test_proc,
        channels=channel_list,
        time_stamps=time_stamps,
        ms_markers_group=ms_markers_group,
        first_event_time_stamp_key=first_event_time_stamp_key,
    )

    # Delay-read all files
    arrays = [
        da.from_delayed(
            dask.delayed(hdf5_to_timed_array)(
                h5file=h5py.File(f),
                channels=channel_list,
                time_stamps=time_stamps,
                ms_markers_group=ms_markers_group,
                first_event_time_stamp_key=first_event_time_stamp_key,
            ),
            dtype=test_array.dtype,
            shape=(test_array.shape[0], np.nan),
        )
        for f in files
    ]
    array_stack = da.concatenate(arrays, axis=1).T

    return ddf.from_dask_array(array_stack, columns=column_names)


def get_groups_and_aliases(
    h5file: h5py.File,
    seach_pattern: str = None,
    alias_key: str = "Name",
) -> dict[str, Any]:
    """Read groups and aliases from a provided hdf5 file handle

    Args:
        h5file (h5py.File):
            The hdf5 file handle
        seach_pattern (str, optional):
            Search pattern to select groups. Defaults to include all groups.
        alias_key (str, optional):
            Attribute key where aliases are stored. Defaults to "Name".

    Returns:
        dict[str, Any]:
        A dict of aliases and groupnames parsed from the file
    """
    # get group names:
    group_names = list(h5file)

    # Filter the group names
    if seach_pattern is None:
        filtered_group_names = group_names
    else:
        filtered_group_names = [name for name in group_names if seach_pattern in name]

    alias_dict = {}
    for name in filtered_group_names:
        alias_dict[name] = get_attribute(h5file[name], alias_key)

    return {
        alias_dict[name]: {"format": "per_electron", "group_name": name}
        for name in filtered_group_names
    }


def hdf5_to_array(
    h5file: h5py.File,
    channels: Sequence[Dict[str, Any]],
    time_stamps=False,
    ms_markers_group: str = "msMarkers",
    first_event_time_stamp_key: str = "FirstEventTimeStamp",
) -> np.ndarray:
    """Reads the content of the given groups in an hdf5 file, and returns a
    2-dimensional array with the corresponding values.

    Args:
        h5file (h5py.File):
            hdf5 file handle to read from
        electron_channels (Sequence[Dict[str, any]]):
            channel dicts containing group names and types to read.
        time_stamps (bool, optional):
            Option to calculate time stamps. Defaults to False.
        ms_markers_group (str): h5 column containing timestamp information.
            Defaults to "msMarkers".
        first_event_time_stamp_key (str): h5 attribute containing the start
            timestamp of a file. Defaults to "FirstEventTimeStamp".

    Returns:
        np.ndarray: The 2-dimensional data array containing the values of the groups.
    """

    # Delayed array for loading an HDF5 file of reasonable size (e.g. < 1GB)

    # determine group length from per_electron column:
    nelectrons = 0
    for channel in channels:
        if channel["format"] == "per_electron":
            nelectrons = len(h5file[channel["group_name"]])
            break
    if nelectrons == 0:
        raise ValueError("No 'per_electron' columns defined, or no hits found in file.")

    # Read out groups:
    data_list = []
    for channel in channels:
        if channel["format"] == "per_electron":
            g_dataset = np.asarray(h5file[channel["group_name"]])
        elif channel["format"] == "per_file":
            value = float(get_attribute(h5file, channel["group_name"]))
            g_dataset = np.asarray([value] * nelectrons)
        else:
            raise ValueError(
                f"Invalid 'format':{channel['format']} for channel {channel['group_name']}.",
            )
        if "data_type" in channel.keys():
            g_dataset = g_dataset.astype(channel["data_type"])
        else:
            g_dataset = g_dataset.astype("float32")
        if len(g_dataset) != nelectrons:
            raise ValueError(f"Inconsistent entries found for channel {channel['group_name']}.")
        data_list.append(g_dataset)

    # calculate time stamps
    if time_stamps:
        # create target array for time stamps
        time_stamp_data = np.zeros(nelectrons)
        # the ms marker contains a list of events that occurred at full ms intervals.
        # It's monotonically increasing, and can contain duplicates
        ms_marker = np.asarray(h5file[ms_markers_group])

        # try to get start timestamp from "FirstEventTimeStamp" attribute
        try:
            start_time_str = get_attribute(h5file, first_event_time_stamp_key)
            start_time = datetime.datetime.strptime(
                start_time_str,
                "%Y-%m-%dT%H:%M:%S.%f%z",
            ).timestamp()
        except KeyError:
            # get the start time of the file from its modification date if the key
            # does not exist (old files)
            start_time = os.path.getmtime(h5file.filename)  # convert to ms
            # the modification time points to the time when the file was finished, so we
            # need to correct for the time it took to write the file
            start_time -= len(ms_marker) / 1000

        # fill in range before 1st marker
        time_stamp_data[0 : ms_marker[0]] = start_time
        for i in range(len(ms_marker) - 1):
            # linear interpolation between ms: Disabled, because it takes a lot of
            # time, and external signals are anyway not better synchronized than 1 ms
            # time_stamp_data[ms_marker[n] : ms_marker[n + 1]] = np.linspace(
            #     start_time + n,
            #     start_time + n + 1,
            #     ms_marker[n + 1] - ms_marker[n],
            # )
            time_stamp_data[ms_marker[i] : ms_marker[i + 1]] = start_time + (i + 1) / 1000
        # fill any remaining points
        time_stamp_data[ms_marker[len(ms_marker) - 1] : len(time_stamp_data)] = (
            start_time + len(ms_marker) / 1000
        )

        data_list.append(time_stamp_data.astype("float32"))

    return np.asarray(data_list)


def hdf5_to_timed_array(
    h5file: h5py.File,
    channels: Sequence[Dict[str, Any]],
    time_stamps=False,
    ms_markers_group: str = "msMarkers",
    first_event_time_stamp_key: str = "FirstEventTimeStamp",
) -> np.ndarray:
    """Reads the content of the given groups in an hdf5 file, and returns a
    timed version of a 2-dimensional array with the corresponding values.

    Args:
        h5file (h5py.File):
            hdf5 file handle to read from
        electron_channels (Sequence[Dict[str, any]]):
            channel dicts containing group names and types to read.
        time_stamps (bool, optional):
            Option to calculate time stamps. Defaults to False.
        ms_markers_group (str): h5 column containing timestamp information.
            Defaults to "msMarkers".
        first_event_time_stamp_key (str): h5 attribute containing the start
            timestamp of a file. Defaults to "FirstEventTimeStamp".

    Returns:
        np.ndarray: the array of the values at evently spaced timing obtained from
        the ms_markers.
    """

    # Delayed array for loading an HDF5 file of reasonable size (e.g. < 1GB)

    # Read out groups:
    data_list = []
    ms_marker = np.asarray(h5file[ms_markers_group])
    for channel in channels:
        timed_dataset = np.zeros_like(ms_marker)
        if channel["format"] == "per_electron":
            g_dataset = np.asarray(h5file[channel["group_name"]])
            for i, point in enumerate(ms_marker):
                timed_dataset[i] = g_dataset[int(point) - 1]
        elif channel["format"] == "per_file":
            value = float(get_attribute(h5file, channel["group_name"]))
            timed_dataset[:] = value
        else:
            raise ValueError(
                f"Invalid 'format':{channel['format']} for channel {channel['group_name']}.",
            )
        if "data_type" in channel.keys():
            timed_dataset = timed_dataset.astype(channel["data_type"])
        else:
            timed_dataset = timed_dataset.astype("float32")

        data_list.append(timed_dataset)

    # calculate time stamps
    if time_stamps:
        # try to get start timestamp from "FirstEventTimeStamp" attribute
        try:
            start_time_str = get_attribute(h5file, first_event_time_stamp_key)
            start_time = datetime.datetime.strptime(
                start_time_str,
                "%Y-%m-%dT%H:%M:%S.%f%z",
            ).timestamp()
        except KeyError:
            # get the start time of the file from its modification date if the key
            # does not exist (old files)
            start_time = os.path.getmtime(h5file.filename)  # convert to ms
            # the modification time points to the time when the file was finished, so we
            # need to correct for the time it took to write the file
            start_time -= len(ms_marker) / 1000

        time_stamp_data = start_time + np.arange(len(ms_marker)) / 1000

        data_list.append(time_stamp_data.astype("float32"))

    return np.asarray(data_list)


def get_attribute(h5group: h5py.Group, attribute: str) -> str:
    """Reads, decodes and returns an attrubute from an hdf5 group

    Args:
        h5group (h5py.Group):
            The hdf5 group to read from
        attribute (str):
            The name of the attribute

    Returns:
        str: The parsed attribute data
    """
    try:
        content = h5group.attrs[attribute].decode("utf-8")
    except AttributeError:  # No need to decode
        content = h5group.attrs[attribute]
    except KeyError as exc:  # No such attribute
        raise KeyError(f"Attribute '{attribute}' not found!") from exc

    return content


def get_count_rate(
    h5file: h5py.File,
    ms_markers_group: str = "msMarkers",
) -> tuple[np.ndarray, np.ndarray]:
    """Create count rate in the file from the msMarker column.

    Args:
        h5file (h5py.File): The h5file from which to get the count rate.
        ms_markers_group (str, optional): The hdf5 group where the millisecond markers
            are stored. Defaults to "msMarkers".

    Returns:
        tuple[np.ndarray, np.ndarray]: The count rate in Hz and the seconds into the
        scan.
    """
    ms_markers = np.asarray(h5file[ms_markers_group])
    secs = np.arange(0, len(ms_markers)) / 1000
    msmarker_spline = sint.InterpolatedUnivariateSpline(secs, ms_markers, k=1)
    rate_spline = msmarker_spline.derivative()
    count_rate = rate_spline(secs)

    return (count_rate, secs)


def get_elapsed_time(
    h5file: h5py.File,
    ms_markers_group: str = "msMarkers",
) -> float:
    """Return the elapsed time in the file from the msMarkers wave

    Args:
        h5file (h5py.File): The h5file from which to get the count rate.
        ms_markers_group (str, optional): The hdf5 group where the millisecond markers
            are stored. Defaults to "msMarkers".

    Return:
        float: The acquision time of the file in seconds.
    """
    secs = h5file[ms_markers_group].len() / 1000

    return secs


def get_archiver_data(
    archiver_url: str,
    archiver_channel: str,
    ts_from: float,
    ts_to: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract time stamps and corresponding data from and EPICS archiver instance

    Args:
        archiver_url (str): URL of the archiver data extraction interface
        archiver_channel (str): EPICS channel to extract data for
        ts_from (float): starting time stamp of the range of interest
        ts_to (float): ending time stamp of the range of interest

    Returns:
        tuple[np.ndarray, np.ndarray]: The extracted time stamps and corresponding data
    """
    iso_from = datetime.datetime.utcfromtimestamp(ts_from).isoformat()
    iso_to = datetime.datetime.utcfromtimestamp(ts_to).isoformat()
    req_str = archiver_url + archiver_channel + "&from=" + iso_from + "Z&to=" + iso_to + "Z"
    with urlopen(req_str) as req:
        data = json.load(req)
        secs = [x["secs"] + x["nanos"] * 1e-9 for x in data[0]["data"]]
        vals = [x["val"] for x in data[0]["data"]]

    return (np.asarray(secs), np.asarray(vals))


class MpesLoader(BaseLoader):
    """Mpes implementation of the Loader. Reads from h5 files or folders of the
    SPECS Metis 1000 (FHI Berlin)

    Args:
        config (dict, optional): Config dictionary. Defaults to None.
        meta_handler (MetaHandler, optional): MetaHandler object. Defaults to None.
    """

    __name__ = "mpes"

    supported_file_types = ["h5"]

    def __init__(
        self,
        config: dict = None,
    ):
        super().__init__(config=config)

        self.read_timestamps = self._config.get("dataframe", {}).get(
            "read_timestamps",
            False,
        )

    def read_dataframe(
        self,
        files: str | Sequence[str] = None,
        folders: str | Sequence[str] = None,
        runs: str | Sequence[str] = None,
        ftype: str = "h5",
        metadata: dict = None,
        collect_metadata: bool = False,
        time_stamps: bool = False,
        **kwds,
    ) -> tuple[ddf.DataFrame, ddf.DataFrame, dict]:
        """Read stored hdf5 files from a list or from folder and returns a dask
        dataframe and corresponding metadata.

        Args:
            files (str | Sequence[str], optional): File path(s) to process.
                Defaults to None.
            folders (str | Sequence[str], optional): Path to folder(s) where files
                are stored. Path has priority such that if it's specified, the specified
                files will be ignored. Defaults to None.
            runs (str | Sequence[str], optional): Run identifier(s). Corresponding
                files will be located in the location provided by ``folders``. Takes
                precendence over ``files`` and ``folders``. Defaults to None.
            ftype (str, optional): File extension to use. If a folder path is given,
                all files with the specified extension are read into the dataframe
                in the reading order. Defaults to "h5".
            metadata (dict, optional): Manual meta data dictionary. Auto-generated
                meta data are added to it. Defaults to None.
            collect_metadata (bool): Option to collect metadata from files. Requires
                a valid config dict. Defaults to False.
            time_stamps (bool, optional): Option to create a time_stamp column in
                the dataframe from ms-Markers in the files. Defaults to False.
            **kwds: Keyword parameters.

                - **hdf5_groupnames** : List of groupnames to look for in the file.
                - **hdf5_aliases**: Dictionary of aliases for the groupnames.
                - **time_stamp_alias**: Alias for the timestamp column
                - **ms_markers_group**: Group name of the millisecond marker column.
                - **first_event_time_stamp_key**: Attribute name containing the start
                  timestamp of the file.

                Additional keywords are passed to ``hdf5_to_dataframe``.

        Raises:
            ValueError: raised if neither files or folder provided.
            FileNotFoundError: Raised if a file or folder is not found.

        Returns:
            tuple[ddf.DataFrame, ddf.DataFrame, dict]: Dask dataframe, timed Dask
            dataframe and metadata read from specified files.
        """
        # if runs is provided, try to locate the respective files relative to the provided folder.
        if runs is not None:  # pylint: disable=duplicate-code
            files = []
            if isinstance(runs, (str, int)):
                runs = [runs]
            for run in runs:
                files.extend(
                    self.get_files_from_run_id(run_id=run, folders=folders, extension=ftype),
                )
            self.runs = list(runs)
            super().read_dataframe(
                files=files,
                ftype=ftype,
                metadata=metadata,
            )
        else:
            # pylint: disable=duplicate-code
            super().read_dataframe(
                files=files,
                folders=folders,
                runs=runs,
                ftype=ftype,
                metadata=metadata,
            )

        channels = kwds.pop(
            "channels",
            self._config.get("dataframe", {}).get("channels", []),
        )
        time_stamp_alias = kwds.pop(
            "time_stamp_alias",
            self._config.get("dataframe", {}).get(
                "time_stamp_alias",
                "timeStamps",
            ),
        )
        ms_markers_group = kwds.pop(
            "ms_markers_group",
            self._config.get("dataframe", {}).get(
                "ms_markers_group",
                "msMarkers",
            ),
        )
        first_event_time_stamp_key = kwds.pop(
            "first_event_time_stamp_key",
            self._config.get("dataframe", {}).get(
                "first_event_time_stamp_key",
                "FirstEventTimeStamp",
            ),
        )
        df = hdf5_to_dataframe(
            files=self.files,
            channels=channels,
            time_stamps=time_stamps,
            time_stamp_alias=time_stamp_alias,
            ms_markers_group=ms_markers_group,
            first_event_time_stamp_key=first_event_time_stamp_key,
            **kwds,
        )
        timed_df = hdf5_to_timed_dataframe(
            files=self.files,
            channels=channels,
            time_stamps=time_stamps,
            time_stamp_alias=time_stamp_alias,
            ms_markers_group=ms_markers_group,
            first_event_time_stamp_key=first_event_time_stamp_key,
            **kwds,
        )

        if collect_metadata:
            metadata = self.gather_metadata(
                files=self.files,
                metadata=self.metadata,
            )
        else:
            metadata = self.metadata

        return df, timed_df, metadata

    def get_files_from_run_id(
        self,
        run_id: str,
        folders: str | Sequence[str] = None,
        extension: str = "h5",
        **kwds,  # noqa: ARG002
    ) -> list[str]:
        """Locate the files for a given run identifier.

        Args:
            run_id (str): The run identifier to locate.
            folders (str | Sequence[str], optional): The directory(ies) where the raw
                data is located. Defaults to config["core"]["base_folder"]
            extension (str, optional): The file extension. Defaults to "h5".
            kwds: Keyword arguments

        Return:
            list[str]: List of file path strings to the location of run data.
        """
        if folders is None:
            folders = self._config["core"]["paths"]["data_raw_dir"]

        if isinstance(folders, str):
            folders = [folders]

        files: list[str] = []
        for folder in folders:
            run_files = natsorted(
                glob.glob(
                    folder + "/**/Scan" + str(run_id).zfill(4) + "_*." + extension,
                    recursive=True,
                ),
            )
            files.extend(run_files)

        # Check if any files are found
        if not files:
            raise FileNotFoundError(
                f"No files found for run {run_id} in directory {str(folders)}",
            )

        # Return the list of found files
        return files

    def get_start_and_end_time(self) -> tuple[float, float]:
        """Extract the start and end time stamps from the loaded files

        Returns:
            tuple[float, float]: A tuple containing the start and end time stamps
        """
        h5file = h5py.File(self.files[0])
        timestamps = hdf5_to_array(
            h5file,
            channels=self._config["dataframe"]["channels"],
            time_stamps=True,
        )
        ts_from = timestamps[-1][1]
        h5file = h5py.File(self.files[-1])
        timestamps = hdf5_to_array(
            h5file,
            channels=self._config["dataframe"]["channels"],
            time_stamps=True,
        )
        ts_to = timestamps[-1][-1]
        return (ts_from, ts_to)

    def gather_metadata(
        self,
        files: Sequence[str],
        metadata: dict = None,
    ) -> dict:
        """Collect meta data from files

        Args:
            files (Sequence[str]): List of files loaded
            metadata (dict, optional): Manual meta data dictionary. Auto-generated
                meta data are added to it. Defaults to None.

        Returns:
            dict: The completed metadata dictionary.
        """

        if metadata is None:
            metadata = {}
        print("Gathering metadata from different locations")
        # Read events in with ms time stamps
        print("Collecting time stamps...")
        (ts_from, ts_to) = self.get_start_and_end_time()

        metadata["timing"] = {
            "acquisition_start": datetime.datetime.utcfromtimestamp(ts_from)
            .replace(tzinfo=datetime.timezone.utc)
            .isoformat(),
            "acquisition_stop": datetime.datetime.utcfromtimestamp(ts_to)
            .replace(tzinfo=datetime.timezone.utc)
            .isoformat(),
            "acquisition_duration": int(ts_to - ts_from),
            "collection_time": float(ts_to - ts_from),
        }

        # import meta data from data file
        if "file" not in metadata:  # If already present, the value is assumed to be a dictionary
            metadata["file"] = {}

        print("Collecting file metadata...")
        with h5py.File(files[0], "r") as h5file:
            for key, value in h5file.attrs.items():
                key = key.replace("VSet", "V")
                metadata["file"][key] = value

        metadata["entry_identifier"] = os.path.dirname(
            os.path.realpath(files[0]),
        )

        print("Collecting data from the EPICS archive...")
        # Get metadata from Epics archive if not present already
        epics_channels = self._config["metadata"]["epics_pvs"]

        start = datetime.datetime.utcfromtimestamp(ts_from).isoformat()

        channels_missing = set(epics_channels) - set(
            metadata["file"].keys(),
        )
        for channel in channels_missing:
            try:
                _, vals = get_archiver_data(
                    archiver_url=self._config["metadata"].get("archiver_url"),
                    archiver_channel=channel,
                    ts_from=ts_from,
                    ts_to=ts_to,
                )
                metadata["file"][f"{channel}"] = np.mean(vals)

            except IndexError:
                metadata["file"][f"{channel}"] = np.nan
                print(
                    f"Data for channel {channel} doesn't exist for time {start}",
                )
            except HTTPError as exc:
                print(
                    f"Incorrect URL for the archive channel {channel}. "
                    "Make sure that the channel name and file start and end times are "
                    "correct.",
                )
                print("Error code: ", exc)
            except URLError as exc:
                print(
                    f"Cannot access the archive URL for channel {channel}. "
                    f"Make sure that you are within the FHI network."
                    f"Skipping over channels {channels_missing}.",
                )
                print("Error code: ", exc)
                break

        # Determine the correct aperture_config
        stamps = sorted(
            list(self._config["metadata"]["aperture_config"]) + [start],
        )
        current_index = stamps.index(start)
        timestamp = stamps[current_index - 1]  # pick last configuration before file date

        # Aperture metadata
        if "instrument" not in metadata.keys():
            metadata["instrument"] = {"analyzer": {}}
        metadata["instrument"]["analyzer"]["fa_shape"] = "circle"
        metadata["instrument"]["analyzer"]["ca_shape"] = "circle"
        metadata["instrument"]["analyzer"]["fa_size"] = np.nan
        metadata["instrument"]["analyzer"]["ca_size"] = np.nan
        # get field aperture shape and size
        if {
            self._config["metadata"]["fa_in_channel"],
            self._config["metadata"]["fa_hor_channel"],
        }.issubset(set(metadata["file"].keys())):
            fa_in = metadata["file"][self._config["metadata"]["fa_in_channel"]]
            fa_hor = metadata["file"][self._config["metadata"]["fa_hor_channel"]]
            for key, value in self._config["metadata"]["aperture_config"][timestamp][
                "fa_size"
            ].items():
                if value[0][0] < fa_in < value[0][1] and value[1][0] < fa_hor < value[1][1]:
                    try:
                        k_float = float(key)
                        metadata["instrument"]["analyzer"]["fa_size"] = k_float
                    except ValueError:  # store string if numeric interpretation fails
                        metadata["instrument"]["analyzer"]["fa_shape"] = key
                    break
            else:
                print("Field aperture size not found.")

        # get contrast aperture shape and size
        if self._config["metadata"]["ca_in_channel"] in metadata["file"]:
            ca_in = metadata["file"][self._config["metadata"]["ca_in_channel"]]
            for key, value in self._config["metadata"]["aperture_config"][timestamp][
                "ca_size"
            ].items():
                if value[0] < ca_in < value[1]:
                    try:
                        k_float = float(key)
                        metadata["instrument"]["analyzer"]["ca_size"] = k_float
                    except ValueError:  # store string if numeric interpretation fails
                        metadata["instrument"]["analyzer"]["ca_shape"] = key
                    break
            else:
                print("Contrast aperture size not found.")

        # Storing the lens modes corresponding to lens voltages.
        # Use lens volages present in first lens_mode entry.
        lens_list = self._config["metadata"]["lens_mode_config"][
            next(iter(self._config["metadata"]["lens_mode_config"]))
        ].keys()

        lens_volts = np.array(
            [metadata["file"].get(f"KTOF:Lens:{lens}:V", np.nan) for lens in lens_list],
        )
        for mode, value in self._config["metadata"]["lens_mode_config"].items():
            lens_volts_config = np.array([value[k] for k in lens_list])
            if np.allclose(
                lens_volts,
                lens_volts_config,
                rtol=0.005,
            ):  # Equal upto 0.5% tolerance
                metadata["instrument"]["analyzer"]["lens_mode"] = mode
                break
        else:
            print(
                "Lens mode for given lens voltages not found. "
                "Storing lens mode from the user, if provided.",
            )

        # Determining projection from the lens mode
        try:
            lens_mode = metadata["instrument"]["analyzer"]["lens_mode"]
            if "spatial" in lens_mode.split("_")[1]:
                metadata["instrument"]["analyzer"]["projection"] = "real"
                metadata["instrument"]["analyzer"]["scheme"] = "momentum dispersive"
            else:
                metadata["instrument"]["analyzer"]["projection"] = "reciprocal"
                metadata["instrument"]["analyzer"]["scheme"] = "spatial dispersive"
        except IndexError:
            print(
                "Lens mode must have the form, '6kV_kmodem4.0_20VTOF_v3.sav'. "
                "Can't determine projection. "
                "Storing projection from the user, if provided.",
            )
        except KeyError:
            print(
                "Lens mode not found. Can't determine projection. "
                "Storing projection from the user, if provided.",
            )

        return metadata

    def get_count_rate(
        self,
        fids: Sequence[int] = None,
        **kwds,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Create count rate from the msMarker column for the files specified in
        ``fids``.

        Args:
            fids (Sequence[int], optional): fids (Sequence[int]): the file ids to
                include. Defaults to list of all file ids.
            kwds: Keyword arguments:

                - **ms_markers_group**: Name of the hdf5 group containing the ms-markers

        Returns:
            tuple[np.ndarray, np.ndarray]: Arrays containing countrate and seconds
            into the scan.
        """
        if fids is None:
            fids = range(0, len(self.files))

        ms_markers_group = kwds.pop(
            "ms_markers_group",
            self._config.get("dataframe", {}).get(
                "ms_markers_group",
                "msMarkers",
            ),
        )

        secs_list = []
        count_rate_list = []
        accumulated_time = 0
        for fid in fids:
            count_rate_, secs_ = get_count_rate(
                h5py.File(self.files[fid]),
                ms_markers_group=ms_markers_group,
            )
            secs_list.append((accumulated_time + secs_).T)
            count_rate_list.append(count_rate_.T)
            accumulated_time += secs_[-1]

        count_rate = np.concatenate(count_rate_list)
        secs = np.concatenate(secs_list)

        return count_rate, secs

    def get_elapsed_time(self, fids: Sequence[int] = None, **kwds) -> float:
        """Return the elapsed time in the files specified in ``fids`` from
        the msMarkers column.

        Args:
            fids (Sequence[int], optional): fids (Sequence[int]): the file ids to
                include. Defaults to list of all file ids.
            kwds: Keyword arguments:

                - **ms_markers_group**: Name of the hdf5 group containing the ms-markers

        Return:
            float: The elapsed time in the files in seconds.
        """
        if fids is None:
            fids = range(0, len(self.files))

        ms_markers_group = kwds.pop(
            "ms_markers_group",
            self._config.get("dataframe", {}).get(
                "ms_markers_group",
                "msMarkers",
            ),
        )

        secs = 0.0
        for fid in fids:
            secs += get_elapsed_time(
                h5py.File(self.files[fid]),
                ms_markers_group=ms_markers_group,
            )

        return secs


LOADER = MpesLoader

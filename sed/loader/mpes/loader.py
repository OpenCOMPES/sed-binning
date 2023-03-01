"""
module sed.loader.mpes, code for loading hdf5 files delayed into a dask dataframe.
Mostly ported from https://github.com/mpes-kit/mpes.
@author: L. Rettig
"""
import datetime
import json
import os
import urllib
from typing import Dict
from typing import List
from typing import Sequence
from typing import Tuple

import dask
import dask.array as da
import dask.dataframe as ddf
import h5py
import numpy as np
import scipy.interpolate as sint

from sed.core.metadata import MetaHandler
from sed.loader.base.loader import BaseLoader
from sed.loader.utils import gather_files


def hdf5_to_dataframe(
    files: Sequence[str],
    group_names: Sequence[str] = None,
    alias_dict: Dict[str, str] = None,
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
        group_names (List[str], optional): hdf5 group names to load. Defaults to load
            all groups containing "Stream"
        alias_dict (Dict[str, str], optional): Dictionary of aliases for the dataframe
            columns. Keys are the hdf5 groupnames, and values the aliases. If an alias
            is not found, its group name is used. Defaults to read the attribute
            "Name" from each group.
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
    if group_names is None:
        group_names = []
    if alias_dict is None:
        alias_dict = {}

    # Read a file to parse the file structure
    test_fid = kwds.pop("test_fid", 0)
    test_proc = h5py.File(files[test_fid])
    if group_names == []:
        group_names, alias_dict = get_groups_and_aliases(
            h5file=test_proc,
            seach_pattern="Stream",
        )

    column_names = [alias_dict.get(group, group) for group in group_names]

    if time_stamps:
        column_names.append(time_stamp_alias)

    test_array = hdf5_to_array(
        h5file=test_proc,
        group_names=group_names,
        time_stamps=time_stamps,
        ms_markers_group=ms_markers_group,
        first_event_time_stamp_key=first_event_time_stamp_key,
    )

    # Delay-read all files
    arrays = [
        da.from_delayed(
            dask.delayed(hdf5_to_array)(
                h5file=h5py.File(f),
                group_names=group_names,
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
) -> Tuple[List[str], Dict[str, str]]:
    """Read groups and aliases from a provided hdf5 file handle

    Args:
        h5file (h5py.File):
            The hdf5 file handle
        seach_pattern (str, optional):
            Search pattern to select groups. Defaults to include all groups.
        alias_key (str, optional):
            Attribute key where aliases are stored. Defaults to "Name".

    Returns:
        Tuple[List[str], Dict[str, str]]:
            The list of groupnames and the alias dictionary parsed from the file
    """
    # get group names:
    group_names = list(h5file)

    # Filter the group names
    if seach_pattern is None:
        filtered_group_names = group_names
    else:
        filtered_group_names = [
            name for name in group_names if seach_pattern in name
        ]

    alias_dict = {}
    for name in filtered_group_names:
        alias_dict[name] = get_attribute(h5file[name], alias_key)

    return filtered_group_names, alias_dict


def hdf5_to_array(
    h5file: h5py.File,
    group_names: Sequence[str],
    data_type: str = "float32",
    time_stamps=False,
    ms_markers_group: str = "msMarkers",
    first_event_time_stamp_key: str = "FirstEventTimeStamp",
) -> np.ndarray:
    """Reads the content of the given groups in an hdf5 file, and returns a
    2-dimensional array with the corresponding values.

    Args:
        h5file (h5py.File):
            hdf5 file handle to read from
        group_names (str):
            group names to read
        data_type (str, optional):
            Data type of the output data. Defaults to "float32".
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

    # Read out groups:
    data_list = []
    for group in group_names:

        g_dataset = np.asarray(h5file[group])
        if bool(data_type):
            g_dataset = g_dataset.astype(data_type)
        data_list.append(g_dataset)

    # calculate time stamps
    if time_stamps:
        # create target array for time stamps
        time_stamp_data = np.zeros(len(data_list[0]))
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
            time_stamp_data[ms_marker[i] : ms_marker[i + 1]] = (
                start_time + i / 1000
            )
        # fill any remaining points
        time_stamp_data[
            ms_marker[len(ms_marker) - 1] : len(time_stamp_data)
        ] = start_time + len(ms_marker)

        data_list.append(time_stamp_data)

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


def parse_metadata(
    files: Sequence[str],
) -> dict:
    """Parses file metadata and returns corresponding dictionary

    Args:
        files (Sequence[str]): List of files from which to read metadata.

    Returns:
        dict: Metadata dictionary.
    """

    metadata_dict = {}
    metadata_dict["name"] = "loader"
    # Get time ranges

    return {}


def get_count_rate(
    h5file: h5py.File,
    ms_markers_group: str = "msMarkers",
) -> Tuple[np.ndarray, np.ndarray]:
    """Create count rate in the file from the msMarker column.

    Args:
        h5file (h5py.File): The h5file from which to get the count rate.
        ms_markers_group (str, optional): The hdf5 group where the millisecond markers
            are stored. Defaults to "msMarkers".

    Returns:
        Tuple[np.ndarray, np.ndarray]: The count rate in Hz and the seconds into the
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
        meta_handler: MetaHandler = None,
    ):
        super().__init__(config=config, meta_handler=meta_handler)

        self.read_timestamps = self._config.get("dataframe", {}).get(
            "read_timestamps",
            False,
        )

        self.files: List[str] = []

    def read_dataframe(
        self,
        files: Sequence[str] = None,
        folder: str = None,
        metadata: dict = None,
        ftype: str = "h5",
        time_stamps: bool = False,
        **kwds,
    ) -> Tuple[ddf.DataFrame, dict]:
        """Read stored hdf5 files from a list or from folder into a dataframe.

        Args:
            files (Sequence[str], optional): List of file paths. Defaults to None.
            folder (str, optional): Path to folder where files are stored. Path has
                the priority such that if it's specified, the specified files will
                be ignored. Defaults to None.
            ftype (str, optional): File extension to use. If a folder path is given,
                all files with the specified extension are read into the dataframe
                in the reading order. Defaults to "h5".
            time_stamps (bool, optional): Option to create a time_stamp column in
                the dataframe from ms-Markers in the files. Defaults to False.
            **kwds: Keyword parameters for gather_files.

        Raises:
            ValueError: raised if neither files or folder provided.
            FileNotFoundError: Raised if a file or folder is not found.

        Returns:
            Tuple[ddf.DataFrame, dict]: Dask dataframe and metadata read from specified
            files.
        """
        # pylint: disable=duplicate-code
        if folder is not None:
            folder = os.path.realpath(folder)
            files = gather_files(
                folder=folder,
                extension=ftype,
                file_sorting=True,
                **kwds,
            )

        elif folder is None:
            if files is None:
                raise ValueError(
                    "Either the folder or file path should be provided!",
                )
            files = [os.path.realpath(file) for file in files]

        self.files = files

        if not files:
            raise FileNotFoundError("No valid files found!")

        hdf5_groupnames = kwds.pop(
            "hdf5_groupnames",
            self._config.get("dataframe", {}).get("hdf5_groupnames", []),
        )
        hdf5_aliases = kwds.pop(
            "hdf5_aliases",
            self._config.get("dataframe", {}).get("hdf5_aliases", {}),
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
            files=files,
            group_names=hdf5_groupnames,
            alias_dict=hdf5_aliases,
            time_stamps=time_stamps,
            time_stamp_alias=time_stamp_alias,
            ms_markers_group=ms_markers_group,
            first_event_time_stamp_key=first_event_time_stamp_key,
            **kwds,
        )

        metadata = self.gather_metadata(files=files, metadata=metadata)

        return df, metadata

    def gather_metadata(self, files: Sequence[str], metadata: dict = None):

        if metadata is None:
            metadata = {}
        print("Gathering metadata from different locations")
        # Read events in with ms time stamps
        print("Collecting time stamps...")

        hf = h5py.File(files[0])
        timestamps = hdf5_to_array(
            hf,
            group_names=self._config["dataframe"]["hdf5_groupnames"],
            time_stamps=True,
        )
        tsFrom = timestamps[-1][1]
        hf = h5py.File(files[-1])
        timestamps = hdf5_to_array(
            hf,
            group_names=self._config["dataframe"]["hdf5_groupnames"],
            time_stamps=True,
        )
        tsTo = timestamps[-1][-1]

        metadata["timing"] = {
            "acquisition_start": datetime.datetime.utcfromtimestamp(tsFrom)
            .replace(tzinfo=datetime.timezone.utc)
            .isoformat(),
            "acquisition_stop": datetime.datetime.utcfromtimestamp(tsTo)
            .replace(tzinfo=datetime.timezone.utc)
            .isoformat(),
            "acquisition_duration": int(tsTo - tsFrom),
            "collection_time": float(tsTo - tsFrom),
        }

        # import meta data from data file
        if (
            "file" not in metadata
        ):  # If already present, the value is assumed to be a dictionary
            metadata["file"] = {}

        print("Collecting file metadata...")
        with h5py.File(files[0], "r") as f:
            for k, v in f.attrs.items():
                k = k.replace("VSet", "V")
                metadata["file"][k] = v

        metadata["entry_identifier"] = os.path.dirname(
            os.path.realpath(files[0]),
        )

        print("Collecting data from the EPICS archive...")
        # Get metadata from Epics archive if not present already
        start = datetime.datetime.utcfromtimestamp(tsFrom).isoformat()
        end = datetime.datetime.utcfromtimestamp(tsTo).isoformat()
        epics_channels = self._config["metadata"]["epics_pvs"]

        channels_missing = set(epics_channels) - set(
            metadata["file"].keys(),
        )
        for channel in channels_missing:
            try:
                req_str = (
                    "http://aa0.fhi-berlin.mpg.de:17668/retrieval/data/getData.json?pv="
                    + channel
                    + "&from="
                    + start
                    + "Z&to="
                    + end
                    + "Z"
                )
                req = urllib.request.urlopen(req_str)
                data = json.load(req)
                vals = [x["val"] for x in data[0]["data"]]
                metadata["file"][f"{channel}"] = np.mean(vals)

            except (IndexError):
                metadata["file"][f"{channel}"] = np.nan
                print(
                    f"Data for channel {channel} doesn't exist for time {start}",
                )
            except urllib.error.HTTPError as e:
                print(
                    f"Incorrect URL for the archive channel {channel}. "
                    "Make sure that the channel name and file start and end times are "
                    "correct.",
                )
                print("Error code: ", e)
            except urllib.error.URLError as e:
                print(
                    f"Cannot access the archive URL for channel {channel}. "
                    f"Make sure that you are within the FHI network."
                    f"Skipping over channels {channels_missing}.",
                )
                print("Error code: ", e)
                break

        # Determine the correct aperture_config
        stamps = sorted(
            list(self._config["metadata"]["aperture_config"]) + [start],
        )
        current_index = stamps.index(start)
        timestamp = stamps[
            current_index - 1
        ]  # pick last configuration before file date

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
            fa_hor = metadata["file"][
                self._config["metadata"]["fa_hor_channel"]
            ]
            for k, v in self._config["metadata"]["aperture_config"][timestamp][
                "fa_size"
            ].items():
                if v[0][0] < fa_in < v[0][1] and v[1][0] < fa_hor < v[1][1]:
                    if isinstance(k, float):
                        metadata["instrument"]["analyzer"]["fa_size"] = k
                    else:  # considering that only int and str type values are present
                        metadata["instrument"]["analyzer"]["fa_shape"] = k
                    break
            else:
                print("Field aperture size not found.")

        # get contrast aperture shape and size
        if self._config["metadata"]["ca_in_channel"] in metadata["file"]:
            ca_in = metadata["file"][self._config["metadata"]["ca_in_channel"]]
            for k, v in self._config["metadata"]["aperture_config"][timestamp][
                "ca_size"
            ].items():
                if v[0] < ca_in < v[1]:
                    if isinstance(k, float):
                        metadata["instrument"]["analyzer"]["ca_size"] = k
                    else:  # considering that only int and str type values are present
                        metadata["instrument"]["analyzer"]["ca_shape"] = k
                    break
            else:
                print("Contrast aperture size not found.")

        # Storing the lens modes corresponding to lens voltages.
        # Use lens volages present in first lens_mode entry.
        lens_list = self._config["metadata"]["lens_mode_config"][
            next(iter(self._config["metadata"]["lens_mode_config"]))
        ].keys()

        lens_volts = np.array(
            [metadata["file"][f"KTOF:Lens:{lens}:V"] for lens in lens_list],
        )
        for mode, v in self._config["metadata"]["lens_mode_config"].items():
            lens_volts_config = np.array([v[k] for k in lens_list])
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
            else:
                metadata["instrument"]["analyzer"]["projection"] = "reciprocal"
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
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Create count rate from the msMarker column for the files specified in
        ``fids``.

        Args:
            fids (Sequence[int], optional): fids (Sequence[int]): the file ids to
                include. Defaults to list of all file ids.
            kwds: Keyword arguments:

                - **ms_markers_group**: Name of the hdf5 group containing the ms-markers

        Returns:
            Tuple[np.ndarray, np.ndarray]: Arrays containing countrate and seconds
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

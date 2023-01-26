"""Utilities for loaders
"""
from glob import glob
from typing import cast
from typing import List
from pathlib import Path

from natsort import natsorted


def gather_files(
    folder: str,
    extension: str = "h5",
    f_start: int = None,
    f_end: int = None,
    f_step: int = 1,
    file_sorting: bool = True,
) -> List[str]:
    """
    Collects and sorts files with specified extension from a given folder.

    Parameters:
        folder: str
            The folder to search
        extension: str | r'/*.h5'
            File extension used for glob.glob().
        f_start, f_end, f_step: int, int, int | None, None, 1
            Starting, ending file id and the step. Used to construct a file selector.
        file_sorting: bool | True
            Option to sort the files by their names.
    """

    try:
        files = glob(folder + "/*." + extension)

        if file_sorting:
            files = cast(List[str], natsorted(files))

        if f_start is not None and f_end is not None:
            files = files[slice(f_start, f_end, f_step)]

    except FileNotFoundError:
        print("No legitimate folder address is specified for file retrieval!")
        raise

    return files

def gather_flash_files(
        run_number: int, daq: str, raw_data_dir: str, extension: str = "h5",
    ) -> List[Path]:
    """Returns all filenames of given run located in directory
    for the given daq."""
    stream_name_prefixes = {
        "pbd": "GMD_DATA_gmd_data",
        "pbd2": "FL2PhotDiag_pbd2_gmd_data",
        "fl1user1": "FLASH1_USER1_stream_2",
        "fl1user2": "FLASH1_USER2_stream_2",
        "fl1user3": "FLASH1_USER3_stream_2",
        "fl2user1": "FLASH2_USER1_stream_2",
        "fl2user2": "FLASH2_USER2_stream_2",
    }

    return sorted(Path(raw_data_dir).glob( f"{stream_name_prefixes[daq]}_run{run_number}_*."
                + extension), key=lambda filename: str(filename).rsplit("_", maxsplit=1)[-1])

def parse_h5_keys(h5_file, prefix=""):
    """Helper method which parses the channels present in the h5 file"""
    file_channel_list = []

    for key in h5_file.keys():
        try:
            [
                file_channel_list.append(s)
                for s in parse_h5_keys(h5_file[key], prefix=prefix + "/" + key)
            ]
        except Exception:
            file_channel_list.append(prefix + "/" + key)

    return file_channel_list
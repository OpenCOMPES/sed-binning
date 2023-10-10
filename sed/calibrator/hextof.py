"""sed.calibrator.hextof module. Code for handling hextof specific transformations and
calibrations.
"""
from typing import Sequence
from typing import Tuple
from typing import Union

import numpy as np
import pandas as pd
import dask.dataframe


def unravel_8s_detector_time_channel(
    df: dask.dataframe.DataFrame,
    time_sector_column: str = "dldTimeAndSector",
    tof_step_column: str = "dldTimeSteps",
    sector_id_column: str = "dldSectorID",
    config: dict = None,
) -> dask.dataframe.DataFrame:
    """Converts the 8s time in steps to time in steps and sectorID.

    The 8s detector encodes the dldSectorID in the 3 least significant bits of the
    dldTimeSteps channel.

    Args:
        sector_delays (Sequece[float], optional): Sector delays for the 8s time.
            Defaults to config["dataframe"]["sector_delays"].
    """
    df = df.dropna(subset=[time_sector_column])
    if time_sector_column is None:
        if config is None:
            raise ValueError("Either time_sector_column or config must be given.")
        time_sector_column = config["dataframe"]["time_sector_column"]
        if time_sector_column not in df.columns:
            raise ValueError(f"Column {time_sector_column} not in dataframe.")
    if tof_step_column is None:
        if config is None:
            raise ValueError("Either tof_step_column or config must be given.")
        tof_step_column = config["dataframe"]["tof_step_column"]
    if sector_id_column is None:
        if config is None:
            raise ValueError("Either sector_id_column or config must be given.")
        sector_id_column = config["dataframe"]["sector_id_column"]

    df[sector_id_column] = (df[time_sector_column] % 8).astype(np.int8)
    df[tof_step_column] = (df[time_sector_column] // 8).astype(np.int32)
    return df


def align_8s_sectors(
        df: dask.dataframe.DataFrame,
        sector_delays: Sequence[float] = None,
        sector_id_column: str = "dldSectorID",
        tof_step_column: str = "dldTimeSteps",
        config: dict = None,
) -> Tuple[Union[pd.DataFrame, dask.dataframe.DataFrame], dict]:
    """Aligns the 8s sectors to the first sector.

    Args:
        sector_delays (Sequece[float], optional): Sector delays for the 8s time.
        in units of step. Calibration should be done with binning along dldTimeSteps.
        Defaults to config["dataframe"]["sector_delays"].
    """
    if sector_delays is None:
        if config is None:
            raise ValueError("Either sector_delays or config must be given.")
        sector_delays = config["dataframe"]["sector_delays"]
    # align the 8s sectors
    sector_delays_arr = dask.array.from_array(sector_delays)

    def align_sector(x):
        return x[tof_step_column] - sector_delays_arr[x[sector_id_column].values.astype(int)]
    df[tof_step_column] = df.map_partitions(
        align_sector, meta=(tof_step_column, np.float64)
    )

    metadata = {}
    metadata["applied"] = True
    metadata["sector_delays"] = sector_delays

    return df, metadata


def convert_8s_time_to_ns(
        df: Union[pd.DataFrame, dask.dataframe.DataFrame],
        time_step_size: float = None,
        tof_step_column: str = "dldTimeSteps",
        tof_column: str = "dldTime",
        config: dict = None,
) -> Tuple[Union[pd.DataFrame, dask.dataframe.DataFrame], dict]:
    """Converts the 8s time in steps to time in ns.

    Args:
        time_step_size (float, optional): Time step size in nanoseconds.
            Defaults to config["dataframe"]["time_step_size"].
        tof_step_column (str, optional): Name of the column containing the
            time-of-flight steps. Defaults to config["dataframe"]["tof_step_column"].
        tof_column (str, optional): Name of the column containing the
            time-of-flight. Defaults to config["dataframe"]["tof_column"].
    """
    if time_step_size is None:
        if config is None:
            raise ValueError("Either time_step_size or config must be given.")
        time_step_size: float = config["dataframe"]["time_step_size"]
    if tof_step_column is None:
        if config is None:
            raise ValueError("Either tof_step_column or config must be given.")
        tof_step_column: str = config["dataframe"]["tof_step_column"]
    if tof_column is None:
        if config is None:
            raise ValueError("Either tof_time_column or config must be given.")
        tof_column: str = config["dataframe"]["tof_column"]

    def convert_to_ns(x):
        return x[tof_step_column] * time_step_size
    df[tof_column] = df.map_partitions(
        convert_to_ns, meta=(tof_column, np.float64)
    )
    metadata = {}
    metadata["applied"] = True
    metadata["time_step_size"] = time_step_size

    return df, metadata

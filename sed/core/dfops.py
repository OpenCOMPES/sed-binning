"""This module contains dataframe operations functions for the sed package

"""
# Note: some of the functions presented here were
# inspired by https://github.com/mpes-kit/mpes
from typing import Callable
from typing import Sequence
from typing import Union

import dask.dataframe
import numpy as np
import pandas as pd
from dask.diagnostics import ProgressBar


def apply_jitter(
    df: Union[pd.DataFrame, dask.dataframe.DataFrame],
    cols: Union[str, Sequence[str]],
    cols_jittered: Union[str, Sequence[str]] = None,
    amps: Union[float, Sequence[float]] = 0.5,
    jitter_type: str = "uniform",
) -> Union[pd.DataFrame, dask.dataframe.DataFrame]:
    """Add jittering to one or more dataframe columns.

    Args:
        df (Union[pd.DataFrame, dask.dataframe.DataFrame]): Dataframe to add
            noise/jittering to.
        cols (Union[str, Sequence[str]]): Names of the columns to add jittering to.
        cols_jittered (Union[str, Sequence[str]], optional): Names of the columns
            with added jitter. Defaults to None.
        amps (Union[float, Sequence[float]], optional): Amplitude scalings for the
            jittering noise. If one number is given, the same is used for all axes.
            Defaults to 0.5.
        jitter_type (str, optional): the type of jitter to add. 'uniform' or 'normal'
            distributed noise. Defaults to "uniform".

    Returns:
        Union[pd.DataFrame, dask.dataframe.DataFrame]: dataframe with added columns.
    """
    assert cols is not None, "cols needs to be provided!"
    assert jitter_type in (
        "uniform",
        "normal",
    ), "type needs to be one of 'normal', 'uniform'!"

    if isinstance(cols, str):
        cols = [cols]
    if isinstance(cols_jittered, str):
        cols_jittered = [cols_jittered]
    if cols_jittered is None:
        cols_jittered = [col + "_jittered" for col in cols]
    if isinstance(amps, float):
        amps = list(np.ones(len(cols)) * amps)

    colsize = df[cols[0]].size

    if jitter_type == "uniform":
        # Uniform Jitter distribution
        jitter = np.random.uniform(low=-1, high=1, size=colsize)
    elif jitter_type == "normal":
        # Normal Jitter distribution works better for non-linear transformations and
        # jitter sizes that don't match the original bin sizes
        jitter = np.random.standard_normal(size=colsize)

    for (col, col_jittered, amp) in zip(cols, cols_jittered, amps):
        df[col_jittered] = df[col] + amp * jitter

    return df


def drop_column(
    df: Union[pd.DataFrame, dask.dataframe.DataFrame],
    column_name: Union[str, Sequence[str]],
) -> Union[pd.DataFrame, dask.dataframe.DataFrame]:
    """Delete columns.

    Args:
        df (Union[pd.DataFrame, dask.dataframe.DataFrame]): Dataframe to use.
        column_name (Union[str, Sequence[str]])): List of column names to be dropped.

    Returns:
        Union[pd.DataFrame, dask.dataframe.DataFrame]: Dataframe with dropped columns.
    """
    out_df = df.drop(column_name, axis=1)

    return out_df


def apply_filter(
    df: Union[pd.DataFrame, dask.dataframe.DataFrame],
    col: str,
    lower_bound: float = -np.inf,
    upper_bound: float = np.inf,
) -> Union[pd.DataFrame, dask.dataframe.DataFrame]:
    """Application of bound filters to a specified column (can be used consecutively).

    Args:
        df (Union[pd.DataFrame, dask.dataframe.DataFrame]): Dataframe to use.
        col (str): Name of the column to filter.
        lower_bound (float, optional): The lower bound used in the filtering.
            Defaults to -np.inf.
        upper_bound (float, optional): The lower bound used in the filtering.
            Defaults to np.inf.

    Returns:
        Union[pd.DataFrame, dask.dataframe.DataFrame]: The filtered dataframe.
    """
    out_df = df[(df[col] > lower_bound) & (df[col] < upper_bound)]

    return out_df


def map_columns_2d(
    df: Union[pd.DataFrame, dask.dataframe.DataFrame],
    map_2d: Callable,
    x_column: np.ndarray,
    y_column: np.ndarray,
    **kwds,
) -> Union[pd.DataFrame, dask.dataframe.DataFrame]:
    """Apply a 2-dimensional mapping simultaneously to two dimensions.

    Args:
        df (Union[pd.DataFrame, dask.dataframe.DataFrame]): Dataframe to use.
        map_2d (Callable): 2D mapping function.
        x_column (np.ndarray): The X column of the dataframe to apply mapping to.
        y_column (np.ndarray): The Y column of the dataframe to apply mapping to.
        **kwds: Additional arguments for the 2D mapping function.

    Returns:
        Union[pd.DataFrame, dask.dataframe.DataFrame]: Dataframe with mapped columns.
    """
    new_x_column = kwds.pop("new_x_column", x_column)
    new_y_column = kwds.pop("new_y_column", y_column)

    (df[new_x_column], df[new_y_column]) = map_2d(
        df[x_column],
        df[y_column],
        **kwds,
    )

    return df


def forward_fill_lazy(
    df: dask.dataframe.DataFrame,
    columns: Sequence[str] = None,
    before: Union[str, int] = "max",
    compute_lengths: bool = False,
    iterations: int = 2,
) -> dask.dataframe.DataFrame:
    """Forward fill the specified columns multiple times in a dask dataframe.

    Allows forward filling between partitions. This is useful for dataframes
    that have sparse data, such as those with many NaNs.
    Runnin the forward filling multiple times can fix the issue of having
    entire partitions consisting of NaNs. By default we run this twice, which
    is enough to fix the issue for dataframes with no consecutive partitions of NaNs.

    Args:
        df (dask.dataframe.DataFrame): The dataframe to forward fill.
        columns (list): The columns to forward fill. If None, fills all columns
        before (int, str, optional): The number of rows to include before the current partition.
            if 'max' it takes as much as possible from the previous partition, which is
            the size of the smallest partition in the dataframe. Defaults to 'max'.
        compute_lengths (bool, optional): Whether to compute the length of each partition
        iterations (int, optional): The number of times to forward fill the dataframe.

    Returns:
        dask.dataframe.DataFrame: The dataframe with the specified columns forward filled.
    """
    if columns is None:
        columns = df.columns
    elif isinstance(columns, str):
        columns = [columns]
    elif len(columns) == 0:
        raise ValueError("columns must be a non-empty list of strings!")
    for c in columns:
        if c not in df.columns:
            raise KeyError(f"{c} not in dataframe!")

    # Define a custom function to forward fill specified columns
    def forward_fill_partition(df):
        df[columns] = df[columns].ffill()
        return df

    # calculate the number of rows in each partition and choose least
    if before == "max":
        nrows = df.map_partitions(len)
        if compute_lengths:
            with ProgressBar():
                print("Computing dataframe shape...")
                nrows = nrows.compute()
        before = min(nrows)
    elif not isinstance(before, int):
        raise TypeError('before must be an integer or "max"')
    # Use map_overlap to apply forward_fill_partition
    for _ in range(iterations):
        df = df.map_overlap(
            forward_fill_partition,
            before=before,
            after=0,
        )
    return df


def backward_fill_lazy(
    df: dask.dataframe.DataFrame,
    columns: Sequence[str] = None,
    after: Union[str, int] = "max",
    compute_lengths: bool = False,
    iterations: int = 1,
) -> dask.dataframe.DataFrame:
    """Forward fill the specified columns multiple times in a dask dataframe.

    Allows backward filling between partitions. Similar to forward fill, but backwards.
    This helps to fill the initial values of a dataframe, which are often NaNs.
    Use with care as the assumption of the values being the same in the past is often not true.

    Args:
        df (dask.dataframe.DataFrame): The dataframe to forward fill.
        columns (list): The columns to forward fill. If None, fills all columns
        after (int, str, optional): The number of rows to include after the current partition.
            if 'max' it takes as much as possible from the previous partition, which is
            the size of the smallest partition in the dataframe. Defaults to 'max'.
        compute_lengths (bool, optional): Whether to compute the length of each partition
        iterations (int, optional): The number of times to backward fill the dataframe.

    Returns:
        dask.dataframe.DataFrame: The dataframe with the specified columns backward filled.
    """
    if columns is None:
        columns = df.columns
    elif isinstance(columns, str):
        columns = [columns]
    elif len(columns) == 0:
        raise ValueError("columns must be a non-empty list of strings!")
    for c in columns:
        if c not in df.columns:
            raise KeyError(f"{c} not in dataframe!")

    # Define a custom function to forward fill specified columns
    def backward_fill_partition(df):
        df[columns] = df[columns].bfill()
        return df

    # calculate the number of rows in each partition and choose least
    if after == "max":
        nrows = df.map_partitions(len)
        if compute_lengths:
            with ProgressBar():
                print("Computing dataframe shape...")
                nrows = nrows.compute()
        after = min(nrows)
    elif not isinstance(after, int):
        raise TypeError('before must be an integer or "max"')
    # Use map_overlap to apply forward_fill_partition
    for _ in range(iterations):
        df = df.map_overlap(
            backward_fill_partition,
            before=0,
            after=after,
        )
    return df


def rolling_average_on_acquisition_time(
    df: Union[pd.DataFrame, dask.dataframe.DataFrame],
    rolling_group_channel: str = None,
    columns: Union[str, Sequence[str]] = None,
    window: float = None,
    sigma: float = 2,
    config: dict = None,
) -> Union[pd.DataFrame, dask.dataframe.DataFrame]:
    """Perform a rolling average with a gaussian weighted window.

    The rolling average is performed on the acquisition time instead of the index.
    This can be a time-stamp or similar, such as the trainID at FLASH.
    This is necessary first when considering the recorded electrons do not come at a regular time
    interval, but even more importantly when loading multiple datasets with gaps in the acquisition.


    In order to preserve the number of points, the first and last "window"
    number of points are substituted with the original signal.
    # TODO: this is currently very slow, and could do with a remake.

    Args:
        df (Union[pd.DataFrame, dask.dataframe.DataFrame]): Dataframe to use.
        group_channel: (str): Name of the column on which to group the data
        cols (str): Name of the column on which to perform the rolling average
        window (float): Size of the rolling average window
        sigma (float): number of standard deviations for the gaussian weighting of the window.
            a value of 2 corresponds to a gaussian with sigma equal to half the window size.
            Smaller values reduce the weighting in the window frame.

    Returns:
        Union[pd.DataFrame, dask.dataframe.DataFrame]: Dataframe with the new columns.
    """
    if rolling_group_channel is None:
        if config is None:
            raise ValueError("Either group_channel or config must be given.")
        rolling_group_channel = config["dataframe"]["rolling_group_channel"]
    if isinstance(columns, str):
        columns = [columns]
    s = f"rolling average over {rolling_group_channel} on "
    for c in columns:
        s += f"{c}, "
    print(s)
    with ProgressBar():
        df_ = df.groupby(rolling_group_channel).agg({c: "mean" for c in columns}).compute()
        df_["dt"] = pd.to_datetime(df_.index, unit="s")
        df_["ts"] = df_.index
        for c in columns:
            df_[c + "_rolled"] = (
                df_[c]
                .interpolate(method="nearest")
                .rolling(window, center=True, win_type="gaussian")
                .mean(std=window / sigma)
                .fillna(df_[c])
            )
            df_ = df_.drop(c, axis=1)
            if c + "_rolled" in df.columns:
                df = df.drop(c + "_rolled", axis=1)
    return df.merge(df_, left_on="timeStamp", right_on="ts").drop(["ts", "dt"], axis=1)


def apply_offset_from_columns(
    df: Union[pd.DataFrame, dask.dataframe.DataFrame],
    target_column: str,
    offset_columns: Union[str, Sequence[str]],
    signs: Union[int, Sequence[int]],
    reductions: Union[str, Sequence[str]],
    inplace: bool = True,
) -> Union[pd.DataFrame, dask.dataframe.DataFrame]:
    """Apply an offset to a column based on the values of other columns.

    Args:
        df (Union[pd.DataFrame, dask.dataframe.DataFrame]): Dataframe to use.
        target_column (str): Name of the column to apply the offset to.
        offset_columns (str): Name of the column(s) to use for the offset.
        signs (int): Sign of the offset. Defaults to 1.
        reductions (str): Reduction function to use for the offset. Defaults to "mean".

    Returns:
        Union[pd.DataFrame, dask.dataframe.DataFrame]: Dataframe with the new column.
    """
    if isinstance(offset_columns, str):
        offset_columns = [offset_columns]
    if not inplace:
        df[target_column + "_offset"] = df[target_column]
        target_column = target_column + "_offset"
    if reductions is None:
        reductions = "mean"
    if isinstance(reductions, str):
        reductions = [reductions] * len(offset_columns)
    if isinstance(signs, int):
        signs = [signs]
    if len(signs) != len(offset_columns):
        raise ValueError("signs and offset_columns must have the same length!")

    for col, sign, red in zip(offset_columns, signs, reductions):
        assert col in df.columns, f"{col} not in dataframe!"
        if red is not None:
            df[target_column] = df[target_column] + sign * df[col].agg(red)
        else:
            df[target_column] = df[target_column] + sign * df[col]
    return df

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
            For normal noise, the added noise will have sdev [-amp, +amp], for
            uniform noise it will cover the interval [-amp, +amp].
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

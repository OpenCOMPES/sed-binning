"""Tests for SXPDataFrameCreator functionality"""
import numpy as np
import pytest
from pandas import DataFrame
from pandas import Index

from sed.loader.fel.utils import get_channels
from sed.loader.sxp.dataframe import SXPDataFrameCreator


def test_get_dataset_array(config_dataframe, h5_file):
    """Test the creation of a h5py dataset for a given channel."""

    df = SXPDataFrameCreator(config_dataframe, h5_file)
    channel = "dldPosX"
    max_hits = df._config.channels.get(channel).max_hits

    train_id, dset = df.get_dataset_array(channel)
    # Check that the train_id and np_array have the correct shapes and types
    assert isinstance(train_id, Index)
    assert isinstance(dset, np.ndarray)
    assert train_id.name == "trainId"
    assert train_id.shape[0] == dset.shape[0]
    assert dset.shape[1] == max_hits

    channel = "delayStage"
    train_id, dset = df.get_dataset_array(channel)
    assert train_id.shape[0] == dset.shape[0]


def test_empty_get_dataset_array(config_dataframe, h5_file, h5_file_copy):
    """Test the method when given an empty dataset."""

    channel = "delayStage"
    df = SXPDataFrameCreator(config_dataframe, h5_file)
    train_id, dset = df.get_dataset_array(channel)

    channel_index_key = "/INDEX/trainId"
    empty_dataset_key = "/CONTROL/SCS_ILH_LAS/MDL/OPTICALDELAY_PP800/actualPosition/empty"
    config_dataframe.channels.get(channel).index_key = channel_index_key
    config_dataframe.channels.get(channel).dataset_key = empty_dataset_key
    # Remove the 'group_name' key
    del config_dataframe.channels.get(channel).group_name

    # create an empty dataset
    h5_file_copy.create_dataset(
        name=empty_dataset_key,
        shape=(train_id.shape[0], 0),
    )

    df = SXPDataFrameCreator(config_dataframe, h5_file)
    df.h5_file = h5_file_copy
    train_id, dset_empty = df.get_dataset_array(channel)

    assert dset_empty.shape[0] == train_id.shape[0]


# def test_pulse_index(config_dataframe, h5_file):
#     """Test the creation of the pulse index for electron resolved data"""

#     df = SXPDataFrameCreator(config_dataframe, h5_file)
#     pulse_index, pulse_array = df.get_dataset_array("pulseId", slice_=True)
#     index, indexer = df.pulse_index(config_dataframe.ubid_offset)
#     # Check if the index_per_electron is a MultiIndex and has the correct levels
#     assert isinstance(index, MultiIndex)
#     assert set(index.names) == {"trainId", "pulseId", "electronId"}

#     # Check if the pulse_index has the correct number of elements
#     # This should be the pulses without nan values
#     pulse_rav = pulse_array.ravel()
#     pulse_no_nan = pulse_rav[~np.isnan(pulse_rav)]
#     assert len(index) == len(pulse_no_nan)

#     # Check if all pulseIds are correctly mapped to the index
#     assert np.all(
#         index.get_level_values("pulseId").values
#         == (pulse_no_nan - config_dataframe.ubid_offset)[indexer],
#     )

#     assert np.all(
#         index.get_level_values("electronId").values[:5] == [0, 1, 0, 1, 0],
#     )

#     assert np.all(
#         index.get_level_values("electronId").values[-5:] == [1, 0, 1, 0, 1],
#     )

#     # check if all indexes are unique and monotonic increasing
#     assert index.is_unique
#     assert index.is_monotonic_increasing


# def test_df_electron(config_dataframe, h5_file):
#     """Test the creation of a pandas DataFrame for a channel of type [per electron]."""
#     df = SXPDataFrameCreator(config_dataframe, h5_file)

#     result_df = df.df_electron

#     # check index levels
#     assert set(result_df.index.names) == {"trainId", "pulseId", "electronId"}

#     # check that there are no nan values in the dataframe
#     assert ~result_df.isnull().values.any()

#     # Check that the values are dropped for pulseId index below 0 (ubid_offset)
#     print(
#         np.all(
#             result_df.values[:5]
#             != np.array(
#                 [
#                     [556.0, 731.0, 42888.0],
#                     [549.0, 737.0, 42881.0],
#                     [671.0, 577.0, 39181.0],
#                     [671.0, 579.0, 39196.0],
#                     [714.0, 859.0, 37530.0],
#                 ],
#             ),
#         ),
#     )
#     assert np.all(result_df.index.get_level_values("pulseId") >= 0)
#     assert isinstance(result_df, DataFrame)

#     assert result_df.index.is_unique

#     # check that dataframe contains all subchannels
#     assert np.all(
#         set(result_df.columns) == set(get_channels(config_dataframe.channels, ["per_electron"])),
#     )


def test_create_dataframe_per_train(config_dataframe, h5_file):
    """Test the creation of a pandas DataFrame for a channel of type [per train]."""
    df = SXPDataFrameCreator(config_dataframe, h5_file)
    result_df = df.df_train

    channel = "delayStage"
    _, data = df.get_dataset_array(channel)

    # Check that the result_df is a DataFrame and has the correct shape
    assert isinstance(result_df, DataFrame)

    # check that all values are in the df for delayStage
    np.all(result_df[channel].dropna() == data[()])

    # check that dataframe contains all channels
    assert np.all(
        set(result_df.columns)
        == set(get_channels(config_dataframe.channels, ["per_train"], extend_aux=True)),
    )

    # find unique index values among all per_train channels
    channels = get_channels(config_dataframe.channels, ["per_train"])
    all_keys = Index([])
    for channel in channels:
        all_keys = all_keys.append(df.get_dataset_array(channel)[0])
    assert result_df.shape[0] == len(all_keys.unique())

    # check index levels
    assert set(result_df.index.names) == {"trainId", "pulseId", "electronId"}

    # all pulseIds and electronIds should be 0
    assert np.all(result_df.index.get_level_values("pulseId") == 0)
    assert np.all(result_df.index.get_level_values("electronId") == 0)


def test_group_name_not_in_h5(config_dataframe, h5_file):
    """Test ValueError when the group_name for a channel does not exist in the H5 file."""
    channel = "delayStage"
    config = config_dataframe
    config.channels.get(channel).index_key = "foo"
    df = SXPDataFrameCreator(config, h5_file)
    with pytest.raises(KeyError):
        df.df_train

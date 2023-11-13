"""Module tests.calibrator.delay, tests for the sed.calibrator.delay file
"""
import os
from importlib.util import find_spec

import dask.dataframe
import numpy as np
import pandas as pd
import pytest

from sed.calibrator.delay import DelayCalibrator
from sed.core.config import parse_config
from sed.loader.loader_interface import get_loader

package_dir = os.path.dirname(find_spec("sed").origin)
file = package_dir + "/../tests/data/loader/mpes/Scan0030_2.h5"


def test_delay_parameters_from_file():
    """Test the option to extract the delay parameters from a file"""
    config = parse_config(
        config={
            "core": {"loader": "mpes"},
            "delay": {
                "p1_key": "@trARPES:DelayStage:p1",
                "p2_key": "@trARPES:DelayStage:p2",
                "t0_key": "@trARPES:DelayStage:t0",
            },
        },
        folder_config={},
        user_config={},
        system_config={},
    )
    df, _, _ = get_loader(loader_name="mpes", config=config).read_dataframe(
        files=[file],
        collect_metadata=False,
    )
    dc = DelayCalibrator(config=config)
    df, metadata = dc.append_delay_axis(df, datafile=file)
    assert "delay" in df.columns
    assert "datafile" in metadata["calibration"]
    assert "delay_range" in metadata["calibration"]
    assert "adc_range" in metadata["calibration"]
    assert "time0" in metadata["calibration"]
    assert "delay_range_mm" in metadata["calibration"]


def test_delay_parameters_from_delay_range():
    """Test the option to extract the delay parameters from a delay range"""
    # from keywords
    config = parse_config(
        config={"core": {"loader": "mpes"}},
        folder_config={},
        user_config={},
        system_config={},
    )
    df, _, _ = get_loader(loader_name="mpes", config=config).read_dataframe(
        files=[file],
        collect_metadata=False,
    )
    dc = DelayCalibrator(config=config)
    df, metadata = dc.append_delay_axis(df, delay_range=(-100, 200))
    assert "delay" in df.columns
    assert "delay_range" in metadata["calibration"]
    assert "adc_range" in metadata["calibration"]

    # from calibration
    df, _, _ = get_loader(loader_name="mpes", config=config).read_dataframe(
        files=[file],
        collect_metadata=False,
    )
    dc = DelayCalibrator(config=config)
    calibration = {"delay_range": (-100, 200), "adc_range": (100, 1000)}
    df, metadata = dc.append_delay_axis(df, calibration=calibration)
    assert "delay" in df.columns
    assert "delay_range" in metadata["calibration"]
    assert "adc_range" in metadata["calibration"]
    assert metadata["calibration"]["adc_range"] == (100, 1000)


def test_delay_parameters_from_delay_range_mm():
    """Test the option to extract the delay parameters from a mm range + t0"""
    # from keywords
    config = parse_config(
        config={"core": {"loader": "mpes"}},
        folder_config={},
        user_config={},
        system_config={},
    )
    df, _, _ = get_loader(loader_name="mpes", config=config).read_dataframe(
        files=[file],
        collect_metadata=False,
    )
    dc = DelayCalibrator(config=config)
    with pytest.raises(NotImplementedError):
        dc.append_delay_axis(df, delay_range_mm=(1, 15))
    df, metadata = dc.append_delay_axis(df, delay_range_mm=(1, 15), time0=1)
    assert "delay" in df.columns
    assert "delay_range" in metadata["calibration"]
    assert "adc_range" in metadata["calibration"]
    assert "time0" in metadata["calibration"]
    assert "delay_range_mm" in metadata["calibration"]

    # from dict
    df, _, _ = get_loader(loader_name="mpes", config=config).read_dataframe(
        files=[file],
        collect_metadata=False,
    )
    dc = DelayCalibrator(config=config)
    calibration = {"delay_range_mm": (1, 15)}
    with pytest.raises(NotImplementedError):
        dc.append_delay_axis(df, calibration=calibration)
    calibration["time0"] = 1
    df, metadata = dc.append_delay_axis(df, calibration=calibration)
    assert "delay" in df.columns
    assert "delay_range" in metadata["calibration"]
    assert "adc_range" in metadata["calibration"]
    assert "time0" in metadata["calibration"]
    assert "delay_range_mm" in metadata["calibration"]


bam_vals = 1000 * (np.random.normal(size=100) + 5)
delay_stage_vals = np.linspace(0, 99, 100)
cfg = {
    "core": {"loader": "flash"},
    "dataframe": {"delay_column": "delay"},
    "delay": {
        "offsets": {
            "constant": 1,
            "bam": {
                "weight": 0.001,
                "preserve_mean": False,
            },
            "flip_time_axis": True,
        },
    },
}
df = dask.dataframe.from_pandas(
    pd.DataFrame(
        {
            "bam": bam_vals.copy(),
            "delay": delay_stage_vals.copy(),
        },
    ),
    npartitions=2,
)


def test_add_offset_from_config(df=df) -> None:
    """test that the timing offset is corrected for correctly from config"""
    config = parse_config(
        config=cfg,
        folder_config={},
        user_config={},
        system_config={},
    )

    expected = (
        delay_stage_vals
        + bam_vals * cfg["delay"]["offsets"]["bam"]["weight"]
        + cfg["delay"]["offsets"]["constant"]
    )

    dc = DelayCalibrator(config=config)
    df, _ = dc.add_offsets(df.copy())
    assert "delay" in df.columns
    assert "bam" in dc.offsets.keys()
    np.testing.assert_allclose(expected, df["delay"])


def test_add_offset_from_args(df=df) -> None:
    """test that the timing offset applied with arguments works"""
    cfg_ = cfg.copy()
    cfg_.pop("delay")
    config = parse_config(
        config=cfg,
        folder_config={},
        user_config={},
        system_config={},
    )
    dc = DelayCalibrator(config=config)
    df, _ = dc.add_offsets(df.copy(), columns="bam", weights=0.001, constant=1)
    assert "delay" in df.columns
    assert "bam" in dc.offsets.keys()
    expected = (
        delay_stage_vals
        + bam_vals * cfg["delay"]["offsets"]["bam"]["weight"]
        + cfg["delay"]["offsets"]["constant"]
    )
    np.testing.assert_allclose(expected, df["delay"])


def test_flip_delay_axis(df=df) -> None:
    """test that the timing offset applied with arguments works"""
    cfg_ = cfg.copy()
    cfg_.pop("delay")
    cfg_["delay"] = {"flip_delay_axis": True}
    config = parse_config(
        config=cfg,
        folder_config={},
        user_config={},
        system_config={},
    )
    dc = DelayCalibrator(config=config)
    df, _ = dc.flip_delay_axis(df.copy())
    assert "delay" in df.columns
    np.testing.assert_allclose(df["delay"], -delay_stage_vals)

"""Pydantic model to validate the config for SED package."""
from collections.abc import Sequence
from typing import Literal
from typing import Optional
from typing import Union

from pydantic import BaseModel
from pydantic import DirectoryPath
from pydantic import Field
from pydantic import field_validator
from pydantic import FilePath
from pydantic import HttpUrl
from pydantic import NewPath
from pydantic import SecretStr

from sed.loader.loader_interface import get_names_of_all_loaders

## Best to not use futures annotations with pydantic models
## https://github.com/astral-sh/ruff/issues/5434


class Paths(BaseModel):
    raw: DirectoryPath
    processed: Union[DirectoryPath, NewPath]


class CoreModel(BaseModel):
    loader: str = "generic"
    paths: Optional[Paths] = None
    num_cores: int = 4
    year: Optional[int] = None
    beamtime_id: Optional[int] = None
    instrument: Optional[str] = None

    @field_validator("loader")
    @classmethod
    def validate_loader(cls, v: str) -> str:
        """Checks if the loader is one of the valid ones"""
        names = get_names_of_all_loaders()
        if v not in names:
            raise ValueError(f"Invalid loader {v}. Available loaders are: {names}")
        return v


class ColumnsModel(BaseModel):
    x: str
    y: str
    tof: str
    tof_ns: str
    corrected_x: str
    corrected_y: str
    corrected_tof: str
    kx: str
    ky: str
    energy: str
    delay: str
    adc: str
    bias: str
    timestamp: str


class ChannelModel(BaseModel):
    format: Literal["per_train", "per_electron", "per_pulse", "per_file"]
    dataset_key: str
    index_key: Optional[str] = None
    slice: Optional[int] = None
    dtype: Optional[str] = None

    class subChannelModel(BaseModel):
        slice: int
        dtype: Optional[str] = None

    sub_channels: Optional[dict[str, subChannelModel]] = None


class Dataframe(BaseModel):
    columns: ColumnsModel = ColumnsModel()
    units: Optional[dict[str, str]] = None
    channels: dict[str, ChannelModel] = Field(default_factory=dict)
    # other settings
    tof_binwidth: float
    tof_binning: int
    adc_binning: int
    jitter_cols: Sequence[str]
    jitter_amps: Union[float, Sequence[float]]
    timed_dataframe_unit_time: float
    # flash specific settings
    forward_fill_iterations: Optional[int] = None
    ubid_offset: Optional[int] = None
    split_sector_id_from_dld_time: Optional[bool] = None
    sector_id_reserved_bits: Optional[int] = None
    sector_delays: Optional[Sequence[int]] = None


class BinningModel(BaseModel):
    hist_mode: str
    mode: str
    pbar: bool
    threads_per_worker: int
    threadpool_API: str


class HistogramModel(BaseModel):
    bins: Sequence[int]
    axes: Sequence[str]
    ranges: Sequence[Sequence[int]]


class StaticModel(BaseModel):
    """Static configuration settings that shouldn't be changed by users."""

    # flash specific settings
    stream_name_prefixes: Optional[dict] = None
    stream_name_postfixes: Optional[dict] = None
    beamtime_dir: Optional[dict] = None


class EnergyCalibrationModel(BaseModel):
    d: float
    t0: float
    E0: float
    energy_scale: str


class EnergyCorrectionModel(BaseModel):
    correction_type: str
    amplitude: float
    center: Sequence[float]
    gamma: float
    sigma: float
    diameter: float


class EnergyModel(BaseModel):
    bins: int
    ranges: Sequence[int]
    normalize: bool
    normalize_span: int
    normalize_order: int
    fastdtw_radius: int
    peak_window: int
    calibration_method: str
    energy_scale: str
    tof_fermi: int
    tof_width: Sequence[int]
    x_width: Sequence[int]
    y_width: Sequence[int]
    color_clip: int
    calibration: Optional[EnergyCalibrationModel] = None
    correction: Optional[EnergyCorrectionModel] = None


class MomentumCalibrationModel(BaseModel):
    kx_scale: float
    ky_scale: float
    x_center: float
    y_center: float
    rstart: float
    cstart: float
    rstep: float
    cstep: float


class MomentumCorrectionModel(BaseModel):
    feature_points: Sequence[Sequence[float]]
    rotation_symmetry: int
    include_center: bool
    use_center: bool


class MomentumModel(BaseModel):
    axes: Sequence[str]
    bins: Sequence[int]
    ranges: Sequence[Sequence[int]]
    detector_ranges: Sequence[Sequence[int]]
    center_pixel: Sequence[int]
    sigma: int
    fwhm: int
    sigma_radius: int
    calibration: Optional[MomentumCalibrationModel] = None
    correction: Optional[MomentumCorrectionModel] = None


class DelayModel(BaseModel):
    adc_range: Sequence[int]
    time0: int
    flip_time_axis: bool = False
    p1_key: Optional[str] = None
    p2_key: Optional[str] = None
    p3_key: Optional[str] = None


class MetadataModel(BaseModel):
    archiver_url: Optional[HttpUrl] = None
    token: Optional[SecretStr] = None
    epics_pvs: Optional[Sequence[str]] = None
    fa_in_channel: Optional[str] = None
    fa_hor_channel: Optional[str] = None
    ca_in_channel: Optional[str] = None
    aperture_config: Optional[dict] = None
    lens_mode_config: Optional[dict] = None


class NexusModel(BaseModel):
    reader: str  # prob good to have validation here
    # Currently only NXmpes definition is supported
    definition: Literal["NXmpes"]
    input_files: Sequence[FilePath]


class ConfigModel(BaseModel):
    core: CoreModel
    dataframe: Dataframe
    energy: EnergyModel
    momentum: MomentumModel
    delay: DelayModel
    binning: BinningModel
    histogram: HistogramModel
    metadata: Optional[MetadataModel] = None
    nexus: Optional[NexusModel] = None
    static: Optional[StaticModel] = None

import itertools as it
import warnings as wn
from functools import partial
from typing import Sequence
from typing import Tuple
from typing import Union

import bokeh.plotting as pbk
import dask.dataframe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from bokeh.io import output_notebook
from bokeh.palettes import Category10 as ColorCycle
from fastdtw import fastdtw
from funcy import project
from lmfit import Minimizer
from lmfit import Parameters
from lmfit.printfuncs import report_fit
from numpy.linalg import lstsq
from scipy.signal import savgol_filter
from scipy.sparse.linalg import lsqr
from scipy.spatial import distance


class EnergyCalibrator:
    """
    Electron binding energy calibration workflow.
    """

    def __init__(
        self,
        biases: Sequence[float],
        traces: Sequence[float],
        tof: Sequence[float],
        config: dict = {},
    ):
        """Initialization of the EnergyCalibrator class can follow different ways,

        1. Initialize with all the file paths in a list
        1a. Use an hdf5 file containing all binned traces and tof
        1b. Use a mat file containing all binned traces and tof
        1c. Use the raw data hdf5 files
        2. Initialize with the folder path containing any of the above files
        3. Initialize with the binned traces and the time-of-flight
        """

        self.biases = biases
        self.tof = tof
        self.featranges = []  # Value ranges for feature detection

        self._config = config
        self.peaks = []
        self.calibration = []

        if traces is not None:
            self.traces = traces
            self.traces_normed = traces
        else:
            self.traces = []
            self.traces_normed = []

    @property
    def ntraces(self) -> int:
        """The number of loaded/calculated traces."""

        return len(self.traces)

    @property
    def nranges(self) -> int:
        """The number of specified feature ranges."""

        return len(self.featranges)

    @property
    def dup(self) -> int:
        """The duplication number."""

        return int(np.round(self.nranges / self.ntraces))

    def normalize(self, **kwds: dict):
        """Normalize the spectra along an axis.

        **Parameters**\n
        **kwds: keyword arguments
            See the keywords for ``mpes.utils.normspec()``.
        """

        self.traces_normed = normspec(self.traces, **kwds)

    def add_features(
        self,
        ranges: Sequence[Tuple[float, float]],
        refid: int = 0,
        traces: Sequence[float] = None,
        infer_others: bool = True,
        mode: str = "replace",
        **kwds,
    ):
        """Select or extract the equivalent landmarks (e.g. peaks) among all traces.

        **Parameters**\n
        ranges: list/tuple
            Collection of feature detection ranges, within which an algorithm
            (i.e. 1D peak detector) with look for the feature.
        refid: int | 0
            Index of the reference trace (EDC).
        traces: 2D array | None
            Collection of energy dispersion curves (EDCs).
        infer_others: bool | True
            Option to infer the feature detection range in other traces (EDCs) from a
            given one.
        mode: str | 'append'
            Specification on how to change the feature ranges ('append' or 'replace').
        **kwds: keyword arguments
            Dictionarized keyword arguments for trace alignment
            (See ``self.findCorrespondence()``)
        """

        if traces is None:
            traces = self.traces_normed

        # Infer the corresponding feature detection range of other traces by alignment
        if infer_others:
            newranges = []

            for i in range(self.ntraces):

                pathcorr = find_correspondence(
                    traces[refid, :],
                    traces[i, :],
                    **kwds,
                )
                newranges.append(range_convert(self.tof, ranges, pathcorr))

        else:
            if isinstance(ranges, list):
                newranges = ranges
            else:
                newranges = [ranges]

        if mode == "append":
            self.featranges += newranges
        elif mode == "replace":
            self.featranges = newranges

    def feature_extract(
        self,
        ranges: Sequence[Tuple[float, float]] = None,
        traces: Sequence[float] = None,
        **kwds,
    ):
        """Select or extract the equivalent landmarks (e.g. peaks) among all traces.

        **Parameters**\n
        ranges: list/tuple | None
            Range in each trace to look for the peak feature, [start, end].
        traces: 2D array | None
            Collection of 1D spectra to use for calibration.
        **kwds: keyword arguments
            See available keywords in ``mpes.analysis.peaksearch()``.
        """

        if ranges is None:
            ranges = self.featranges

        if traces is None:
            traces = self.traces_normed

        # Augment the content of the calibration data
        traces_aug = np.tile(traces, (self.dup, 1))
        # Run peak detection for each trace within the specified ranges
        self.peaks = peaksearch(traces_aug, self.tof, ranges=ranges, **kwds)

    def calibrate(
        self,
        refid: int = 0,
        ret: str = "coeffs",
        method: str = "lmfit",
        **kwds,
    ) -> dict:
        """Calculate the functional mapping between time-of-flight and the energy
        scale using optimization methods.

        **Parameters**\n
        refid: int | 0
            The reference trace index (an integer).
        ret: list | ['coeffs']
            Options for return values (see ``mpes.analysis.calibrateE()``).
        method: str | lmfit
            Method for determining the energy calibration. "lmfit" or "poly"
        **kwds: keyword arguments
            See available keywords for ``poly_energy_calibration()``.
        """

        landmarks = kwds.pop("landmarks", self.peaks[:, 0])
        biases = kwds.pop("biases", self.biases)
        if method == "lmfit":
            self.calibration = fit_energy_calibation(
                landmarks,
                biases,
                refid=refid,
                **kwds,
            )
        elif method in ("lstsq", "lsqr"):
            self.calibration = poly_energy_calibration(
                landmarks,
                biases,
                refid=refid,
                ret=ret,
                aug=self.dup,
                method=method,
                **kwds,
            )
        else:
            raise NotImplementedError()

    def view(
        self,
        traces: Sequence[float],
        segs: Sequence[float] = None,
        peaks: Sequence[float] = None,
        show_legend: bool = True,
        backend: str = "matplotlib",
        linekwds: dict = {},
        linesegkwds: dict = {},
        scatterkwds: dict = {},
        legkwds: dict = {},
        **kwds,
    ):
        """Display a plot showing line traces with annotation.

        **Parameters**\n
        traces: 2d array
            Matrix of traces to visualize.
        segs: list/tuple
            Segments to be highlighted in the visualization.
        peaks: 2d array
            Peak positions for labelling the traces.
        ret: bool
            Return specification.
        backend: str | 'matplotlib'
            Backend specification, choose between 'matplotlib' (static) or 'bokeh'
            (interactive).
        linekwds: dict | {}
            Keyword arguments for line plotting (see ``matplotlib.pyplot.plot()``).
        scatterkwds: dict | {}
            Keyword arguments for scatter plot (see ``matplotlib.pyplot.scatter()``).
        legkwds: dict | {}
            Keyword arguments for legend (see ``matplotlib.pyplot.legend()``).
        **kwds: keyword arguments
            ===============  ==========  ================================
            keyword          data type   meaning
            ===============  ==========  ================================
            labels           list        Labels for each curve
            xaxis            1d array    x (horizontal) axis values
            title            str         Title of the plot
            legend_location  str         Location of the plot legend
            ===============  ==========  ================================
        """

        lbs = kwds.pop("labels", [str(b) + " V" for b in self.biases])
        xaxis = kwds.pop("xaxis", self.tof)
        ttl = kwds.pop("title", "")

        if backend == "matplotlib":

            figsize = kwds.pop("figsize", (12, 4))
            fig, ax = plt.subplots(figsize=figsize)
            for itr, trace in enumerate(traces):
                ax.plot(
                    xaxis,
                    trace,
                    ls="--",
                    linewidth=1,
                    label=lbs[itr],
                    **linekwds,
                )

                # Emphasize selected EDC segments
                if segs is not None:
                    seg = segs[itr]
                    cond = (self.tof >= seg[0]) & (self.tof <= seg[1])
                    tofseg, traceseg = self.tof[cond], trace[cond]
                    ax.plot(
                        tofseg,
                        traceseg,
                        color="k",
                        linewidth=2,
                        **linesegkwds,
                    )
                # Emphasize extracted local maxima
                if peaks is not None:
                    ax.scatter(
                        peaks[itr, 0],
                        peaks[itr, 1],
                        s=30,
                        **scatterkwds,
                    )

            if show_legend:
                try:
                    ax.legend(fontsize=12, **legkwds)
                except Exception:
                    pass

            ax.set_title(ttl)

        elif backend == "bokeh":

            output_notebook(hide_banner=True)
            colors = it.cycle(ColorCycle[10])
            ttp = [("(x, y)", "($x, $y)")]

            figsize = kwds.pop("figsize", (800, 300))
            fig = pbk.figure(
                title=ttl,
                plot_width=figsize[0],
                plot_height=figsize[1],
                tooltips=ttp,
            )
            # Plotting the main traces
            for itr, color in zip(range(len(traces)), colors):
                trace = traces[itr, :]
                fig.line(
                    xaxis,
                    trace,
                    color=color,
                    line_dash="solid",
                    line_width=1,
                    line_alpha=1,
                    legend=lbs[itr],
                    **kwds,
                )

                # Emphasize selected EDC segments
                if segs is not None:
                    seg = segs[itr]
                    cond = (self.tof >= seg[0]) & (self.tof <= seg[1])
                    tofseg, traceseg = self.tof[cond], trace[cond]
                    fig.line(
                        tofseg,
                        traceseg,
                        color=color,
                        line_width=3,
                        **linekwds,
                    )

                # Plot detected peaks
                if peaks is not None:
                    fig.scatter(
                        peaks[itr, 0],
                        peaks[itr, 1],
                        fill_color=color,
                        fill_alpha=0.8,
                        line_color=None,
                        size=5,
                        **scatterkwds,
                    )

            if show_legend:
                fig.legend.location = kwds.pop("legend_location", "top_right")
                fig.legend.spacing = 0
                fig.legend.padding = 2

            pbk.show(fig)


def normspec(
    specs: Sequence[float],
    smooth: bool = False,
    span: int = 7,
    order: int = 1,
) -> np.ndarray:
    """
    Normalize a series of 1D signals.

    **Parameters**\n
    *specs: list/2D array
        Collection of 1D signals.
    smooth: bool | False
        Option to smooth the signals before normalization.
    span, order: int, int | 13, 1
        Smoothing parameters of the LOESS method (see ``scipy.signal.savgol_filter()``).

    **Return**\n
    normalized_specs: 2D array
        The matrix assembled from a list of maximum-normalized signals.
    """

    nspec = len(specs)
    specnorm = []

    for i in range(nspec):

        spec = specs[i]

        if smooth:
            spec = savgol_filter(spec, span, order)

        if type(spec) in (list, tuple):
            nsp = spec / max(spec)
        else:
            nsp = spec / spec.max()
        specnorm.append(nsp)

        # Align 1D spectrum
        normalized_specs = np.asarray(specnorm)

    return normalized_specs


def find_correspondence(
    sig_still: Sequence[float],
    sig_mov: Sequence[float],
    **kwds,
) -> np.ndarray:
    """Determine the correspondence between two 1D traces by alignment.

    **Parameters**\n
    sig_still, sig_mov: 1D array, 1D array
        Input 1D signals.
    **kwds: keyword arguments
        See available keywords for the following functions,
        (1) ``fastdtw.fastdtw()`` (when ``method=='dtw'``)
        (2) ``ptw.ptw.timeWarp()`` (when ``method=='ptw'``)

    **Return**\n
    pathcorr: list
        Pixel-wise path correspondences between two input 1D arrays
        (sig_still, sig_mov).
    """

    dist = kwds.pop("dist_metric", distance.euclidean)
    rad = kwds.pop("radius", 1)
    _, pathcorr = fastdtw(sig_still, sig_mov, dist=dist, radius=rad)
    return np.asarray(pathcorr)


def range_convert(
    x: Sequence[float],
    xrng: Sequence[float],
    pathcorr: Sequence[Tuple[float, float]],
) -> tuple:
    """Convert value range using a pairwise path correspondence (e.g. obtained
    from time warping techniques).

    **Parameters**\n
    x: 1D array
        Values of the x axis (e.g. time-of-flight values).
    xrng: list/tuple
        Boundary value range on the x axis.
    pathcorr: list/tuple
        Path correspondence between two 1D arrays in the following form,
        [(id_1_trace_1, id_1_trace_2), (id_2_trace_1, id_2_trace_2), ...]

    **Return**\n
    xrange_trans: tuple
        Transformed range according to the path correspondence.
    """

    pathcorr = np.asarray(pathcorr)
    xrange_trans = []

    for xval in xrng:  # Transform each value in the range
        xind = find_nearest(xval, x)
        xind_alt = find_nearest(xind, pathcorr[:, 0])
        xind_trans = pathcorr[xind_alt, 1]
        xrange_trans.append(x[xind_trans])

    return tuple(xrange_trans)


def find_nearest(val: float, narray: np.ndarray) -> int:
    """
    Find the value closest to a given one in a 1D array.

    **Parameters**\n
    val: float
        Value of interest.
    narray: 1D numeric array
        The array to look for the nearest value.

    **Return**\n
    ind: int
        Array index of the value nearest to the given one.
    """

    return np.argmin(np.abs(narray - val))


def peaksearch(
    traces: np.ndarray,
    tof: np.ndarray,
    ranges: Sequence[Tuple[float, float]] = None,
    pkwindow: int = 3,
    plot: bool = False,
):
    """
    Detect a list of peaks in the corresponding regions of multiple EDCs

    **Parameters**\n
    traces: 2D array
        Collection of EDCs.
    tof: 1D array
        Time-of-flight values.
    ranges: list of tuples/lists | None
        List of ranges for peak detection in the format
        [(LowerBound1, UpperBound1), (LowerBound2, UpperBound2), ....].
    pkwindow: int | 3
        Window width of a peak (amounts to lookahead in ``peakdetect1d``).
    plot: bool | False
        Specify whether to display a custom plot of the peak search results.

    **Returns**\n
    pkmaxs: 1D array
        Collection of peak positions.
    """

    pkmaxs = []
    if plot:
        plt.figure(figsize=(10, 4))

    for rg, trace in zip(ranges, traces.tolist()):

        cond = (tof >= rg[0]) & (tof <= rg[1])
        trace = np.array(trace).ravel()
        tofseg, trseg = tof[cond], trace[cond]
        maxs, _ = peakdetect1d(trseg, tofseg, lookahead=pkwindow)
        pkmaxs.append(maxs[0, :])

        if plot:
            plt.plot(tof, trace, "--k", linewidth=1)
            plt.plot(tofseg, trseg, linewidth=2)
            plt.scatter(maxs[0, 0], maxs[0, 1], s=30)

    pkmaxs = np.asarray(pkmaxs)
    return pkmaxs


# 1D peak detection algorithm adapted from Sixten Bergman
# https://gist.github.com/sixtenbe/1178136#file-peakdetect-py
def _datacheck_peakdetect(
    x_axis: Sequence[float],
    y_axis: Sequence[float],
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Input format checking
    """

    if x_axis is None:
        x_axis = range(len(y_axis))

    if len(y_axis) != len(x_axis):
        raise ValueError(
            "Input vectors y_axis and x_axis must have same length",
        )

    # Needs to be a numpy array
    y_axis = np.array(y_axis)
    x_axis = np.array(x_axis)

    return x_axis, y_axis


def peakdetect1d(
    y_axis: Sequence[float],
    x_axis: Sequence[float] = None,
    lookahead: int = 200,
    delta: int = 0,
) -> Tuple[Sequence[float], Sequence[float]]:
    """
    Function for detecting local maxima and minima in a signal.
    Discovers peaks by searching for values which are surrounded by lower
    or larger values for maxima and minima respectively

    Converted from/based on a MATLAB script at:
    http://billauer.co.il/peakdet.html

    **Parameters**\n
    y_axis: list
        A list containing the signal over which to find peaks
    x_axis: list | None
        A x-axis whose values correspond to the y_axis list and is used
        in the return to specify the position of the peaks. If omitted an
        index of the y_axis is used.
    lookahead: int | 200
        distance to look ahead from a peak candidate to determine if
        it is the actual peak
        '(samples / period) / f' where '4 >= f >= 1.25' might be a good value
    delta: numeric | 0
        this specifies a minimum difference between a peak and
        the following points, before a peak may be considered a peak. Useful
        to hinder the function from picking up false peaks towards to end of
        the signal. To work well delta should be set to delta >= RMSnoise * 5.

    **Returns**\n
    max_peaks: list
        positions of the positive peaks
    min_peaks: list
        positions of the negative peaks
    """

    max_peaks = []
    min_peaks = []
    dump = []  # Used to pop the first hit which almost always is false

    # Check input data
    x_axis, y_axis = _datacheck_peakdetect(x_axis, y_axis)
    # Store data length for later use
    length = len(y_axis)

    # Perform some checks
    if lookahead < 1:
        raise ValueError("Lookahead must be '1' or above in value")

    if not (np.isscalar(delta) and delta >= 0):
        raise ValueError("delta must be a positive number")

    # maxima and minima candidates are temporarily stored in
    # mx and mn respectively
    mn, mx = np.Inf, -np.Inf

    # Only detect peak if there is 'lookahead' amount of points after it
    for index, (x, y) in enumerate(
        zip(x_axis[:-lookahead], y_axis[:-lookahead]),
    ):

        if y > mx:
            mx = y
            mxpos = x

        if y < mn:
            mn = y
            mnpos = x

        # Find local maxima
        if y < mx - delta and mx != np.Inf:
            # Maxima peak candidate found
            # look ahead in signal to ensure that this is a peak and not jitter
            if y_axis[index : index + lookahead].max() < mx:

                max_peaks.append([mxpos, mx])
                dump.append(True)
                # Set algorithm to only find minima now
                mx = np.Inf
                mn = np.Inf

                if index + lookahead >= length:
                    # The end is within lookahead no more peaks can be found
                    break
                continue
            # else:
            #    mx = ahead
            #    mxpos = x_axis[np.where(y_axis[index:index+lookahead]==mx)]

        # Find local minima
        if y > mn + delta and mn != -np.Inf:
            # Minima peak candidate found
            # look ahead in signal to ensure that this is a peak and not jitter
            if y_axis[index : index + lookahead].min() > mn:

                min_peaks.append([mnpos, mn])
                dump.append(False)
                # Set algorithm to only find maxima now
                mn = -np.Inf
                mx = -np.Inf

                if index + lookahead >= length:
                    # The end is within lookahead no more peaks can be found
                    break
            # else:
            #    mn = ahead
            #    mnpos = x_axis[np.where(y_axis[index:index+lookahead]==mn)]

    # Remove the false hit on the first value of the y_axis
    try:
        if dump[0]:
            max_peaks.pop(0)
        else:
            min_peaks.pop(0)
        del dump

    except IndexError:  # When no peaks have been found
        pass

    max_peaks = np.asarray(max_peaks)
    min_peaks = np.asarray(min_peaks)

    return max_peaks, min_peaks


def fit_energy_calibation(
    pos: Sequence[float],
    vals: Sequence[float],
    refid: int = 0,
    Eref: float = None,
    t: Sequence[float] = None,
    **kwds,
) -> dict:
    """
    Energy calibration by nonlinear least squares fitting of spectral landmarks on
    a set of (energy dispersion curves (EDCs). This is done here by fitting to the
    function d/(t-t0)**2.

    **Parameters**\n
    pos: list/array
        Positions of the spectral landmarks (e.g. peaks) in the EDCs.
    vals: list/array
        Bias voltage value associated with each EDC.
    refid: int | 0
        Reference dataset index, varies from 0 to vals.size - 1.
    Eref: float | None
        Energy of the reference value.
    t: numeric array | None
        Drift time.

    **Returns**\n
    ecalibdict: dict
        A dictionary of fitting parameters including the following,
        :coeffs: Fitted function coefficents.
        :axis: Fitted energy axis.
    """
    binwidth = kwds.pop("binwidth", 4.125e-12)
    binning = kwds.pop("binning", 1)

    vals = np.array(vals)
    nvals = vals.size

    if refid >= nvals:
        wn.warn(
            "Reference index (refid) cannot be larger than the number of traces!\
                Reset to the largest allowed number.",
        )
        refid = nvals - 1

    def residual(pars, time, data, binwidth=binwidth, binning=binning):
        model = tof2ev(
            pars["d"],
            pars["t0"],
            pars["E0"],
            time,
            binwidth=binwidth,
            binning=binning,
        )
        if data is None:
            return model
        return model - data

    pars = Parameters()
    pars.add(name="d", value=kwds.pop("d_init", 1))
    pars.add(
        name="t0",
        value=kwds.pop("t0_init", 1e-6),
        max=(min(pos) - 1) * binwidth * 2**binning,
    )
    pars.add(name="E0", value=kwds.pop("E0_init", min(vals)))
    fit = Minimizer(residual, pars, fcn_args=(pos, vals))
    result = fit.leastsq()
    report_fit(result)

    # Construct the calibrating function
    pfunc = partial(
        tof2ev,
        result.params["d"].value,
        result.params["t0"].value,
        binwidth=binwidth,
        binning=binning,
    )

    # Return results according to specification
    ecalibdict = {}
    ecalibdict["d"] = result.params["d"].value
    ecalibdict["t0"] = result.params["t0"].value
    ecalibdict["E0"] = result.params["E0"].value

    if (Eref is not None) and (t is not None):
        E0 = -pfunc(-Eref, pos[refid])
        ecalibdict["axis"] = pfunc(E0, t)
        ecalibdict["E0"] = E0

    return ecalibdict


def poly_energy_calibration(
    pos: Sequence[float],
    vals: Sequence[float],
    order: int = 3,
    refid: int = 0,
    ret: str = "func",
    E0: float = None,
    Eref: float = None,
    t: Sequence[float] = None,
    aug: int = 1,
    method: str = "lstsq",
    **kwds,
) -> dict:
    """
    Energy calibration by nonlinear least squares fitting of spectral landmarks on
    a set of (energy dispersion curves (EDCs). This amounts to solving for the
    coefficient vector, a, in the system of equations T.a = b. Here T is the
    differential drift time matrix and b the differential bias vector, and
    assuming that the energy-drift-time relationship can be written in the form,
    E = sum_n (a_n * t**n) + E0

    **Parameters**\n
    pos: list/array
        Positions of the spectral landmarks (e.g. peaks) in the EDCs.
    vals: list/array
        Bias voltage value associated with each EDC.
    order: int | 3
        Polynomial order of the fitting function.
    refid: int | 0
        Reference dataset index, varies from 0 to vals.size - 1.
    ret: str | 'func'
        Return type, including 'func', 'coeffs', 'full', and 'axis' (see below).
    E0: float | None
        Constant energy offset.
    t: numeric array | None
        Drift time.
    aug: int | 1
        Fitting dimension augmentation (1=no change, 2=double, etc).

    **Returns**\n
    pfunc: partial function
        Calibrating function with determined polynomial coefficients
        (except the constant offset).
    ecalibdict: dict
        A dictionary of fitting parameters including the following,
        :coeffs: Fitted polynomial coefficients (the a's).
        :offset: Minimum time-of-flight corresponding to a peak.
        :Tmat: the T matrix (differential time-of-flight) in the equation Ta=b.
        :bvec: the b vector (differential bias) in the fitting Ta=b.
        :axis: Fitted energy axis.
    """

    vals = np.array(vals)
    nvals = vals.size

    if refid >= nvals:
        wn.warn(
            "Reference index (refid) cannot be larger than the number of traces!\
                Reset to the largest allowed number.",
        )
        refid = nvals - 1

    # Top-to-bottom ordering of terms in the T matrix
    termorder = np.delete(range(0, nvals, 1), refid)
    termorder = np.tile(termorder, aug)
    # Left-to-right ordering of polynomials in the T matrix
    polyorder = np.linspace(order, 1, order, dtype="int")

    # Construct the T (differential drift time) matrix, Tmat = Tmain - Tsec
    Tmain = np.array([pos[refid] ** p for p in polyorder])
    # Duplicate to the same order as the polynomials
    Tmain = np.tile(Tmain, (aug * (nvals - 1), 1))

    Tsec = []

    for to in termorder:
        Tsec.append([pos[to] ** p for p in polyorder])
    Tsec = np.asarray(Tsec)
    Tmat = Tmain - Tsec

    # Construct the b vector (differential bias)
    bvec = vals[refid] - np.delete(vals, refid)
    bvec = np.tile(bvec, aug)

    # Solve for the a vector (polynomial coefficients) using least squares
    if method == "lstsq":
        sol = lstsq(Tmat, bvec, rcond=None)
    elif method == "lsqr":
        sol = lsqr(Tmat, bvec, **kwds)
    a = sol[0]

    # Construct the calibrating function
    pfunc = partial(tof2evpoly, a)

    # Return results according to specification
    ecalibdict = {}
    ecalibdict["offset"] = np.asarray(pos).min()
    ecalibdict["coeffs"] = a
    ecalibdict["Tmat"] = Tmat
    ecalibdict["bvec"] = bvec
    if (E0 is not None) and (t is not None):
        ecalibdict["axis"] = pfunc(E0, t)
        ecalibdict["E0"] = E0

    elif (Eref is not None) and (t is not None):
        E0 = -pfunc(-Eref, pos[refid])
        ecalibdict["axis"] = pfunc(E0, t)
        ecalibdict["E0"] = E0

    if ret == "all":
        return ecalibdict
    elif ret == "func":
        return pfunc
    else:
        return project(ecalibdict, ret)


def apply_energy_correction(
    df: Union[pd.DataFrame, dask.dataframe.DataFrame],
    type: str,
    **kwds,
) -> Union[pd.DataFrame, dask.dataframe.DataFrame]:
    """Apply correction to the time-of-flight (TOF) axis of single-event data.

    :Parameters:
        type: str
            Type of correction to apply to the TOF axis.
        **kwds: keyword arguments
            Additional parameters to use for the correction.
            :corraxis: str | 't'
                String name of the axis to correct.
            :center: list/tuple | (650, 650)
                Image center pixel positions in (row, column) format.
            :amplitude: numeric | -1
                Amplitude of the time-of-flight correction term
                (negative sign meaning subtracting the curved wavefront).
            :d: numeric | 0.9
                Field-free drift distance.
            :t0: numeric | 0.06
                Time zero position corresponding to the tip of the valence band.
            :gamma: numeric
                Linewidth value for correction using a 2D Lorentz profile.
            :sigma: numeric
                Standard deviation for correction using a 2D Gaussian profile.
            :gam2: numeric
                Linewidth value for correction using an asymmetric 2D Lorentz profile,
                X-direction.
            :amplitude2: numeric
                Amplitude value for correction using an asymmetric 2D Lorentz profile,
                X-direction.

    :Return:

    """

    corraxis = kwds.pop("corraxis", "t")
    ycenter, xcenter = kwds.pop("center", (650, 650))
    amplitude = kwds.pop("amplitude", -1)
    X = kwds.pop("X", "X")
    Y = kwds.pop("Y", "Y")

    if type == "spherical":
        d = kwds.pop("d", 0.9)
        t0 = kwds.pop("t0", 0.06)
        df[corraxis] += (
            (
                np.sqrt(
                    1
                    + ((df[X] - xcenter) ** 2 + (df[Y] - ycenter) ** 2)
                    / d**2,
                )
                - 1
            )
            * t0
            * amplitude
        )
        return df

    elif type == "Lorentzian":
        gam = kwds.pop("gamma", 300)
        df[corraxis] += (
            amplitude
            / (gam * np.pi)
            * (
                gam**2
                / ((df[X] - xcenter) ** 2 + (df[Y] - ycenter) ** 2 + gam**2)
            )
        ) - amplitude / (gam * np.pi)
        return df

    elif type == "Gaussian":
        sig = kwds.pop("sigma", 300)
        df[corraxis] += (
            amplitude
            / np.sqrt(2 * np.pi * sig**2)
            * np.exp(
                -((df[X] - xcenter) ** 2 + (df[Y] - ycenter) ** 2)
                / (2 * sig**2),
            )
        )
        return df

    elif type == "Lorentzian_asymmetric":
        gam = kwds.pop("gamma", 300)
        gam2 = kwds.pop("gamma2", 300)
        amplitude2 = kwds.pop("amplitude2", -1)
        df[corraxis] += (
            amplitude
            / (gam * np.pi)
            * (gam**2 / ((df[Y] - ycenter) ** 2 + gam**2))
        )
        df[corraxis] += (
            amplitude2
            / (gam2 * np.pi)
            * (gam2**2 / ((df[X] - xcenter) ** 2 + gam2**2))
        )
        return df

    else:
        raise NotImplementedError


def append_energy_axis(
    df: Union[pd.DataFrame, dask.dataframe.DataFrame],
    E0: float,
    **kwds,
) -> Union[pd.DataFrame, dask.dataframe.DataFrame]:
    """Calculate and append the E axis to the events dataframe.
    This method can be reused.

    **Parameter**\n
    E0: numeric
        Time-of-flight offset.
    """

    tof_column = kwds.pop("tof_column", "t")
    energy_column = kwds.pop("energy_column", "E")

    if ("t0" in kwds) and ("d" in kwds):
        t0 = kwds.pop("t0")
        d = kwds.pop("d")
        df[energy_column] = tof2ev(
            d,
            t0,
            E0,
            df[tof_column].astype("float64"),
            **kwds,
        )
        return df

    elif "a" in kwds:
        poly_a = kwds.pop("a")
        df[energy_column] = tof2evpoly(
            poly_a,
            E0,
            df[tof_column].astype("float64"),
            **kwds,
        )
        return df
    else:
        raise NotImplementedError


def tof2ev(
    d: float,
    t0: float,
    E0: float,
    t: Sequence[float],
    binwidth: float = 4.125e-12,
    binning: int = 1,
) -> Sequence[float]:
    """
    d/(t-t0) expression of the time-of-flight to electron volt
    conversion formula.

    **Parameters**\n
    d: float
        Drift distance
    t0: float
        time offset
    E0: float
        Energy offset.
    t: numeric array
        Drift time of electron.

    **Return**\n
    E: numeric array
        Converted energy
    """

    #    m_e/2 [eV]            bin width [s]
    E = 2.84281e-12 * (d / (t * binwidth * 2**binning - t0)) ** 2 + E0

    return E


def tof2evpoly(
    a: Sequence[float],
    E0: float,
    t: Sequence[float],
) -> Sequence[float]:
    """
    Polynomial approximation of the time-of-flight to electron volt
    conversion formula.

    **Parameters**\n
    a: 1D array
        Polynomial coefficients.
    E0: float
        Energy offset.
    t: numeric array
        Drift time of electron.

    **Return**\n
    E: numeric array
        Converted energy
    """

    odr = len(a)  # Polynomial order
    a = a[::-1]
    E = 0

    for i, d in enumerate(range(1, odr + 1)):
        E += a[i] * t**d
    E += E0

    return E

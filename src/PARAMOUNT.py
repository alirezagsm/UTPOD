import os
import shutil
import psutil
from pathlib import Path
import logging
import numpy as np
import pandas as pd
from dask import delayed
from dask.distributed import Client, LocalCluster, wait
import dask.dataframe as dd
import dask.array as da
import re

from src.utils import utils
from tqdm import tqdm

# suppress dask user warnings
# logging.getLogger("distributed").setLevel(logging.CRITICAL)


# logging.getLogger("distributed.utils_perf").setLevel(logging.CRITICAL)
# logging.getLogger("distributed.diskutils").setLevel(logging.CRITICAL)
# logging.getLogger("distributed.worker_memory").setLevel(logging.CRITICAL)

# help pd output better fit in console
pd.set_option("display.max_colwidth", 20)


class Base:
    def __init__(self, show_dashboard) -> None:
        self.cluster, self.client = self.create_cluster(show_dashboard)

    def create_cluster(self, show_dashboard):
        """
        create_cluster create a dask cluster. modify LocalCluster for parallel runs on
        remote clusters. webbrowser.open() shows the dask operation in browser.

        Returns:
            tuple: cluster, client
        """

        total_memory = psutil.virtual_memory().total
        core_count = psutil.cpu_count(logical=True)

        n_workers = max(6, core_count // 3)  # Number of workers
        threads_per_worker = 2  # Number of threads per worker
        memory_limit = f"{total_memory / 2**30}GB"  # Memory per worker = total_memory (over allocated)

        cluster = LocalCluster(
            dashboard_address="localhost:8000",
            n_workers=n_workers,
            threads_per_worker=threads_per_worker,
            memory_limit=memory_limit,
            silence_logs=logging.WARN,
        )
        client = Client(cluster)

        print(client.cluster)
        print(client.dashboard_link)
        if show_dashboard:
            import webbrowser

            webbrowser.open(cluster.dashboard_link, new=2)

        return cluster, client

    @staticmethod
    def read_csv_columns(
        path_csv=Path.cwd(), skiprows=0, delimiter=",", boolPrint=True
    ):
        """
        read_csv_columns get columns of a csv file and print the headers


        Args:
            path_csv (str, optional): path to folder containing csv files. Defaults to Path.cwd().
            skiprows (int, optional): rows to skip in each csv file. Defaults to 0.
            delimiter (str, optional): delimiter used in csv files. Defaults to ",".
            boolPrint (bool, optional): whether to print our the columns. Defaults to True.

        Returns:
            list: the headers found in the first csv file
        """
        """

        Returns:
            list: headers in csv file
        """
        pathlist = sorted(Path(path_csv).resolve().glob("*.csv"))
        df = pd.read_csv(pathlist[0], sep=delimiter, skiprows=skiprows)
        print(df.head())
        headers = df.columns.tolist()
        if boolPrint:
            print(pd.DataFrame({"Available headers": headers}))
        return headers

    @staticmethod
    def check_csv(
        path_csv=Path.cwd(),
        delimiter=",",
        skiprows=0,
    ):
        pathlist = sorted(Path(path_csv).resolve().glob("*.csv"))
        result0 = pd.read_csv(pathlist[0], sep=delimiter, skiprows=skiprows)
        for path_csv in tqdm(pathlist[1:], "Comparing csv line numbers"):
            result = pd.read_csv(path_csv, sep=delimiter, skiprows=skiprows)
            if result.shape != result0.shape:
                print(" Mismatch found")
                print(f"{path_csv.name} {result.shape}")

    @staticmethod
    def get_folderlist(
        path=".data", boolPrint=True, ignoreStack=False, onlyStack=False
    ):
        """
        get_folderlist get list of folders in a given path

        Args:
            path (str, optional): path to look for folders. Defaults to ".data".
            boolPrint (bool, optional): whether to print out the folders. Defaults to True.

        Returns:
            list: list of available folders
        """
        files = Path.cwd() / path
        if not files.is_dir():
            os.makedirs(files)

        folderlist = [f for f in files.iterdir() if f.is_dir()]
        folderlist = [folder.parts[-1] for folder in folderlist]
        if ignoreStack:
            folderlist = [
                folder for folder in folderlist if folder.split("_")[0] != "stack"
            ]
        if onlyStack:
            if ignoreStack:
                print("WARNING: ignoreStack flag is ignored")
            folderlist = [
                folder for folder in folderlist if folder.split("_")[0] == "stack"
            ]
        if boolPrint:
            print(pd.DataFrame({"Available folders": folderlist}))
        return folderlist

    def csv_to_parquet(
        self,
        variables,
        coordinates="2D",
        path_csv=Path.cwd(),
        path_parquet=".data",
        i_start=0,
        i_end=None,
        delimiter=",",
        skiprows=0,
    ):
        """
        csv_to_parquet read all csv files in path and save desired variables in parquet format
        x, y, z spatial values are read from the first csv file


        Args:
            variables (list): list of variables to consider
            coordinates (str): Cartesian coordinates to store e.g. 2D for 'xy' and 3D for 'xyz'.
            path_csv (_type_, optional): Path to folder contining CSV files. Defaults to Path.cwd().
            path_parquet (str, optional): Path to save parquet database in. Defaults to ".data".
            i_start (int, optional): index for first CSV file. Defaults to 0.
            i_end (_type_, optional): index for last CSV file. Defaults to None which means consider all files.
            delimiter (str, optional): delimiter in CSV file. Defaults to ",".
            skiprows (int, optional): number of rows to skip. Defaults to 0.

        Raises:
            ValueError: checking for existing folders and warn user about unwanted overwrites
        """

        variables = variables if type(variables) is list else [variables]

        self.make_dim(coordinates)

        utils.ensure_dir(path_parquet)

        v_ = variables.copy()
        v_ = self.overwrite_guard(path_parquet, v_)
        variables = v_

        pathlist = sorted(Path(path_csv).resolve().glob("*.csv"))
        if i_end is not None:
            if len(pathlist) < i_end:
                print("i_end is longer than pathlist")
                i_end = len(pathlist)
            pathlist = pathlist[i_start:i_end]
        else:
            pathlist = pathlist[i_start:]

        df = pd.read_csv(pathlist[0], sep=delimiter, skiprows=skiprows)

        try:
            for item in df.columns:
                if re.match(r"\s*" + "x", item, re.IGNORECASE):
                    variables.remove(item)
                    if "x" in self.dim:
                        utils.saveit(df[item], f"{path_parquet}/x.pkl")
                if re.match(r"\s*" + "y", item, re.IGNORECASE):
                    variables.remove(item)
                    if "y" in self.dim:
                        utils.saveit(df[item], f"{path_parquet}/y.pkl")
                if re.match(r"\s*" + "z", item, re.IGNORECASE):
                    variables.remove(item)
                    if "z" in self.dim:
                        utils.saveit(df[item], f"{path_parquet}/z.pkl")
        except Exception as e:
            print(f"warning: you did not specify all coordinate variables: {e}")

        results = [[] for x in range(len(variables))]

        for path_csv in tqdm(pathlist, "analyzing csv files"):
            for i, var in enumerate(variables):
                result = dd.read_csv(path_csv, sep=delimiter, skiprows=skiprows)
                results[i].append(result[var])

        for i, var in enumerate(tqdm(variables, "writing parquet database")):
            df = dd.concat(results[i], axis=1, ignore_unknown_divisions=True)
            df.columns = [path.stem for path in pathlist]
            dd.to_parquet(
                df.repartition(partition_size="150MB", force=True),
                f"{path_parquet}/{var.strip()}",
                compression="snappy",
                write_metadata_file=True,
            )

    @staticmethod
    def extract_csv_sequential(
        path_csv=Path.cwd(),
        path_save=".data",
        delimiter=",",
        x0=0,
        y0=0,
        tol=1e-3,
        skiprows=0,
        booldisplay=False,
    ):
        """
        extract_csv_sequential extract data from a point in sequential manner

        Args:
            path_csv (str, optional): path to csv database. Defaults to Path.cwd().
            path_save (str, optional): path to save resutls to. Defaults to ".data".
            delimiter (str, optional): delimiter used in csv files. Defaults to ",".
            x0 (float, optional): targer x coordinate. Defaults to 0.
            y0 (float, optional): targer y coordinate. Defaults to 0.
            z0 (float, optional): targer z coordinate. Defaults to 0.
            tol (float, optional): tolerance for point detection. Defaults to 1e-3.
            skiprows (int, optional): rows to skip in csv files. Defaults to 0.
        """
        pathlist = sorted(Path(path_csv).resolve().glob("*.csv"))
        df = pd.read_csv(pathlist[0], sep=delimiter, skiprows=skiprows)

        x = df.iloc[:, 0]
        y = df.iloc[:, 1]

        tol = 1e-3

        for i in range(len(x)):
            if abs(x[i] - x0) < tol and abs(y[i] - y0) < tol:
                index = i
                break

        if booldisplay:
            import matplotlib.pyplot as plt
            from IPython.display import display

            fig, ax = plt.subplots()
            fig.set_size_inches(6, 15)
            ax.scatter(x, y, color="k")
            ax.scatter(x[index], y[index], color="r")
            display(fig)

        variables = df.columns[3:]

        results = []
        for path_csv in tqdm(pathlist, "analyzing csv files"):
            result = pd.read_csv(path_csv, sep=delimiter, skiprows=skiprows)
            results.append(result.iloc[index, :])
        results = pd.concat(results, axis=1)
        results.columns = [path.stem for path in pathlist]
        results = results.T
        print(results)
        utils.ensure_dir(path_save)
        for var in variables:
            utils.saveit(results[var], f"{path_save}/{var}")

    @staticmethod
    def read_csv_sequential(
        path_csv=Path.cwd(),
        path_save=".data",
        delimiter=",",
        skiprows=0,
    ):
        """
        read_csv_sequential read values from csv database that is not clean
        and had units e.g. 3.123 [m/s] in each row

        Args:
            path_csv (str, optional): path to csv database. Defaults to Path.cwd().
            path_save (str, optional): path to save resutls to. Defaults to ".data".
            delimiter (str, optional): delimiter used in csv files. Defaults to ",".
            skiprows (int, optional):  rows to skip in csv files. Defaults to 0.
        """
        pathlist = sorted(Path(path_csv).resolve().glob("*.csv"))

        df = pd.read_csv(pathlist[0], sep=delimiter, skiprows=skiprows)
        df.applymap(lambda x: float(re.sub(r"\[(.*?)\]", "", x)))
        print(df.head())
        headers = df.columns.tolist()
        print(pd.DataFrame({"Available headers": headers}))
        variables = headers

        results = [[] for x in range(len(variables))]
        for path_csv in tqdm(pathlist, "analyzing csv files"):
            for i, var in enumerate(variables):
                result = pd.read_csv(path_csv, sep=delimiter, skiprows=skiprows)
                result = result.applymap(lambda x: float(re.sub(r"\[(.*?)\]", "", x)))
                results[i].append(result[var][0])

        for i, var in enumerate(variables):
            utils.ensure_dir(path_save)
            print(f"saving {var} {results[i][:10]}")
            utils.saveit(results[i], f"{path_save}/{var.strip()}")

    @staticmethod
    def fft_signal(signal, dt, path_save=Path.cwd(), fmax=3000):
        """
        fft_signal produce fast Fourier transform plot of a given signal

        Args:
            signal (Series): raw data
            dt (float): acquisition time period
            path_save (str, optional): path to save fft plot. Defaults to Path.cwd().
            fmax (int): maximum frequency to include in plot
        """
        import numpy as np
        from scipy.fft import fft, fftfreq
        import matplotlib.pyplot as plt

        plt.rc("font", family="Times New Roman")
        plt.rc("font", size=14)

        N = len(signal)
        T = dt

        yf = fft(signal)
        xf = fftfreq(N, T)[: N // 2]

        yff = 2.0 / N * np.abs(yf[1 : N // 2])
        xff = xf[1 : N // 2]

        fig, ax = plt.subplots()
        fig.set_size_inches(5, 4)
        fig.patch.set_facecolor("w")
        ax.plot(xff, yff, "k", linewidth=0.75)
        ax.set_xlim(0, fmax)
        ax.set_ylim(0, max(yff) * 1.05)
        ax.set_xlabel("Frequency [Hz]")
        ax.set_ylabel("FFT magnitude")

        ax.set_axisbelow(True)
        ax.grid(alpha=0.5, which="both")

        fig.tight_layout()
        for axis in ["bottom", "left"]:
            ax.spines[axis].set_linewidth(0.5)
        for axis in ["top", "right"]:
            ax.spines[axis].set_linewidth(0)
        plt.savefig(f"{path_save}/fft" + ".png", dpi=300, bbox_inches="tight")
        plt.close("all")
        plt.show()

    @staticmethod
    def check_parquet(path_parquet=".data"):
        """
        check_parquet read and print head of all parquet files in path

        Args:
            path_parquet (str, optional): path to look for parquet files. Defaults to ".data".
        """
        pathlist = (Path.cwd() / path_parquet).glob("*/*.parquet")
        for path in tqdm(pathlist, "reading parquet databases"):
            print(path)
            df = dd.read_parquet(path, engine="pyarrow")
            print(df.head())
            print(len(df))

    @staticmethod
    def correlate(v1, v2):
        """
        correlate find pearson's correlation as well as maximum correlation found for a time lag between signals

        Args:
            v1 (series): first variables time series
            v2 (series): second variables time series

        Returns:
            (tuple): pearson's index, maximum correlation
        """
        from scipy import signal

        corr = (
            signal.correlate(v1 - np.mean(v1), v2 - np.mean(v2), mode="full")
            / len(v1)
            / np.std(v1)
            / np.std(v2)
        )
        corr_smooth = (
            pd.DataFrame(corr)
            .rolling(window=max(int(len(v1) * 0.01), 5), center=True, closed="both")
            .mean()
        )
        lagindex = corr_smooth.iloc[:, 0].argmax()

        corrcoef = corr[int(len(corr) / 2)]
        corrcoef_adj = corr[lagindex]
        return corrcoef, corrcoef_adj

    def correlation_signals(
        self,
        path_signals=".signals",
        path_signals2=".signals2",
        path_viz=".viz",
    ):
        """
        correlation_signals plot correlation heatmap between signals.
        The signals are assumed to be in pickled format in two folders

        Args:
            path_signals (str, optional): folder for first set of signals. Defaults to ".usv".
            path_signals2 (str, optional): folder for second set of signals. Defaults to ".usv2".
            path_viz (str, optional): path to store plots in. Defaults to ".viz".
        """
        import matplotlib.pyplot as plt
        from mpl_toolkits.axes_grid1 import make_axes_locatable

        utils.ensure_dir(path_viz)

        pathlist = Path(path_signals).resolve().glob("*")
        pathlist2 = Path(path_signals2).resolve().glob("*")

        signals = []
        for path in pathlist:
            signals.append(pd.Series(utils.loadit(path), name=path.name))
        signaldf = pd.concat(signals, axis=1)

        signals = []
        for path in pathlist2:
            signals.append(pd.Series(utils.loadit(path), name=path.name))
        signaldf2 = pd.concat(signals, axis=1)

        dfcorr_adjusted = pd.DataFrame(
            np.nan, columns=range(signaldf.shape[1]), index=range(signaldf2.shape[1])
        )
        dfcorr = pd.DataFrame(
            np.nan, columns=range(signaldf.shape[1]), index=range(signaldf2.shape[1])
        )

        for i in tqdm(range(signaldf.shape[1]), "computing correlations"):
            for j in range(signaldf2.shape[1]):
                v1 = signaldf.iloc[:, i]
                v2 = signaldf2.iloc[:, j]
                corrcoef, corrcoef_adj = self.correlate(v1, v2)
                dfcorr.iat[i, j] = corrcoef
                dfcorr_adjusted.iat[i, j] = corrcoef_adj

        for name, df in zip(["corr", "corr_adjusted"], [dfcorr, dfcorr_adjusted]):
            fig, ax = plt.subplots()
            fig.set_size_inches(
                self.width * signaldf.shape[1] / signaldf2.shape[1], self.width
            )
            fig.patch.set_facecolor("w")

            ax1 = ax.imshow(df.abs(), interpolation="none", aspect="equal")
            ax1.set_clim(0, 1)
            divider = make_axes_locatable(ax)
            cax = divider.append_axes(
                "right",
                size=self.width * 5 / 100,
                pad=self.width * 2 / 100,
            )
            cbar = fig.colorbar(ax1, cax=cax)
            cbar.ax.set_xlabel("Correlation Coefficient")

            for i in range(1, 1 + signaldf.shape[1]):
                ax.axhline(i - 0.5, color="w")
            for i in range(1, 1 + signaldf2.shape[1]):
                ax.axvline(i - 0.5, color="w")

            sigloc = np.arange(
                0,
                signaldf.shape[1],
                step=1,
            )
            sigloc2 = np.arange(
                0,
                signaldf2.shape[1],
                step=1,
            )
            ax.xaxis.set_ticks(
                sigloc,
                signaldf.columns,
                rotation=90,
                ha="center",
            )
            ax.yaxis.set_ticks(
                sigloc2,
                signaldf2.columns,
            )

            ax.xaxis.remove_overlapping_locs = True
            ax.yaxis.remove_overlapping_locs = False

            plt.savefig(
                f"{path_viz}/Sigs_{name}" + ".png",
                dpi=self.dpi,
                bbox_inches="tight",
            )
            plt.close("all")

    def make_dim(self, coordinates):
        """
        make_dim set the analysis dimensions

        Args:
            coordinates (str): "2d" or "3d"
        """
        coordinates = coordinates.lower().strip()
        if coordinates == "2d":
            self.dim = "xy"
        elif coordinates == "3d":
            self.dim = "xyz"
        else:
            raise ("please specify 2D or 3D as coordinates")

    def make_bounds(self, xyz):
        """
        make_bounds define analysis bounds

        Args:
            xyz (list): x, y ,z coordinate of points

        Returns:
            list: bounds of analysis and spatial resolution
        """
        if self.dim == "xy":
            x = xyz[0]
            y = xyz[1]
            xmin = min(x)
            xmax = max(x)
            ymin = min(y)
            ymax = max(y)
            lmax = max(xmax, ymax)
            lmin = max(xmin, ymin)
            res = (lmax - lmin) / 1000
            return [xmin, xmax, ymin, ymax, res]
        if self.dim == "xyz":
            x = xyz[0]
            y = xyz[1]
            z = xyz[2]
            xmin = min(x)
            xmax = max(x)
            ymin = min(y)
            ymax = max(y)
            zmin = min(z)
            zmax = max(z)
            lmax = max(xmax, ymax, zmax)
            lmin = max(xmin, ymin, zmin)
            res = (lmax - lmin) / 75
            return [xmin, xmax, ymin, ymax, zmin, zmax, res]

    def set_time(self, dt, t0=0):
        """
        set_time set timestep and initial time of data acquisition

        Args:
            dt (float): timestep
            t0 (float): initial time
        """
        try:
            self.data_skip
        except:
            self.data_skip = None

        if self.data_skip is not None:
            self.dt = dt * self.data_skip
        else:
            self.dt = dt
        self.t0 = t0

    def data_decimate(self, df, X1=False, X2=False):
        """
        data_decimate preprocess a DataFrame by applying various transformations such as cutting off columns, skipping
        columns, and slicing columns based on certain conditions

        Args:
            df : The DataFrame to be decimated
            X1 (bool, optional): flag to determine if the last column should be excluded.
            X2 (bool, optional): flag to determine if the first column should be excluded.
        Returns:
            df
        """
        try:
            self.data_cutoff
        except:
            self.data_cutoff = None

        try:
            self.data_cutin
        except:
            self.data_cutin = None

        try:
            self.data_skip
        except:
            self.data_skip = None

        if self.data_cutoff is not None:
            cutoff = int(df.shape[1] * self.data_cutoff / 100)
            try:
                df = df[:, :cutoff]
            except:
                df = df.iloc[:, :cutoff]

        if self.data_cutin is not None:
            cutin = int(df.shape[1] * self.data_cutin / 100)
            try:
                df = df[:, cutin:]
            except:
                df = df.iloc[:, cutin:]

        if self.data_skip is not None:
            df = df[:, :: self.data_skip]

        if X1:
            try:
                df = df[:, :-1]
            except:
                df = df.iloc[:, :-1]

        if X2:
            try:
                df = df[:, 1:]
            except:
                df = df.iloc[:, 1:]

        return df

    def set_data_cutin(self, data_cutin):
        self.data_cutin = data_cutin

    def set_data_cutoff(self, data_cutoff):
        self.data_cutoff = data_cutoff

    def set_data_skip(self, data_skip):
        self.data_skip = data_skip

    def set_viz_params(
        self,
        dpi=300,
        linewidth=1.5,
        color="k",
        cmap="seismic",
        ax_width=0.5,
        font="Times New Roman",
        fontsize=14,
        height=4,
        width=5,
        contour_levels=20,
    ):
        """
        set_viz_params set visualization parameters

        Args:
            dpi (int, optional): dpi to save figures. Defaults to 300.
            linewidth (float, optional): line width. Defaults to 1.5.
            color (str, optional): line color. Defaults to 'k'.
            cmap (str, optional): color map to use. Defaults to 'seismic'.
            ax_width (float, optional): linewidth for axes of plots. Defaults to 0.5.
            font (str, optional): font family used in plots. Defaults to "Times New Roman".
            fontsize (int, optional): font size used in plots. Defaults to 14.
            height (int, optional): plot height in inches. Defaults to 4.
            width (int, optional): plot width in inches. Defaults to 6.
        """
        self.dpi = dpi
        self.linewidth = linewidth
        self.color = color
        self.cmap = cmap
        self.ax_width = ax_width
        self.font = font
        self.fontsize = fontsize
        self.width = width
        self.height = height
        self.contour_levels = contour_levels

    def dist_map(self, x, y, bounds):
        """
        dist_map generate a kd-tree distance map for all xy coordinates. sed to mask the visualization results for which no data exists

        Args:
            x (list): list of x coordination values
            y (list): list of y coordination values
            bounds (list): domain bounds for visualization [xmin, xmax, ymin, ymax, resolution]


        Returns:
            list: k-d tree distance map for all xy coordination pairs.
        """
        from scipy.spatial import KDTree

        xx, yy = self.make_meshgrid(bounds)

        tree = KDTree(np.c_[x, y])
        dist, _ = tree.query(np.c_[xx.ravel(), yy.ravel()], k=1)
        dist = dist.reshape(xx.shape)
        return dist

    def make_meshgrid(self, bounds):
        """
        make_meshgrid generates a meshgrid for the domain described by its boundary and meshgrid resolution

        Args:
            bounds (list): domain bounds for visualization [xmin, xmax, ymin, ymax, resolution]


        Returns:
            ndarray: numpy meshgrid
        """
        if self.dim == "xy":
            xmin, xmax, ymin, ymax, res = bounds
            mgrid = np.meshgrid(
                np.arange(
                    xmin,
                    xmax + res,
                    res,
                ),
                np.arange(
                    ymin,
                    ymax + res,
                    res,
                ),
            )
            return mgrid

        if self.dim == "xyz":
            xmin, xmax, ymin, ymax, zmin, zmax, res = bounds
            mgrid = np.meshgrid(
                np.arange(
                    xmin,
                    xmax + res,
                    res,
                ),
                np.arange(
                    ymin,
                    ymax + res,
                    res,
                ),
                np.arange(
                    zmin,
                    zmax + res,
                    res,
                ),
            )
            return mgrid


class POD(Base):
    """

    handle loading and processing csv datasets for POD analysis
    this class can read csv files in bulk and save to fast parquet format
    SVD analysis result are stored in parquet format for fast processing
    pd.Series are serialized and stored in pickle format
    Refer to svd_example.py, csv_example.py and viz_example.py for examples on how to utilize PARAMOUNT.POD

    Available Functions
    ----------
    read_csv_coordinates
    csv_to_parquet
    extract_csv_sequential
    read_csv_sequential
    check_parquet
    correlate
    svd_save_usv
    svd_correlation
    correlation_signals
    svd_correlation_2X
    svd_correlation_signals
    read_csv_columns
    svd_viz
    s_viz_combined

    """

    def __init__(self, show_dashboard=False) -> None:
        """
        initializes a PARAMOUNT POD class
        Args:
            show_dashboard (bool, optional): Whether to open dask dashboard in browser. Defaults to False.
        """
        super().__init__(show_dashboard)
        self.set_viz_params()

    def overwrite_guard(self, path, variables):
        remove_vars = []
        for var in variables:
            if var in self.get_folderlist(path=path, boolPrint=False):
                choice = input(
                    f"{var.strip()} folder already exists! overwrite existing files? [y/n] "
                )
                if choice.lower().strip() == "y":
                    shutil.rmtree(Path.cwd() / path / var)
                else:
                    remove_vars.append(var)

        for var in remove_vars:
            variables.remove(var)

        return variables

    def svd_save_usv(
        self,
        variables,
        path_parquet=".data",
        path_pod=".usv",
        dmd_X1=False,
        in_memory_df=None,
    ):
        """
        svd_save_usv compute distributed Singular Value Decomposition and store results in parquet format.

        Args:
            variables (list or str): list of variables to consider
            path_parquet (str, optional): path to parquet datasets. Defaults to ".data".
            path_pod (str, optional): path to store SVD results in. Defaults to ".usv".
            dmd_X1 (bool, optional): ignored that last snapshot for the DMD procedure. Defaults to False.
            in_memory_df (dataframe, optional): use the in_memory_df instead of reading it from disk. Defaults to None.

        Raises:
            ValueError: checking for existing folders and warn user about unwanted overwrites
        """
        variables = variables if type(variables) is list else [variables]
        v_ = variables.copy()
        if in_memory_df is None:
            v_ = self.overwrite_guard(path_pod, v_)
        variables = v_

        try:
            shutil.copy(Path.cwd() / path_parquet / "x.pkl", path_pod)
            shutil.copy(Path.cwd() / path_parquet / "y.pkl", path_pod)
            shutil.copy(Path.cwd() / path_parquet / "z.pkl", path_pod)
        except:
            pass

        for var in tqdm(variables, "computing SVD modes"):
            path = Path.cwd() / path_parquet / f"{var}"
            # utils.ensure_dir(path)
            if in_memory_df is None:
                df = dd.read_parquet(path, engine="pyarrow")
            else:
                df = in_memory_df
            df = self.data_decimate(df, X1=dmd_X1)
            u, s, v = da.linalg.svd(df.values)

            for name, item in zip(["u", "v"], [u, v]):
                # uncomment if dask complains about unknown dimensions
                # if np.isnan(item.shape[0]):
                #     item = item.compute()
                result = dd.from_array(item)
                result.columns = result.columns.astype(str)
                # set write_metadata_file to False in case of worker error
                dd.to_parquet(
                    result,
                    f"{path_pod}/{var}/{name}",
                    compression="snappy",
                    write_metadata_file=True,
                )
                self.client.cancel(result)  # free up memory

            del result, u, v  # free up memory
            result = dd.from_array(s).compute()
            utils.saveit(result, f"{path_pod}/{var}/s.pkl")

    def svd_correlation(self, variables, maxmode=5, path_pod=".usv", path_viz=".viz"):
        """
        svd_correlation produces correlation heatmap between modes for specified variables.
        The correlation map shows the default Pearson's correlation between mode pairs on the lower triangle
        Upper triangle shows the maximum correlation coefficient accounting for time lag between mode pairs


        Args:
            variables (list): list of variables to consider in the correlation map
            maxmode (int, optional): maximum number of modes to consider in the correlation map. Defaults to 5.
            path_pod (str, optional):  path to read SVD results from. Defaults to ".usv".
            path_viz (str, optional): path to store plots in. Defaults to ".viz".
        """

        import matplotlib.pyplot as plt
        from matplotlib.ticker import AutoMinorLocator, FuncFormatter
        from mpl_toolkits.axes_grid1 import make_axes_locatable
        from itertools import combinations
        from scipy import signal

        plt.rc("font", family=self.font)
        plt.rc("font", size=self.fontsize)

        utils.ensure_dir(path_viz)

        maxmode = max(list(maxmode))
        variables = variables if type(variables) is list else [variables]
        path_v = Path.cwd() / path_pod / f"{variables[0]}" / "v"
        df = dd.read_parquet(path_v, engine="pyarrow")
        df = df.compute().iloc[:maxmode, :].transpose()
        for v in variables[1:]:
            path_v = Path.cwd() / path_pod / f"{v}" / "v"
            df2 = dd.read_parquet(path_v, engine="pyarrow")
            df2 = df2.compute().iloc[:maxmode, :].transpose()
            df = pd.concat([df, df2], axis=1)
        df = df.dropna()
        results = []
        combs = list(combinations(range(len(df.columns)), 2))
        for comb in combs:
            v1 = df.iloc[:, comb[0]]
            v2 = df.iloc[:, comb[1]]
            _, corrcoef_adj = self.correlate(v1, v2)
            results.append(
                [
                    comb,
                    corrcoef_adj,
                    # lag * self.dt,
                ]
            )
        corr_adjusted = pd.DataFrame(np.nan, columns=df.columns, index=df.columns)
        for result in results:
            corr_adjusted.iat[result[0][0], result[0][1]] = result[1]
        corr = df.corr()
        corr = corr.where(np.tril(np.ones(corr.shape), k=0).astype(bool)).abs()
        fig, ax = plt.subplots()
        fig.set_size_inches(self.width * 2, self.width * 2)
        fig.patch.set_facecolor("w")

        ax2 = ax.imshow(corr, interpolation="none", aspect="equal")
        ax1 = ax.imshow(corr_adjusted, interpolation="none", aspect="equal")
        ax2.set_clim(0, 1)
        ax1.set_clim(0, 1)
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="5%", pad="4%")
        cbar = fig.colorbar(ax1, cax=cax)
        cbar.ax.set_xlabel("Correlation Coefficient")
        for i in range(1, len(variables)):
            ax.axhline(i * maxmode - 0.5, color="w")
            ax.axvline(i * maxmode - 0.5, color="w")

        varlabels = []
        for var in variables:
            label = re.sub(r"\[(.*?)\]", "", var)
            label = re.sub(r"\.", " ", label)
            varlabels.append(label)

        majorloc = np.arange(
            np.floor(maxmode / 2),
            maxmode * len(variables) + np.floor(maxmode / 2),
            step=maxmode,
        )
        ax.xaxis.set_ticks(majorloc, varlabels)
        ax.yaxis.set_ticks(
            majorloc,
            varlabels,
            rotation=90,
            va="center",
        )
        ax.xaxis.set_minor_locator(AutoMinorLocator(maxmode))
        ax.yaxis.set_minor_locator(AutoMinorLocator(maxmode))

        indexskip = int((maxmode + 1) / 5)
        ax.xaxis.set_minor_formatter(
            FuncFormatter(
                lambda x, pos: (
                    f"{x % maxmode:.0f}"
                    if (x % maxmode) in np.arange(0, maxmode - 1, indexskip)
                    else ""
                )
            )
        )
        ax.yaxis.set_minor_formatter(
            FuncFormatter(
                lambda x, pos: (
                    f"{x % maxmode:.0f}"
                    if (x % maxmode) in np.arange(0, maxmode - 1, indexskip)
                    else ""
                )
            )
        )
        ax.xaxis.remove_overlapping_locs = False
        ax.yaxis.remove_overlapping_locs = False
        ax.tick_params(axis="both", which="both", length=7)
        ax.tick_params(axis="both", which="major", pad=20)

        plt.savefig(
            f"{path_viz}/correlation_{maxmode}" + ".png",
            dpi=self.dpi,
            bbox_inches="tight",
        )
        plt.close("all")

    def svd_correlation_2X(
        self,
        variables,
        maxmode=11,
        path_pod=".usv",
        path_pod2=".usv2",
        path_viz=".corr2X",
    ):
        """
        svd_correlation_2X pairwise correlation map between two separe SVD results.

        Args:
            variables (list): variables to consider
            maxmode (int, optional): maximum mode number to include in analysis. Defaults to 11.
            path_pod (str, optional): first results folder. Will be shown as the y axis. Defaults to ".usv".
            path_pod2 (str, optional): second results folder. Will be shown as the x axis. Defaults to ".usv2".
            path_viz (str, optional): path to store plots in. Defaults to ".corr2X".
        """
        import matplotlib.pyplot as plt
        from matplotlib.ticker import AutoMinorLocator, FuncFormatter
        from mpl_toolkits.axes_grid1 import make_axes_locatable
        from scipy import signal

        plt.rc("font", family=self.font)
        plt.rc("font", size=self.fontsize)

        utils.ensure_dir(path_viz)

        variables = variables if type(variables) is list else [variables]

        path_v = Path.cwd() / path_pod / f"{variables[0]}" / "v"
        df = dd.read_parquet(path_v, engine="pyarrow")
        df = df.compute().iloc[:maxmode, :].transpose()
        for v in variables[1:]:
            path_v = Path.cwd() / path_pod / f"{v}" / "v"
            df2 = dd.read_parquet(path_v, engine="pyarrow")
            df2 = df2.compute().iloc[:maxmode, :].transpose()
            df = pd.concat([df, df2], axis=1)

        for v in variables:
            path_v = Path.cwd() / path_pod2 / f"{v}" / "v"
            df2 = dd.read_parquet(path_v, engine="pyarrow")
            df2 = df2.compute().iloc[:maxmode, :].transpose()
            df = pd.concat([df, df2], axis=1)

        df = df.dropna()
        len_ = int(len(df.columns) / 2)
        dfcorr_adjusted = pd.DataFrame(np.nan, columns=range(len_), index=range(len_))
        dfcorr = pd.DataFrame(np.nan, columns=range(len_), index=range(len_))
        for i in tqdm(range(len_), "computing correlations"):
            for j in range(len_):
                v1 = df.iloc[:, i]
                v2 = df.iloc[:, len_ + j]
                corrcoef, corrcoef_adj = self.correlate(v1, v2)
                dfcorr.iat[i, j] = corrcoef
                dfcorr_adjusted.iat[i, j] = corrcoef_adj

        diff = dfcorr_adjusted.T - dfcorr_adjusted
        diff = diff.where(np.triu(np.ones(diff.shape), k=0).astype(np.bool))

        for name, df in zip(
            ["corr", "corr_adjusted", "diff"], [dfcorr, dfcorr_adjusted, diff]
        ):
            fig, ax = plt.subplots()
            fig.set_size_inches(self.width * 2, self.width * 2)
            fig.patch.set_facecolor("w")

            ax1 = ax.imshow(df.abs(), interpolation="none", aspect="equal")
            ax1.set_clim(0, df.max().max())
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="5%", pad="4%")
            cbar = fig.colorbar(ax1, cax=cax)
            cbar.ax.set_xlabel("Correlation Coefficient")
            for i in range(1, len(variables)):
                ax.axhline(i * maxmode - 0.5, color="w")
                ax.axvline(i * maxmode - 0.5, color="w")

            varlabels = []
            for var in variables:
                label = re.sub(r"\[(.*?)\]", "", var)
                label = re.sub(r"\.", " ", label)
                varlabels.append(label)

            majorloc = np.arange(
                np.floor(maxmode / 2),
                maxmode * len(variables) + np.floor(maxmode / 2),
                step=maxmode,
            )
            ax.xaxis.set_ticks(majorloc, varlabels)
            ax.yaxis.set_ticks(
                majorloc,
                varlabels,
                rotation=90,
                va="center",
            )
            ax.xaxis.set_minor_locator(AutoMinorLocator(maxmode))
            ax.yaxis.set_minor_locator(AutoMinorLocator(maxmode))

            indexskip = int((maxmode + 1) / 5)
            ax.xaxis.set_minor_formatter(
                FuncFormatter(
                    lambda x, pos: (
                        f"{x % maxmode:.0f}"
                        if (x % maxmode) in np.arange(0, maxmode - 1, indexskip)
                        else ""
                    )
                )
            )
            ax.yaxis.set_minor_formatter(
                FuncFormatter(
                    lambda x, pos: (
                        f"{x % maxmode:.0f}"
                        if (x % maxmode) in np.arange(0, maxmode - 1, indexskip)
                        else ""
                    )
                )
            )
            ax.xaxis.remove_overlapping_locs = False
            ax.yaxis.remove_overlapping_locs = False
            ax.tick_params(axis="both", which="both", length=7)
            ax.tick_params(axis="both", which="major", pad=20)

            plt.savefig(
                f"{path_viz}/2X_{name}_{maxmode}" + ".png",
                dpi=self.dpi,
                bbox_inches="tight",
            )
            plt.close("all")

    def svd_correlation_signals(
        self,
        variables,
        maxmode=5,
        path_pod=".usv",
        path_signals=".signals",
        path_viz=".viz",
    ):
        """
        svd_correlation_signals plot correlation heatmap between signals in a folder and
        the svd mode coefficients. Signals are assumed to be in pickled format.

        Args:
            variables (list): list of variables to consider in the correlation map
            maxmode (int, optional): maximum number of modes to consider in the correlation map. Defaults to 5.
            path_pod (str, optional):  path to read SVD results from. Defaults to ".usv".
            path_signals (str, optional): folder for set of signals. Defaults to ".signals".
            path_viz (str, optional): path to save results in. Defaults to ".viz".
        """
        import matplotlib.pyplot as plt
        from matplotlib.ticker import AutoMinorLocator, FuncFormatter
        from mpl_toolkits.axes_grid1 import make_axes_locatable

        plt.rc("font", family=self.font)
        plt.rc("font", size=self.fontsize)

        utils.ensure_dir(path_viz)

        variables = variables if type(variables) is list else [variables]

        path_v = Path.cwd() / path_pod / f"{variables[0]}" / "v"
        df = dd.read_parquet(path_v, engine="pyarrow")
        df = df.compute().iloc[:maxmode, :].transpose()
        for v in variables[1:]:
            path_v = Path.cwd() / path_pod / f"{v}" / "v"
            df2 = dd.read_parquet(path_v, engine="pyarrow")
            df2 = df2.compute().iloc[:maxmode, :].transpose()
            df = pd.concat([df, df2], axis=1)
        df = df.dropna()

        pathlist = Path(path_signals).resolve().glob("*")
        signals = []
        for path in pathlist:
            signals.append(pd.Series(utils.loadit(path), name=path.name))
        signaldf = pd.concat(signals, axis=1)
        dfcorr_adjusted = pd.DataFrame(
            np.nan, columns=range(signaldf.shape[1]), index=range(df.shape[1])
        )
        dfcorr = pd.DataFrame(
            np.nan, columns=range(signaldf.shape[1]), index=range(df.shape[1])
        )

        for i in tqdm(range(df.shape[1]), "computing correlations"):
            for j in range(signaldf.shape[1]):
                v1 = df.iloc[:, i]
                v2 = signaldf.iloc[:, j]
                corrcoef, corrcoef_adj = self.correlate(v1, v2)
                dfcorr.iat[i, j] = corrcoef
                dfcorr_adjusted.iat[i, j] = corrcoef_adj

        for name, df in zip(["corr", "corr_adjusted"], [dfcorr, dfcorr_adjusted]):
            fig, ax = plt.subplots()
            fig.set_size_inches(
                self.width * signaldf.shape[1] / df.shape[1], self.width * 3
            )
            fig.patch.set_facecolor("w")

            ax1 = ax.imshow(df.abs(), interpolation="none", aspect="equal")
            ax1.set_clim(0, 1)
            divider = make_axes_locatable(ax)
            cax = divider.append_axes(
                "right",
                size=self.width * 5 / 100,
                pad=self.width * 2 / 100,
            )
            cbar = fig.colorbar(ax1, cax=cax)
            cbar.ax.set_xlabel("Correlation Coefficient")

            for i in range(1, len(variables)):
                ax.axhline(i * maxmode - 0.5, color="w")
            for i in range(1, 1 + len(signaldf.columns)):
                ax.axvline(i - 0.5, color="w")

            varlabels = []
            for var in variables:
                label = re.sub(r"\[(.*?)\]", "", var)
                label = re.sub(r"\.", " ", label)
                varlabels.append(label)

            majorloc = np.arange(
                np.floor(maxmode / 2),
                maxmode * len(variables) + np.floor(maxmode / 2),
                step=maxmode,
            )
            sigloc = np.arange(
                0,
                signaldf.shape[1],
                step=1,
            )
            ax.xaxis.set_ticks(
                sigloc,
                signaldf.columns,
                rotation=90,
                ha="center",
            )
            ax.yaxis.set_ticks(
                majorloc,
                varlabels,
                rotation=90,
                va="center",
            )
            ax.yaxis.set_minor_locator(AutoMinorLocator(maxmode))

            indexskip = int((maxmode + 1) / 5)
            ax.yaxis.set_minor_formatter(
                FuncFormatter(
                    lambda x, pos: (
                        f"{x % maxmode:.0f}"
                        if (x % maxmode) in np.arange(0, maxmode - 1, indexskip)
                        else ""
                    )
                )
            )
            ax.xaxis.remove_overlapping_locs = True
            ax.yaxis.remove_overlapping_locs = False
            ax.tick_params(axis="y", which="both", length=7)
            ax.tick_params(axis="y", which="major", pad=20)

            plt.savefig(
                f"{path_viz}/Sig_{name}_{maxmode}" + ".png",
                dpi=self.dpi,
                bbox_inches="tight",
            )
            plt.close("all")

    def svd_viz(
        self,
        variables,
        modelist,
        bounds="auto",
        coordinates="2D",
        path_pod=".usv",
        path_viz=".viz",
        freq_max=3000,
        dist=False,
    ):
        """
        svd_viz distributed visualization of Singular Value Decomposition results

        Args:
            variables (list or str): list of variables to consider
            modelist (list): modes to consider
            bounds (list): domain bounds for visualization [xmin, xmax, ymin, ymax, resolution]
            coordinates (str): "2D" or "3D" visualization of modes
            path_pod (str, optional): path to read SVD results from. Defaults to ".usv".
            path_viz (str, optional): path to store plots in. Defaults to ".viz".
            freq_max (float, optional): maximum frequency of interest for PSD plots. Defaults to 3kHz.
            dist (float or bool): distance threshold to mask the xy meshgrid using k-d tree method. Defaults to False.
        """
        variables = variables if type(variables) is list else [variables]
        modelist = modelist if type(modelist) is list else list(modelist)

        self.make_dim(coordinates)

        for var in tqdm(variables, "analyzing variables"):
            utils.ensure_dir(f"{path_viz}/{var}")

            path_u = Path.cwd() / path_pod / f"{var}" / "u"
            path_v = Path.cwd() / path_pod / f"{var}" / "v"
            path_s = Path.cwd() / path_pod / f"{var}" / "s.pkl"
            u = dd.read_parquet(path_u, engine="pyarrow")
            v = dd.read_parquet(path_v, engine="pyarrow")
            s = utils.loadit(path_s)

            if self.dim == "xy":
                path_x = Path.cwd() / path_pod / "x.pkl"
                path_y = Path.cwd() / path_pod / "y.pkl"
                x = utils.loadit(path_x)
                y = utils.loadit(path_y)

                if bounds == "auto":
                    bounds = self.make_bounds([x, y])

                if dist:
                    dist_map = self.dist_map(x, y, bounds)

                self.u_viz(
                    x,
                    y,
                    u,
                    f"{path_viz}/{var}",
                    modelist,
                    bounds,
                    dist,
                    dist_map,
                )

            if self.dim == "xyz":
                path_x = Path.cwd() / path_pod / "x.pkl"
                path_y = Path.cwd() / path_pod / "y.pkl"
                path_z = Path.cwd() / path_pod / "z.pkl"
                x = utils.loadit(path_x)
                y = utils.loadit(path_y)
                z = utils.loadit(path_z)

                if bounds == "auto":
                    bounds = self.make_bounds([x, y, z])

                self.u_viz_3d(
                    x,
                    y,
                    z,
                    u,
                    f"{path_viz}/{var}",
                    modelist,
                    bounds,
                )
            self.v_viz(
                v,
                f"{path_viz}/{var}",
                modelist,
                freq_max,
            )
            self.s_viz(s, f"{path_viz}/{var}")

    def s_viz_combined(
        self,
        variables,
        maxmode=100,
        path_pod=".usv",
        path_viz=".viz",
    ):
        """
        s_viz_combined visualization of all s energy values in one plot shown as cumulative contributions

        Args:
            variables (list or str): list of variables to consider
            maxmode (int): final mode to consider. Defaults to 100
            path_pod (str, optional): path to read SVD results from. Defaults to ".usv".
            path_viz (str, optional): path to store plots in. Defaults to ".viz".
        """

        variables = variables if type(variables) is list else [variables]

        utils.ensure_dir(path_viz)

        s_combined = pd.DataFrame(columns=variables)
        for var in variables:
            path_s = Path.cwd() / path_pod / f"{var}" / "s.pkl"
            s = utils.loadit(path_s)

            mode_energy = [x**2 for x in s]
            mode_energy = [x / sum(mode_energy) * 100 for x in mode_energy]
            cumsum = np.cumsum(mode_energy)
            s_combined[var] = cumsum[:maxmode]

        self.s_viz_combined_plot(s_combined, f"{path_viz}")

    def u_viz_3d(
        self,
        x,
        y,
        z,
        u,
        path_viz,
        modelist,
        bounds,
    ):
        """
        u_viz_3d 3D visualization of SVD mode shapes

        Args:
            x (list): x coordinates
            y (list): y coordinates
            z (list): z coordinates
            u (list): u matrix from SVD analysis
            path_viz (str): path to store plots in
            modelist (list): mode numbers to visualize
            bounds (list): visualization boundaries and resolution
        """
        from scipy.interpolate import griddata
        import plotly.graph_objects as go
        import plotly.io as pio
        from ipywidgets import (
            interact,
            FloatSlider,
            FloatRangeSlider,
            Layout,
            Button,
        )
        from IPython.display import display
        from IPython.core.interactiveshell import InteractiveShell

        InteractiveShell.ast_node_interactivity = "all"

        pio.templates["custom"] = go.layout.Template(
            layout=go.Layout(
                font_family=self.font,
                font_size=self.fontsize,
            )
        )
        pio.templates.default = "simple_white+custom"

        xmin, xmax, ymin, ymax, zmin, zmax, res = bounds
        xx, yy, zz = self.make_meshgrid(bounds)

        figs = [[] for x in range(max(modelist) + 1)]

        for mode in tqdm(modelist, "creating plots", leave=False):
            uu = u.iloc[:, mode].compute()
            kk = griddata(
                (x, z, y),
                uu,
                (xx, zz, yy),
                method="linear",
                fill_value=min(abs(uu)),
            )
            kmin = kk.min()
            kmax = kk.max()
            krng = kmax - kmin
            kmean = kk.mean()
            stp = krng / 100
            kwargs = dict(layout=Layout(width="700px"), readout_format=".4f")
            fig = go.FigureWidget(
                data=go.Isosurface(
                    x=xx.flatten(),
                    z=yy.flatten(),
                    y=zz.flatten(),
                    value=kk.flatten(),
                    isomin=kk.min(),
                    isomax=kk.max(),
                    surface_count=2,
                    opacity=1,
                    colorscale="bluered",
                    caps=dict(x_show=False, y_show=False, z_show=False),
                    showscale=False,
                    flatshading=False,
                    lighting=dict(ambient=0.65, specular=0.8),
                )
            )

            fig.update_layout(
                width=600,
                height=400 * (ymax - ymin) / (xmax - xmin),
                scene=dict(
                    xaxis=dict(
                        gridcolor="lightgray",
                        showticklabels=False,
                        title="",
                        showgrid=True,
                        range=[xmin, xmax],
                    ),
                    yaxis=dict(
                        gridcolor="lightgray",
                        showticklabels=False,
                        title="",
                        showgrid=True,
                        range=[zmin, zmax],
                    ),
                    zaxis=dict(
                        gridcolor="lightgray",
                        showticklabels=False,
                        title="",
                        showgrid=True,
                        range=[ymin, ymax],
                    ),
                    aspectmode="data",
                    camera=dict(eye=dict(x=1.35, y=1.35, z=1.35)),
                ),
                margin=go.layout.Margin(l=0, r=0, b=0, t=0, pad=0),
            )
            figs[mode] = fig
            print(f"fig_id = {mode}")

            @interact(
                fig_id=modelist,
                surface_count=(1, 20, 1),
                opacity=FloatSlider(value=0.5, min=0, max=1, step=0.01, **kwargs),
                iso=FloatSlider(value=kmean, min=kmin, max=kmax, step=stp, **kwargs),
                iso_spread=FloatSlider(value=5, min=0, max=100, step=0.05, **kwargs),
                iso_limits=FloatRangeSlider(
                    value=(kmin, kmax), min=kmin, max=kmax, step=stp, **kwargs
                ),
            )
            def update(
                opacity=0.5,
                surface_count=2,
                iso=kmean,
                iso_spread=5,
                fig_id=mode,
                iso_limits=(kmin, kmax),
            ):
                with fig.batch_update():
                    figs[fig_id].data[0].surface.count = surface_count
                    figs[fig_id].data[0].opacity = opacity
                    l_bound = max(iso_limits[0], iso - krng * iso_spread / 100)
                    h_bound = min(iso_limits[1], iso + krng * iso_spread / 100)
                    figs[fig_id].data[0].isomin = l_bound
                    figs[fig_id].data[0].isomax = h_bound
                    figs[fig_id].data[0].cmin = l_bound
                    figs[fig_id].data[0].cmax = h_bound

            def buttonfunction(btn):
                figs[int(btn.description[5:])].write_image(
                    f"{path_viz}/u{btn.description[5:]}_3D" + ".png", scale=4
                )

            savebutton = Button(description=f"save {mode}", button_style="primary")
            savebutton.on_click(buttonfunction)

            display(savebutton, fig)

    def u_viz(
        self,
        x,
        y,
        u,
        path_viz,
        modelist,
        bounds,
        dist,
        dist_map,
        vmax=None,
        vmin=None,
        cbar=False,
        cbar_label="value",
    ):
        """
        u_viz 2D visualization of SVD mode shapes

        Args:
            x (series): x coordinates
            y (series): y coordinates
            z (series): z coordinates
            u (dataframe): u matrix from SVD analysis
            path_viz (str): path to store plots in
            modelist (list): mode numbers to visualize
            bounds (list): visualization boundaries and resolution
            dist (float): distance threshold to mask out mode shapes
            dist_map (ndarray): k-d tree distance map for coordinates
        """
        from scipy.interpolate import griddata
        import matplotlib.pyplot as plt
        from mpl_toolkits.axes_grid1 import make_axes_locatable
        import matplotlib.ticker as ticker

        plt.switch_backend("agg")
        plt.rc("font", family=self.font)
        plt.rc("font", size=self.fontsize)

        xmin, xmax, ymin, ymax, res = bounds
        xx, yy = self.make_meshgrid(bounds)

        # for mode in tqdm(modelist, "plotting 2D mode shapes", leave=False):
        @delayed
        def _plot(mode):
            if isinstance(u, dd.DataFrame):
                uu = u.iloc[:, mode].compute()
            elif isinstance(u, pd.DataFrame):
                uu = u.iloc[:, mode]
            else:
                raise ("u must be a pandas or dask dataframe")
            kk = griddata(
                (x, y),
                uu,
                (xx, yy),
                method="linear",
                fill_value=min(abs(uu)),
            )
            if dist is not None:
                # adjust this threshold according to your mesh size
                # this will mask out the parts of visualization for
                # which the distance between points exceeds a certain value
                kk[dist_map >= dist] = np.nan

            fig, ax = plt.subplots(1)
            fig.set_size_inches(self.width, self.height)
            fig.patch.set_facecolor("w")
            ax.set_xlabel("")
            ax.set_ylabel("")
            ax.axes.xaxis.set_visible(False)
            ax.axes.yaxis.set_visible(False)
            ax.set_xlim(xmin, xmax)
            ax.set_ylim(ymin, ymax)
            ax.set_aspect(1)
            ax.set_axisbelow(True)
            ax.grid(alpha=0.5)
            kk[np.isnan(kk)] = np.min(abs(kk))
            if vmax is None:
                contour = ax.contourf(
                    xx,
                    yy,
                    kk,
                    self.contour_levels,
                    cmap=self.cmap,
                    antialiased=True,
                )
            else:
                contour = ax.contourf(
                    xx,
                    yy,
                    kk,
                    self.contour_levels,
                    cmap=self.cmap,
                    antialiased=True,
                    vmax=vmax,
                    vmin=vmin,
                )

            nonlocal cbar
            if cbar:
                divider = make_axes_locatable(ax)
                cax = divider.append_axes("right", size="5%", pad="4%")
                cbar = fig.colorbar(contour, cax=cax)
                cbar.ax.set_xlabel(cbar_label)
                ticklabs = cbar.ax.get_yticklabels()

                for t in ticklabs:
                    t.set_horizontalalignment("right")
                    t.set_x(5.5)

                # Set scientific notation for ticks
                formatter = ticker.ScalarFormatter(useMathText=False)
                formatter.set_scientific(True)
                formatter.set_powerlimits((0, 0))
                cbar.ax.yaxis.set_major_formatter(formatter)
                cbar.ax.yaxis.get_offset_text().set_position((0.5, 0))
                cbar.ax.yaxis.offsetText.set_ha("center")

            for c in contour.collections:
                c.set_edgecolor("face")
            fig.tight_layout()
            for axis in ["top", "bottom", "left", "right"]:
                ax.spines[axis].set_linewidth(self.ax_width)
            fig.savefig(
                f"{path_viz}/u{mode}" + ".png",
                dpi=self.dpi,
                bbox_inches="tight",
            )

            plt.close("all")

        tasks = []
        for mode in tqdm(modelist, "plotting 2D mode shapes", leave=False):
            tasks.append(_plot(mode))
        import dask
        from dask.diagnostics import ProgressBar

        num_threads = len(self.client.nthreads()) * 2
        with ProgressBar():
            dask.compute(tasks, scheduler="threads", num_workers=num_threads)

    def v_viz(self, v, path_viz, modelist, freq_max):
        """
        uv_viz visualize u and v matrix of SVD result. used in svd.viz.

        Args:
            x (series): x coordinates
            y (series): y coordinates
            u (dataframe): u matrix from SVD analysis
            v (dataframe): v matrix from SVD analysis
            path_viz (str): path to save results
            modelist (list): list of modes to visualize
            freq_max (int): maximum frequency to consider is PSD graphs
        """
        from scipy.signal import find_peaks

        import matplotlib.pyplot as plt
        import matplotlib.mlab as mlab

        plt.rc("font", family=self.font)
        plt.rc("font", size=self.fontsize)
        for mode in tqdm(modelist, "plotting mode coefficients", leave=False):
            vv = v.compute().iloc[mode, :]
            tt = np.arange(self.t0, vv.shape[0] * self.dt, self.dt)

            fig, ax = plt.subplots(1)
            fig.set_size_inches(self.width, self.height)
            fig.patch.set_facecolor("w")
            ax.set_xlabel("Time [s]")
            ax.set_ylabel("Coefficient")
            ax.grid(alpha=0.5)
            ax.set_xlim(tt[0], tt[-1])
            ax.plot(tt, vv, self.color, linewidth=self.linewidth)

            fig.tight_layout()
            for axis in ["bottom", "left"]:
                ax.spines[axis].set_linewidth(self.ax_width)
            for axis in ["top", "right"]:
                ax.spines[axis].set_linewidth(0)
            plt.savefig(
                f"{path_viz}/v{mode}" + ".png", dpi=self.dpi, bbox_inches="tight"
            )

            fig, ax = plt.subplots(1)
            fig.set_size_inches(self.width, self.height)
            fig.patch.set_facecolor("w")
            ax.set_xlabel("Frequency [Hz]")
            ax.set_ylabel("Power Spectral Density [db/Hz]")
            ax.grid(alpha=0.5)
            ax.set_xlim(0, freq_max)

            Pxx, freqs = mlab.psd(
                vv,
                Fs=1 / self.dt,
                window=mlab.window_hanning,
                detrend="linear",
            )
            freqs = freqs[np.where(freqs < freq_max)]
            Pxx = Pxx[: len(freqs)]
            dbPxx = 10 * np.log10(Pxx)
            peaks, _ = find_peaks(dbPxx, prominence=3)
            ax.plot(freqs, dbPxx, self.color, linewidth=self.linewidth)
            npeaks = 3
            for n in range(0, min(npeaks, len(peaks))):
                ax.scatter(
                    freqs[peaks[n]],
                    dbPxx[peaks[n]],
                    s=80,
                    facecolors="none",
                    edgecolors="grey",
                )
                acc = 0
                if freq_max < 10:
                    acc = 2
                ax.annotate(
                    f"{freqs[peaks[n]]:0.{acc}f}",
                    xy=(freqs[peaks[n]] + freq_max / 25, dbPxx[peaks[n]] * 0.99),
                )
            fig.tight_layout()
            for axis in ["bottom", "left"]:
                ax.spines[axis].set_linewidth(self.ax_width)
            for axis in ["top", "right"]:
                ax.spines[axis].set_linewidth(0)
            plt.savefig(
                f"{path_viz}/v{mode}_PSD" + ".png", dpi=self.dpi, bbox_inches="tight"
            )
            plt.close("all")

    def s_viz(self, s, path_viz, maxmode=100):
        """
        s_viz visualize s diagonal matrix of SVD result

        Args:
            s (series): eigenvalues of SVD analysis
            path_viz (str): path to save results
            modelist (int, optional): Defaults to 20.
        """
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mtick

        plt.rc("font", family=self.font)
        plt.rc("font", size=self.fontsize)

        fig, ax = plt.subplots(1)
        fig.set_size_inches(self.width, self.height)
        fig.patch.set_facecolor("w")
        ax.set_xlabel("Mode number")
        ax.set_ylabel("Cumulative share of mode energy")
        ax.yaxis.set_major_formatter(mtick.PercentFormatter())
        ax.set_axisbelow(True)
        ax.grid(alpha=0.5, which="both")

        mode_energy = [x**2 for x in s]
        mode_energy = [x / sum(mode_energy) * 100 for x in mode_energy]
        cumsum = np.cumsum(mode_energy)
        s = cumsum[:maxmode]
        ax.set_ylim(s[0] - 10, 100)
        ax.set_xlim(0, maxmode)
        ax.plot(s, self.color, linewidth=self.linewidth)
        fig.tight_layout()
        for axis in ["bottom", "left"]:
            ax.spines[axis].set_linewidth(self.ax_width)
        for axis in ["top", "right"]:
            ax.spines[axis].set_linewidth(0)
        plt.savefig(f"{path_viz}/s" + ".png", dpi=self.dpi, bbox_inches="tight")
        plt.close("all")

    def s_viz_combined_plot(self, s, path_viz):
        """
        s_viz_combined visualize combined s plot

        Args:
            s (pd.Dataframe): eigenvalues of SVD analysis as columns of a dataframe
            path_viz (str): path to save results
        """
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mtick

        plt.switch_backend("agg")
        plt.rc("font", family=self.font)
        plt.rc("font", size=self.fontsize)

        clrs_list = ["k", "b", "g", "r"]
        styl_list = ["-", "--", "-.", ":"]

        fig, ax = plt.subplots(1)
        fig.set_size_inches(self.width, self.height)
        fig.patch.set_facecolor("w")
        ax.set_xlabel("Mode number")
        ax.set_ylabel("Cumulative share of mode energy")
        ax.yaxis.set_major_formatter(mtick.PercentFormatter())
        ax.set_axisbelow(True)
        ax.grid(alpha=0.5, which="both")

        ax.set_ylim(min(s.min(axis=1)) - 10, 100)
        ax.set_xlim(0, s.shape[0])
        for i, var in enumerate(s.columns):
            label = re.sub(r"\[(.*?)\]", "", var)
            label = re.sub(r"\.", " ", label)
            clrr = clrs_list[i // 4]
            styl = styl_list[i % 4]
            ax.plot(s[var], linewidth=self.linewidth, label=label, color=clrr, ls=styl)

        ax.legend(fontsize="small")
        fig.tight_layout()
        for axis in ["bottom", "left"]:
            ax.spines[axis].set_linewidth(self.ax_width)
        for axis in ["top", "right"]:
            ax.spines[axis].set_linewidth(0)
        plt.savefig(
            f"{path_viz}/s_combined" + ".png", dpi=self.dpi, bbox_inches="tight"
        )
        plt.close("all")

    # def multiscale(
    #     self, variables, path_parquet=".data", path_mpod=".mpod", levels=5, freq_max=3000
    # ):
    #     variables = variables if type(variables) is list else [variables]
    #     path_mpod = Path.cwd() / path_mpod

    #     for var in tqdm(variables, "computing mPOD modes and coefficients"):
    #         df = dd.read_parquet(f"{path_parquet}/{var}", engine="pyarrow")
    #         Keep = np.array([1, 1, 1, 1])
    #         Nf = np.array([201, 201, 201, 201])
    #         F_V = [freq_max/levels*i for i in range(1, levels+1)]
    #         F_Bank_r = F_V * 2 * self.dt
    #         M = len(F_Bank_r)
    #         Ex = 103
    #         K = np.dot(df.values.T, df.values)
    #         for m in range(M):
    #             if m<1:


class DMD(POD):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def stack(self, variables, path_parquet=".data", stack_idx=None):
        variables = variables if type(variables) is list else [variables]
        if len(variables) == 1:
            print("only one variable found, stacking not possible")
            return
        if stack_idx is not None:
            vars = [variables[i] for i in stack_idx]
        path_var0 = Path.cwd() / path_parquet / f"{vars[0]}"
        df = dd.read_parquet(path_var0, engine="pyarrow")
        for var in vars[1:]:
            path_var = Path.cwd() / path_parquet / f"{var}"
            df2 = dd.read_parquet(path_var, engine="pyarrow")
            df = dd.concat(
                [df.loc[:: len(variables)], df2.loc[:: len(variables)]], axis=0
            )

        stack_name = "_".join(vars)
        self.stack_name = f"stack_{len(vars)}_{stack_name}"
        df.to_parquet(
            f"{path_parquet}/{self.stack_name}",
            compression="snappy",
            write_metadata_file=True,
        )

    def save_Atilde(
        self,
        variables,
        path_parquet=".data",
        path_pod=".usv",
        path_dmd=".dmd",
        in_memory_df=None,
    ):
        """
        save_Atilde compute Atilde matrix.
        """
        variables = variables if type(variables) is list else [variables]
        v_ = variables.copy()

        if in_memory_df is None:
            v_ = self.overwrite_guard(path_dmd, v_)
        variables = v_

        try:
            shutil.copy(Path.cwd() / path_parquet / "x.pkl", path_dmd)
            shutil.copy(Path.cwd() / path_parquet / "y.pkl", path_dmd)
            shutil.copy(Path.cwd() / path_parquet / "z.pkl", path_dmd)
        except:
            pass

        for var in tqdm(variables, "computing Atilde matrix"):
            path_var = Path.cwd() / path_parquet / f"{var}"
            if in_memory_df is None:
                df = df = dd.read_parquet(path_var, engine="pyarrow").to_dask_array()
            else:
                df = in_memory_df

            # df = df[:, :: self.skip]
            # # df1 = df[:, :-1]
            # df2 = df[:, 1:]
            df2 = self.data_decimate(df, X2=True)
            df2.compute_chunk_sizes()
            # load in u, s and v from path_pod
            path_u = Path.cwd() / path_pod / f"{var}" / "u"
            path_s = Path.cwd() / path_pod / f"{var}" / "s.pkl"
            path_v = Path.cwd() / path_pod / f"{var}" / "v"
            u = dd.read_parquet(path_u, engine="pyarrow")
            s = utils.loadit(path_s)
            v = dd.read_parquet(path_v, engine="pyarrow")
            u = u.to_dask_array()
            u.compute_chunk_sizes()
            v = v.to_dask_array()
            v.compute_chunk_sizes()
            # Atilde = (
            #     u.transpose() @ df2 @ v @ np.diag(s**-1)
            # )
            Atilde = da.matmul(
                da.matmul(da.matmul(u.transpose(), df2), v.transpose()),
                da.diag(s.values**-1),
            )
            utils.saveit(Atilde.compute(), f"{path_dmd}/{var}/Atilde.pkl")

    def get_init(self, path, index=0):
        df = dd.read_parquet(path, engine="pyarrow").to_dask_array()
        return df.T[index]

    def save_modes(
        self,
        variables,
        path_parquet=".data",
        path_dmd=".dmd",
        path_pod=".usv",
        projection_method=True,
        in_memory_df=None,
    ):
        variables = variables if type(variables) is list else [variables]

        for var in tqdm(variables, "computing DMD modes and coefficients"):
            path_Atilde = Path.cwd() / path_dmd / f"{var}" / "Atilde.pkl"
            Atilde = utils.loadit(path_Atilde)
            Lambda, eigvecs = np.linalg.eig(Atilde)
            path_u = Path.cwd() / path_pod / f"{var}" / "u"
            path_v = Path.cwd() / path_pod / f"{var}" / "v"
            u = dd.read_parquet(path_u, engine="pyarrow")
            columns = u.columns
            v = dd.read_parquet(path_v, engine="pyarrow")
            u = u.to_dask_array()
            u.compute_chunk_sizes()
            v = v.to_dask_array()
            v.compute_chunk_sizes()

            path_var = Path.cwd() / path_parquet / f"{var}"

            if in_memory_df is None:
                df = dd.read_parquet(path_var, engine="pyarrow").to_dask_array()
            else:
                df = in_memory_df

            # Two methods to compute phi
            if projection_method:
                phi = da.matmul(u, eigvecs)
            else:
                df2 = self.data_decimate(df, X2=True)
                path_s = Path.cwd() / path_pod / f"{var}" / "s.pkl"
                s = utils.loadit(path_s)
                phi = da.matmul(
                    da.matmul(da.matmul(df2, v.transpose()), da.diag(s.values**-1)),
                    eigvecs,
                )

            # Convert the complex numbers to real and imaginary parts
            phi_real = phi.real.to_dask_dataframe(columns=columns)
            phi_imag = phi.imag.to_dask_dataframe(columns=columns)

            # Write the real and imaginary parts to separate Parquet files
            dd.to_parquet(
                phi_real,
                f"{path_dmd}/{var}/modes_real",
                compression="snappy",
                write_metadata_file=True,
            )
            dd.to_parquet(
                phi_imag,
                f"{path_dmd}/{var}/modes_imag",
                compression="snappy",
                write_metadata_file=True,
            )

            # df.compute_chunk_sizes()
            init = df[:, 0].compute()
            # b = np.linalg.pinv(phi) @ init
            b = np.linalg.lstsq(phi.compute(), init, rcond=None)[0]
            utils.saveit(b, f"{path_dmd}/{var}/b.pkl")
            utils.saveit(Lambda, f"{path_dmd}/{var}/lambda.pkl")

    def save_prediction(
        self,
        variables,
        path_dmd=".dmd",
        end=None,
        frame_skip=1,
    ):
        variables = variables if type(variables) is list else [variables]

        for var in tqdm(variables, "predicting variables"):
            # path_frames = Path.cwd() / f"{var}" / "frames"
            path_dmd_values = Path.cwd() / path_dmd / f"{var}"

            # init = self.get_init(f"{path_parquet}/{var}")
            # init.compute_chunk_sizes()

            # Atilde = dd.read_parquet(path_dmd_values / "Atilde", engine="pyarrow")
            b = utils.loadit(path_dmd_values / "b.pkl")
            eigs = utils.loadit(path_dmd_values / "lambda.pkl")
            omega = np.log(eigs) / self.dt
            # Read the real and imaginary parts from the Parquet files
            phi_real = dd.read_parquet(f"{path_dmd}/{var}/modes_real")
            phi_imag = dd.read_parquet(f"{path_dmd}/{var}/modes_imag")

            # Combine the real and imaginary parts to form complex numbers
            phi = phi_real + 1j * phi_imag
            # phi = dd.read_parquet(path_dmd_values / "modes", engine="pyarrow")
            phi = phi.to_dask_array(lengths=True)

            # dynamics = []
            if end is None:
                end = phi.shape[1]
            # for frame in range(start, end, frame_skip):
            #     # prediction_list.append(
            #     #     # da.real(phi.dot(b * da.exp(omega * (start + self.dt * frame))))
            #     #     da.matmul(phi, b * da.exp(omega * (start + self.dt * frame))).real
            #     # )
            #     td = b * np.exp(omega * (start + self.dt * frame))
            #     dynamics.append(td)

            # # save dynamics into a dataframe
            time = np.arange(0, end, frame_skip) * self.dt
            dynamics = np.zeros((len(b), len(time)), dtype=complex)
            for i, t in enumerate(time):
                dynamics[:, i] = b * np.exp(omega * t)

            prediction_da = da.matmul(phi, dynamics).real
            prediction_df = dd.from_dask_array(prediction_da)
            prediction_df.columns = prediction_df.columns.astype(str)
            prediction_df.repartition(npartitions=20)
            prediction_df.to_parquet(
                f"{path_dmd_values}/prediction",
                compression="snappy",
                write_metadata_file=True,
            )

    def describe_parquet(
        self,
        variables,
        path_data=".data",
        folder_name="",
        path_data2=None,
        folder_name2=None,
    ):
        variables = variables if type(variables) is list else [variables]
        for var in tqdm(variables, "describing variables"):
            data = dd.read_parquet(f"{path_data}/{var}/{folder_name}", engine="pyarrow")

            if folder_name2 is not None:
                if path_data2 is None:
                    path_data2 = path_data
                data2 = dd.read_parquet(
                    f"{path_data2}/{var}/{folder_name2}", engine="pyarrow"
                )
                data = data.map_partitions(lambda a, b: a - b, data2)
            data = data.compute()

            def remove_outliers(df):
                df = df.transpose()
                mask = pd.Series(data=True, index=df.index)
                for index in df.index:
                    Q1 = df.loc[index].quantile(0.25)
                    Q3 = df.loc[index].quantile(0.75)
                    IQR = Q3 - Q1
                    lower_bound = Q1 - 1.5 * IQR
                    upper_bound = Q3 + 1.5 * IQR
                    mask = (df.loc[index] < lower_bound) | (df.loc[index] > upper_bound)
                    df.loc[index, mask] = np.nan
                df = df.transpose()
                return df

            # print(df.mean(axis=1).describe())
            data = remove_outliers(data)
            print(data.mean(axis=0).describe())
            if folder_name2 is None:
                with open(f"{path_data}/{var}/{folder_name}/description.txt", "w") as f:
                    f.write(data.mean(axis=0).describe().to_string())
            else:
                with open(
                    f"{path_data}/{var}/{folder_name}/description_diff.txt", "w"
                ) as f:
                    f.write(data.mean(axis=0).describe().to_string())

    def viz_error(
        self, variables, path_data=".data1", path_dmd=".data2", path_viz=".viz"
    ):
        variables = variables if type(variables) is list else [variables]
        for var in tqdm(variables, "prediction error calculation"):

            utils.ensure_dir(f"{path_viz}/{var}")
            path_pq1 = Path.cwd() / path_data / f"{var}"
            path_pq2 = Path.cwd() / path_dmd / f"{var}" / "prediction"
            df1 = dd.read_parquet(path_pq1, engine="pyarrow")
            df2 = dd.read_parquet(path_pq2, engine="pyarrow")

            # get minimum columns of the two dataframes
            min_cols = min(df1.shape[1], df2.shape[1])
            df1 = df1.iloc[:, :min_cols]
            df2 = df2.iloc[:, :min_cols]

            df1 = df1.to_dask_array()
            df2 = df2.to_dask_array()

            if var.startswith("stack"):
                varnum = int(var.split("_")[1])
                idx_end = df2.shape[1] // varnum
                df2[:, :idx_end]

            # make df2 same shape as df1
            # Root Mean Square Error (RMSE)
            # rmse = da.mean((df1 - df2) ** 2, axis=0).compute()**0.5

            # # Mean Squared Logarithmic Error (MSLE)
            # msle = da.mean((da.log(df1 + 3e5) - da.log(df2 + 3e5)) ** 2, axis=0).compute()

            # # Mean Absolute Percentage Error (MAPE)
            # mape = da.mean(da.abs((df1 - df2) / df1), axis=0).compute() * 100

            # Mean Absolute Error (MAE)
            mae = da.mean(da.abs(df1 - df2), axis=0).compute()
            error = mae
            utils.saveit(error, f"{path_dmd}/{var}/mae.pkl")

            import matplotlib.pyplot as plt
            import matplotlib.ticker as mtick

            plt.rc("font", family=self.font)
            plt.rc("font", size=self.fontsize)
            plt.switch_backend("agg")
            fig, ax = plt.subplots(1)
            fig.set_size_inches(self.width, self.height)
            fig.patch.set_facecolor("w")
            ax.set_xlabel("snapshots")
            ax.set_ylabel("MAE")
            ax.set_yscale("log")
            # ax.yaxis.set_major_formatter(mtick.PercentFormatter())
            ax.set_axisbelow(True)
            ax.grid(alpha=0.5, which="both")
            ax.grid(alpha=0.3, which="minor", linewidth=self.linewidth * 0.75)
            ax.yaxis.set_minor_locator(mtick.LogLocator(numticks=999, subs="auto"))

            # ax.set_ylim(
            #     rmse.min() - 10, rmse[int(self.data_cutoff * rmse.shape[0] / 100)] + 40
            # )
            # ax.set_ylim(
            #     -2,2
            # )
            ax.set_xlim(1, error.shape[0])
            ax.axvline(
                self.data_cutoff * error.shape[0] / 100,
                color="grey",
                linestyle="--",
                linewidth=1,
            )
            ax.plot(
                error[1:],
                self.color,
                linewidth=self.linewidth,
            )
            fig.tight_layout()
            for axis in ["bottom", "left"]:
                ax.spines[axis].set_linewidth(self.ax_width)
            for axis in ["top", "right"]:
                ax.spines[axis].set_linewidth(0)
            plt.savefig(
                f"{path_viz}/{var}/mae" + ".png", dpi=self.dpi, bbox_inches="tight"
            )
            plt.close("all")

    def viz_error_combined(self, variables, path_dmd=".data2", path_viz=".viz"):
        variables = variables if type(variables) is list else [variables]
        utils.ensure_dir(path_viz)

        error_combined = pd.DataFrame(columns=variables)
        path_error = Path.cwd() / path_dmd / f"{variables[0]}" / "mae.pkl"
        _data = utils.loadit(path_error)
        cutoff_index = self.data_cutoff * _data.shape[0] // 100
        for var in variables:
            path_error = Path.cwd() / path_dmd / f"{var}" / "mae.pkl"
            error_combined[var] = utils.loadit(path_error)

        import matplotlib.pyplot as plt
        import matplotlib.ticker as mtick

        plt.rc("font", family=self.font)
        plt.rc("font", size=self.fontsize)

        plt.switch_backend("agg")
        clrs_list = ["k", "b", "g", "r"]
        styl_list = ["-", "--", "-.", ":"]

        fig, ax = plt.subplots(1)
        fig.set_size_inches(self.width, self.height)
        fig.patch.set_facecolor("w")
        ax.set_xlabel("snapshots")
        ax.set_ylabel("MAE")
        ax.set_yscale("log")
        ax.set_axisbelow(True)

        ax.grid(alpha=0.5, which="both")
        ax.grid(alpha=0.3, which="minor", linewidth=self.linewidth * 0.75)
        ax.yaxis.set_minor_locator(mtick.LogLocator(numticks=999, subs="auto"))

        ax.set_xlim(0, error_combined.shape[0])
        yspan = error_combined.max().max() - error_combined.min().min()
        padding = 0.1 * yspan
        ax.set_ylim(
            max(error_combined.min().min(), error_combined.min().min() - padding),
            error_combined.max().max() + padding,
        )
        ax.axvline(
            self.data_cutoff * error_combined.shape[0] // 100 - 1,
            color="grey",
            linestyle="--",
            linewidth=1,
        )

        for i, var in enumerate(error_combined.columns):
            label = re.sub(r"\[(.*?)\]", "", var)  # remove units between brackets
            label = re.sub(r"\.", " ", label)  # remove dots
            if label.startswith("stack"):
                first = f"{label.split('_')[2]}".strip()
                rest = [x.strip() for x in label.split("_")[3:]]
                label = f"{first} w/ {', '.join(rest)}"
                label = label.replace("Velocity u, Velocity v, Velocity w", "Velocity")
            clrr = clrs_list[i // len(clrs_list)]
            styl = styl_list[i % len(styl_list)]
            ax.plot(
                error_combined[var],
                linewidth=self.linewidth,
                label=label,
                color=clrr,
                ls=styl,
            )

        ax.legend(fontsize="small")

        fig.tight_layout()
        for axis in ["bottom", "left"]:
            ax.spines[axis].set_linewidth(self.ax_width)
        for axis in ["top", "right"]:
            ax.spines[axis].set_linewidth(0)

        plt.savefig(
            f"{path_viz}/mae_combined_full" + ".png", dpi=self.dpi, bbox_inches="tight"
        )

        ax.set_xlim(cutoff_index, error_combined.shape[0])
        yspan = (
            error_combined.iloc[cutoff_index:, :].max().max()
            - error_combined.iloc[cutoff_index:, :].min().min()
        )
        padding = 0.1 * yspan
        ax.set_ylim(
            max(
                error_combined.iloc[cutoff_index:, :].min().min(),
                error_combined.iloc[cutoff_index:, :].min().min() - padding,
            ),
            error_combined.iloc[cutoff_index:, :].max().max() + padding,
        )
        plt.savefig(
            f"{path_viz}/mae_combined_post" + ".png", dpi=self.dpi, bbox_inches="tight"
        )

        plt.close("all")

    def viz_parquet(
        self,
        variables,
        num_frames=None,
        path_data=".dmd",
        folder_name="",
        path_data2=None,
        folder_name2=None,
        path_viz=".viz",
        bounds="auto",
        coordinates="2D",
        dist=None,
        vmax="auto",
        vmin="auto",
    ):
        variables = variables if type(variables) is list else [variables]

        variables = self.overwrite_guard(path_viz, variables)
        for var in tqdm(variables, "predicting variables"):
            utils.ensure_dir(f"{path_viz}/{var}")

            path = Path.cwd() / path_data / f"{var}"
            data = dd.read_parquet(f"{path}/{folder_name}", engine="pyarrow")

            self.make_dim(coordinates)

            if self.dim == "xy":
                path_x = f"{path_data}/x.pkl"
                path_y = f"{path_data}/y.pkl"
                x = utils.loadit(path_x)
                y = utils.loadit(path_y)

                if bounds == "auto":
                    bounds = self.make_bounds([x, y])

                if dist:
                    dist_map = self.dist_map(x, y, bounds)

            # if a second path is provided, visualize the difference
            if folder_name2 is not None:
                if path_data2 is None:
                    path_data2 = path_data
                path2 = Path.cwd() / path_data2 / f"{var}"
                data2 = dd.read_parquet(f"{path2}/{folder_name2}", engine="pyarrow")
                data = data.map_partitions(lambda a, b: a - b, data2)

            # visualize data snapshots
            if num_frames is None:
                modelist = range(0, data.shape[1])
            else:
                modelist = np.linspace(0, data.shape[1] - 1, num_frames).astype(int)
            vmax_val = data.iloc[:, -1].max().compute() if vmax == "auto" else vmax
            vmin_val = data.iloc[:, -1].min().compute() if vmin == "auto" else vmin
            match = re.search(r"\[(.*?)\]", var)
            if match:
                cbar_label = match.group(1)
            else:
                cbar_label = " "
            self.u_viz(
                x,
                y,
                data.compute(),
                f"{path_viz}/{var}",
                modelist,
                bounds,
                dist,
                dist_map,
                vmax=vmax_val,
                vmin=vmin_val,
                cbar=True,
                cbar_label=cbar_label,
            )
            self.animate(
                Path.cwd() / f"{path_viz}/{var}",
            )

    def animate(self, path_frames):
        import imageio

        file_pattern = re.compile(r".*?(\d+).*?")

        def get_order(file):
            match = file_pattern.match(Path(file).name)
            if not match:
                return np.inf
            return int(match.groups()[0])

        with imageio.get_writer(
            path_frames / "animation.mp4", quality=9, fps=24
        ) as writer:
            for png_file in sorted(path_frames.glob("*.png"), key=get_order):
                image = imageio.imread(png_file)
                writer.append_data(image)
            writer.close()

    def viz_eigs_circle(
        self, variables, path_dmd=".dmd", path_viz=".viz", maxmode=None
    ):
        variables = variables if type(variables) is list else [variables]
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mtick
        from matplotlib.colors import Normalize

        plt.switch_backend("agg")
        plt.rc("font", family=self.font)
        plt.rc("font", size=self.fontsize)
        plt.rc("text", usetex=True)
        for var in tqdm(variables, "plotting DMD modes eigenvalues"):
            utils.ensure_dir(f"{path_viz}/{var}")
            eigs = utils.loadit(f"{path_dmd}/{var}/lambda.pkl")
            if maxmode is None:
                maxmode = eigs.shape[0]
            eigs = eigs[:maxmode]

            fig, ax = plt.subplots(1)
            fig.set_size_inches(self.width, self.height)
            fig.patch.set_facecolor("w")
            ax.set_xlabel("$\\Re(\\lambda_i$)")
            ax.set_ylabel("$\\Im(\\lambda_i$)")
            ax.set_axisbelow(True)
            ax.grid(alpha=0.5, which="both")

            ax.set_ylim(-1.05, 1.05)
            ax.set_xlim(-1.05, 1.05)
            ax.set_aspect(1)
            circ = plt.Circle((0, 0), radius=1, edgecolor="black", facecolor="None")
            ax.add_patch(circ)
            ax.scatter(
                np.real(eigs),
                np.imag(eigs),
                s=7,
                # c=np.abs(eigs),
                c="black",
                edgecolors="none",
            )

            fig.tight_layout()
            for axis in ["bottom", "left"]:
                ax.spines[axis].set_linewidth(self.ax_width)
            for axis in ["top", "right"]:
                ax.spines[axis].set_linewidth(0)
            plt.show()
            plt.savefig(
                f"{path_viz}/{var}/eig_z" + ".png",
                dpi=self.dpi,
                bbox_inches="tight",
            )
            plt.close("all")

    def viz_eigs_spectrum(
        self,
        variables,
        path_dmd=".dmd",
        path_pod=".pod",
        path_viz=".viz",
        maxmode=None,
        freq_max=3000,
    ):
        variables = variables if type(variables) is list else [variables]
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mtick
        from matplotlib.colors import Normalize
        import matplotlib.mlab as mlab
        from scipy.signal import find_peaks

        plt.switch_backend("agg")
        plt.rc("font", family=self.font)
        plt.rc("font", size=self.fontsize)
        for var in tqdm(variables, "plotting DMD modes eigenvalues PSD"):
            utils.ensure_dir(f"{path_viz}/{var}")
            eigs = utils.loadit(f"{path_dmd}/{var}/lambda.pkl")
            b = utils.loadit(f"{path_dmd}/{var}/b.pkl")
            s = utils.loadit(f"{path_pod}/{var}/s.pkl")

            fig, ax = plt.subplots(1)
            fig.set_size_inches(self.width, self.height)
            fig.patch.set_facecolor("w")
            ax.set_xlabel("Frequency [Hz]")
            ax.set_ylabel("Power Spectrum [$|$b$|$/Hz]")
            ax.grid(alpha=0.5)
            ax.set_xlim(0, freq_max)
            ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))

            freqs = np.imag(np.log(eigs) / self.dt / 2 / np.pi)  # frequency in Hz
            idx = np.argsort(freqs)
            Pxx = np.abs(b) * 2 / np.sqrt(s.values)  # scaled magnitude according to s
            freqs = freqs[idx]
            Pxx = Pxx[idx]
            Pxx = Pxx[(0 < freqs) & (freqs < freq_max)]
            freqs = freqs[(0 < freqs) & (freqs < freq_max)]
            maxval = np.max(Pxx)
            peaks, _ = find_peaks(Pxx, prominence=maxval / 15, distance=50)
            ax.plot(freqs, Pxx, self.color, linewidth=self.linewidth)
            npeaks = 4
            for n in range(0, min(npeaks, len(peaks))):
                ax.scatter(
                    freqs[peaks[n]],
                    Pxx[peaks[n]],
                    s=80,
                    facecolors="none",
                    edgecolors="grey",
                )
                acc = 0
                if freq_max < 10:
                    acc = 2
                ax.annotate(
                    f"{freqs[peaks[n]]:0.{acc}f}",
                    xy=(
                        freqs[peaks[n]] + freq_max / 25,
                        Pxx[peaks[n]] * 0.99,
                    ),
                )
            fig.tight_layout()
            for axis in ["bottom", "left"]:
                ax.spines[axis].set_linewidth(self.ax_width)
            for axis in ["top", "right"]:
                ax.spines[axis].set_linewidth(0)
            plt.savefig(
                f"{path_viz}/{var}/eig_PS" + ".png",
                dpi=self.dpi,
                bbox_inches="tight",
            )
            plt.close("all")

    def viz_eigs_spectrum_combined(
        self,
        variables,
        path_dmd=".dmd",
        path_pod=".pod",
        path_viz=".viz",
        maxmode=None,
        freq_max=3000,
    ):
        variables = variables if type(variables) is list else [variables]
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mtick
        from matplotlib.colors import Normalize
        import matplotlib.mlab as mlab
        from scipy.signal import find_peaks
        from scipy.signal import convolve

        plt.switch_backend("agg")
        plt.rc("font", family=self.font)
        plt.rc("font", size=self.fontsize)

        def gaussian_kernel(x, sigma):
            return np.exp(-0.5 * (x / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi))

        eigs_combined = 0
        df_combined = pd.DataFrame()

        for var in tqdm(variables, "plotting DMD modes eigenvalues PSD"):
            utils.ensure_dir(f"{path_viz}/{var}")
            _eig = utils.loadit(f"{path_dmd}/{var}/lambda.pkl")
            _b = utils.loadit(f"{path_dmd}/{var}/b.pkl")
            _s = utils.loadit(f"{path_pod}/{var}/s.pkl")
            eigs_combined += _eig
            df_combined[var] = (
                np.abs(_b) * 2 / np.sqrt(_s.values)
            )  # scaled magnitude according to s

        df_combined["freqs"] = np.imag(
            np.log(eigs_combined) / self.dt / 2 / np.pi
        )  # frequency in Hz
        df_combined = df_combined.sort_values(by="freqs")
        df_combined = df_combined[
            (0 < df_combined["freqs"]) & (df_combined["freqs"] < freq_max)
        ]
        sigma = 1.0
        kernel_size = 25  # Define the size of the kernel
        x = np.linspace(-3 * sigma, 3 * sigma, kernel_size)
        kernel = gaussian_kernel(x, sigma)

        for col in df_combined.columns:
            if col != "freqs":
                df_combined[col] = convolve(df_combined[col], kernel, mode="same")

        freqs = df_combined["freqs"].values
        df_combined.drop(columns=["freqs"], inplace=True)
        Pxx = df_combined.prod(axis=1).values

        fig, ax = plt.subplots(1)
        fig.set_size_inches(self.width, self.height)
        fig.patch.set_facecolor("w")
        ax.set_xlabel("Frequency [Hz]")
        ax.set_ylabel("Power Spectrum [$|$b$|$/Hz]")
        ax.grid(alpha=0.5)
        ax.set_xlim(0, freq_max)
        ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
        # ax.set_yscale("log")

        maxval = np.max(Pxx)
        peaks, _ = find_peaks(Pxx, prominence=maxval / 2, distance=50)
        ax.plot(freqs, Pxx, self.color, linewidth=self.linewidth)

        npeaks = 1
        for n in range(0, min(npeaks, len(peaks))):
            ax.scatter(
                freqs[peaks[n]],
                Pxx[peaks[n]],
                s=80,
                facecolors="none",
                edgecolors="grey",
            )
            acc = 0
            if freq_max < 10:
                acc = 2
            ax.annotate(
                f"{freqs[peaks[n]]:0.{acc}f}",
                xy=(
                    freqs[peaks[n]] + freq_max / 25,
                    Pxx[peaks[n]] * 0.99,
                ),
            )
        fig.tight_layout()
        for axis in ["bottom", "left"]:
            ax.spines[axis].set_linewidth(self.ax_width)
        for axis in ["top", "right"]:
            ax.spines[axis].set_linewidth(0)
        plt.savefig(
            f"{path_viz}/eig_PS_combined" + ".png",
            dpi=self.dpi,
            bbox_inches="tight",
        )
        plt.close("all")

    def viz_modes(
        self,
        variables,
        modelist=None,
        freqlist=None,
        coordinates="2D",
        path_dmd=".dmd",
        path_viz=".viz",
        bounds="auto",
        dist=False,
    ):
        variables = variables if type(variables) is list else [variables]

        if modelist is not None:
            modelist = modelist if type(modelist) is list else list(modelist)
        if freqlist is not None:
            freqlist = freqlist if type(freqlist) is list else list(freqlist)
            if modelist is not None:
                print("please either provide modelist or freqlist")
                return

        self.make_dim(coordinates)

        for var in tqdm(variables, "analyzing variables"):
            utils.ensure_dir(f"{path_viz}/{var}")

            eigs = utils.loadit(f"{path_dmd}/{var}/lambda.pkl")
            freqs = np.imag(np.log(eigs) / self.dt / 2 / np.pi)

            if freqlist is not None:
                modelist = []
                for f in freqlist:
                    diffs = abs(freqs - f)
                    sorted_indices = np.argsort(diffs)
                    closest_indices = sorted_indices[:3]
                    for idx in closest_indices:
                        modelist.append(idx)

            freq_lookup = {idx: freqs[idx] for idx in modelist}

            if self.dim == "xy":
                path_x = f"{path_dmd}/x.pkl"
                path_y = f"{path_dmd}/y.pkl"
                x = utils.loadit(path_x)
                y = utils.loadit(path_y)

                if bounds == "auto":
                    bounds = self.make_bounds([x, y])

                if dist:
                    dist_map = self.dist_map(x, y, bounds)

            from scipy.interpolate import griddata
            import matplotlib.pyplot as plt

            plt.switch_backend("agg")
            plt.rc("font", family=self.font)
            plt.rc("font", size=self.fontsize)

            xmin, xmax, ymin, ymax, res = bounds
            xx, yy = self.make_meshgrid(bounds)

            for mode in tqdm(modelist, "plotting 2D mode shapes", leave=False):
                dmd_mode = dd.read_parquet(
                    f"{path_dmd}/{var}/modes_real", engine="pyarrow"
                )
                dm = dmd_mode.iloc[:, mode].compute()
                kk = griddata(
                    (x, y),
                    dm,
                    (xx, yy),
                    method="linear",
                    fill_value=min(abs(dm)),
                )
                if dist:
                    # adjust this threshold according to your mesh size
                    # this will mask out the parts of visualization for
                    # which the distance between points exceeds a certain value
                    kk[dist_map >= dist] = np.nan

                fig, ax = plt.subplots(1)
                fig.set_size_inches(self.width, self.height)
                fig.patch.set_facecolor("w")
                ax.set_xlabel("")
                ax.set_ylabel("")
                ax.axes.xaxis.set_visible(False)
                ax.axes.yaxis.set_visible(False)
                ax.set_xlim(xmin, xmax)
                ax.set_ylim(ymin, ymax)
                ax.set_aspect(1)
                ax.set_axisbelow(True)
                ax.grid(alpha=0.5)
                kk[np.isnan(kk)] = np.min(abs(kk))

                contour = ax.contourf(
                    xx,
                    yy,
                    kk,
                    self.contour_levels,
                    cmap=self.cmap,
                    antialiased=True,
                    extend="both",
                )
                for c in contour.collections:
                    c.set_edgecolor("face")
                fig.tight_layout()
                for axis in ["top", "bottom", "left", "right"]:
                    ax.spines[axis].set_linewidth(self.ax_width)
                plt.savefig(
                    f"{path_viz}/{var}/mode_{mode}_freq_{freq_lookup[mode]}" + ".png",
                    dpi=self.dpi,
                    bbox_inches="tight",
                )
                plt.close("all")

    def multires(
        self, variables, path_parquet=".data", path_mrdmd=".mrdmd", levels=4, end=None
    ):
        variables = variables if type(variables) is list else [variables]
        path_mrdmd = Path.cwd() / path_mrdmd

        for var in tqdm(variables, "computing mrDMD modes and coefficients"):
            for level in range(levels):
                for i in range(2**level):
                    utils.ensure_dir(path_mrdmd / f"level_{level}/{i}")
            df = dd.read_parquet(f"{path_parquet}/{var}", engine="pyarrow")
            df = df.iloc[:, : end - end % 2**levels]
            if end is None:
                end = df.shape[1].compute()
            for level in range(0, levels):
                if level > 0:
                    df = dd.read_parquet(
                        path_mrdmd / f"level_{level-1}/{var}/level_prediction",
                        engine="pyarrow",
                    )
                slice_size = df.shape[1] // 2**level
                dfs = [
                    df.iloc[:, i * slice_size : (i + 1) * slice_size]
                    for i in range(2**level)
                ]
                time = np.arange(0, end, 1) * self.dt
                for i in range(0, 2**level):
                    df_i = dfs[i]
                    path_pod = path_mrdmd / f"level_{level}/{i}"
                    path_dmd = path_mrdmd / f"level_{level}/{i}"
                    self.svd_save_usv(
                        variables,
                        path_parquet=path_parquet,
                        path_pod=path_pod,
                        dmd_X1=True,
                        in_memory_df=df_i,
                    )
                    self.save_Atilde(
                        variables,
                        path_parquet=path_parquet,
                        path_pod=path_pod,
                        path_dmd=path_dmd,
                        in_memory_df=df_i.to_dask_array(lengths=True),
                    )
                    self.save_modes(
                        variables,
                        path_parquet=path_parquet,
                        path_dmd=path_dmd,
                        path_pod=path_pod,
                        projection_method=True,
                        in_memory_df=df_i.to_dask_array(lengths=True),
                    )
                    eigs = utils.loadit(path_dmd / f"{var}/lambda.pkl")
                    omega = np.log(eigs) / self.dt
                    rho = 1 / (self.dt * slice_size)
                    slow_mask = np.where(np.abs(omega) < rho * 2 * np.pi)[0]
                    b = utils.loadit(path_dmd / f"{var}/b.pkl")
                    utils.saveit(b[slow_mask], f"{path_dmd}/{var}/b.pkl")
                    utils.saveit(eigs[slow_mask], f"{path_dmd}/{var}/lambda.pkl")
                    phi_real = dd.read_parquet(
                        path_dmd / f"{var}/modes_real", engine="pyarrow"
                    )
                    phi_imag = dd.read_parquet(
                        path_dmd / f"{var}/modes_imag", engine="pyarrow"
                    )
                    phi_real = phi_real.iloc[:, slow_mask]
                    phi_imag = phi_imag.iloc[:, slow_mask]
                    phi_real = phi_real.reset_index(drop=True)
                    phi_imag = phi_imag.reset_index(drop=True)
                    phi_real.to_parquet(
                        path_dmd / f"{var}/modes_real_2", compression="snappy"
                    )
                    phi_imag.to_parquet(
                        path_dmd / f"{var}/modes_imag_2", compression="snappy"
                    )
                    shutil.rmtree(path_dmd / f"{var}/modes_real")
                    shutil.rmtree(path_dmd / f"{var}/modes_imag")
                    shutil.move(
                        path_dmd / f"{var}/modes_real_2",
                        path_dmd / f"{var}/modes_real",
                    )
                    shutil.move(
                        path_dmd / f"{var}/modes_imag_2",
                        path_dmd / f"{var}/modes_imag",
                    )
                    self.save_prediction(variables, path_dmd=path_dmd, end=slice_size)

                df_new = dd.concat(
                    [
                        dd.read_parquet(
                            path_mrdmd / f"level_{level}/{i}/{var}/prediction"
                        )
                        for i in range(2**level)
                    ],
                    axis=1,
                )
                df_new.columns = df.columns
                df -= df_new
                df.to_parquet(
                    path_mrdmd / f"level_{level}/{var}/level_prediction",
                    compression="snappy",
                    write_metadata_file=True,
                )
                # del df_new, df_i, df, dfs, time, rho

    def multires_predict(self, variables, path_mrdmd=".mrdmd", end=None):
        variables = variables if type(variables) is list else [variables]
        for var in variables:
            path_mrdmd = Path.cwd() / path_mrdmd

            # discover the number of levels
            levels = 0
            while True:
                if not (path_mrdmd / f"level_{levels}").exists():
                    break
                levels += 1
            print(f"Number of levels: {levels}")
            predictions = []
            for level in range(levels):
                prediction = dd.read_parquet(
                    path_mrdmd / f"level_{level}/{var}/level_prediction"
                )
                predictions.append(prediction)

            prediction_df = predictions[0]
            for i in range(1, len(predictions)):
                prediction_df += predictions[i]

            for level in range(levels):
                shutil.copy(
                    path_mrdmd / f"level_0/0/x.pkl", path_mrdmd / f"level_{level}"
                )
                shutil.copy(
                    path_mrdmd / f"level_0/0/y.pkl", path_mrdmd / f"level_{level}"
                )

            # prediction_df = dd.from_dask_array(df_sum)
            # prediction_df.columns = prediction_df.columns.astype(str)
            prediction_df.repartition(npartitions=20)
            prediction_df.to_parquet(
                path_mrdmd / f"{var}/prediction",
                compression="snappy",
                write_metadata_file=True,
            )

    def viz_multires(
        self,
        variables,
        num_frames=0,
        path_mrdmd=".mrdmd",
        path_viz=".viz",
        bounds="auto",
        coordinates="2D",
        dist=None,
        vmax="auto",
        vmin="auto",
    ):
        variables = variables if type(variables) is list else [variables]
        path_mrdmd = Path.cwd() / path_mrdmd
        path_viz = Path.cwd() / path_viz

        levels = 0
        while True:
            if not (path_mrdmd / f"level_{levels}").exists():
                break
            levels += 1
        print(f"Number of levels: {levels}")

        for var in variables:
            for level in range(levels):
                self.viz_parquet(
                    variables,
                    num_frames=num_frames,
                    path_data=path_mrdmd / f"level_{level}",
                    folder_name="",
                    folder_name2=None,
                    path_viz=path_viz / f"level_{level}",
                    bounds=bounds,
                    coordinates=coordinates,
                    dist=dist,
                    vmax=vmax,
                    vmin=vmin,
                )

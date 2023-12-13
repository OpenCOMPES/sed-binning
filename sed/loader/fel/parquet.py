"""
The ParquetHandler class allows for saving and reading Dask DataFrames to/from Parquet files.
It also provides methods for initializing paths, deleting Parquet files, and reading Parquet
files into a Dask DataFrame.

Typical usage example:

    parquet_handler = ParquetHandler(parquet_names='data', folder=Path('/path/to/folder'))
    parquet_handler.save_parquet(df) # df is a uncomputed Dask DataFrame
    data = parquet_handler.read_parquet()
"""
from __future__ import annotations

from pathlib import Path

import dask.dataframe as ddf


class ParquetHandler:
    """
    A handler for saving and reading Dask DataFrames to/from Parquet files.

    Args:
        parquet_names Union[str, List[str]]: The base name of the Parquet files.
        folder (Path): The directory where the Parquet file will be stored.
        subfolder (str): Optional subfolder within the main folder.
        prefix (str): Optional prefix for the Parquet file name.
        suffix (str): Optional suffix for the Parquet file name.
        parquet_path (Path): Optional custom path for the Parquet file.
    """

    def __init__(
        self,
        parquet_names: str | list[str] = None,
        folder: Path = None,
        subfolder: str = None,
        prefix: str = None,
        suffix: str = None,
        extension: str = "parquet",
        parquet_paths: Path = None,
    ):

        self.parquet_paths: list[Path] = None

        if isinstance(parquet_names, str):
            parquet_names = [parquet_names]

        if not folder and not parquet_paths:
            raise ValueError("Please provide folder or parquet_paths.")
        if folder and not parquet_names:
            raise ValueError("With folder, please provide parquet_names.")

        if parquet_paths:
            self.parquet_paths = (
                parquet_paths if isinstance(parquet_paths, list) else [parquet_paths]
            )
        else:
            self._initialize_paths(parquet_names, folder, subfolder, prefix, suffix, extension)

    def _initialize_paths(
        self,
        parquet_names: list[str],
        folder: Path,
        subfolder: str = "",
        prefix: str = "",
        suffix: str = "",
        extension: str = "",
    ) -> None:
        """
        Create the directory for the Parquet file.
        """
        # Create the full path for the Parquet file
        parquet_dir = folder.joinpath(subfolder)
        parquet_dir.mkdir(parents=True, exist_ok=True)

        self.parquet_paths = [
            parquet_dir.joinpath(Path(f"{prefix}{name}{suffix}.{extension}"))
            for name in parquet_names
        ]

    def save_parquet(
        self,
        dfs: list[ddf.DataFrame],
        drop_index=False,
    ) -> None:
        """
        Save the DataFrame to a Parquet file.

        Args:
            dfs (DataFrame | ddf.DataFrame): The pandas or Dask Dataframe to be saved.
        """
        # Compute the Dask DataFrame, reset the index, and save to Parquet
        for df, parquet_path in zip(dfs, self.parquet_paths):
            df.compute().reset_index(drop=drop_index).to_parquet(parquet_path)

    def read_parquet(self) -> ddf.DataFrame:
        """
        Read a Dask DataFrame from the Parquet file.

        Returns:
            ddf.DataFrame: The Dask DataFrame read from the Parquet file.

        Raises:
            FileNotFoundError: If the Parquet file does not exist.
        """
        try:
            return ddf.read_parquet(self.parquet_paths, calculate_divisions=True)
        except Exception as exc:
            raise FileNotFoundError(
                "The Parquet file does not exist. "
                "If it is in another location, provide the correct path as parquet_path.",
            ) from exc

    def delete_parquet(self) -> None:
        """
        Delete the Parquet file.
        """
        for parquet_path in self.parquet_paths:
            parquet_path.unlink()
            print(f"Parquet file deleted: {parquet_path}")
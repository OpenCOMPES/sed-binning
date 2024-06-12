"""Run this from main package dir"""
import shutil
from pathlib import Path


def load_checksums(checksum_file):
    checksums = {}
    with open(checksum_file) as f:
        for line in f:
            checksum, path = line.strip().split()
            checksums[path] = checksum
    return checksums


def main():
    checksum_file_name = "tutorial_checksums.txt"
    docs_dir = Path("docs").resolve()
    tutorial_src_dir = Path("tutorial").resolve()
    cache_dir = docs_dir / "tutorial"
    current_checksums_file = Path(checksum_file_name).resolve()
    cached_checksums_file = cache_dir / checksum_file_name

    cache_dir.mkdir(parents=True, exist_ok=True)

    if not cached_checksums_file.exists():
        print("No cached checksums found. Copying tutorials.")
        for file in tutorial_src_dir.glob("*.ipynb"):
            shutil.copy(file, cache_dir)
        print("Copying new checksums to docs/tutorial")
        shutil.copy(current_checksums_file, cache_dir)
        return

    current_checksums = load_checksums(current_checksums_file)
    cached_checksums = load_checksums(cached_checksums_file)

    for notebook, checksum in current_checksums.items():
        if notebook in cached_checksums and cached_checksums[notebook] != checksum:
            print(f"CHANGED: {notebook}. Copying file.")
            shutil.copy(notebook, cache_dir)
        else:
            print(f"NOT CHANGED: {notebook}. Will use cached version.")
    if cached_checksums != current_checksums:
        print("Copying new checksums to docs/tutorial")
        shutil.copy(current_checksums_file, cache_dir)


if __name__ == "__main__":
    main()

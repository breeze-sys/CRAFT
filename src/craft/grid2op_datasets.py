"""Grid2Op dataset management helpers for CRAFT."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
import warnings
from argparse import ArgumentParser
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

MAX_DATASET_BYTES = 5 * 1024**3
DEFAULT_NON_TEST_DATASET = "l2rpn_neurips_2020_track1_small"
CHUNK_SIZE = 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GRID2OP_DATA_DIR = REPO_ROOT / "data" / "grid2op"
ENV_GRID2OP_DATA_DIR = "CRAFT_GRID2OP_DATA_DIR"
L2RPN_2019_OLD_IMPORT = "from grid2op.Chronics import ReadPypowNetData"
L2RPN_2019_NEW_IMPORT = "from grid2op.Chronics.readPypowNetData import ReadPypowNetData"


@dataclass(frozen=True)
class DatasetCandidate:
    name: str
    estimated_size_gb: float
    grid_size: str
    recommended_for: str
    url: str
    preferred: bool = False


CURATED_NON_TEST_DATASETS: tuple[DatasetCandidate, ...] = (
    DatasetCandidate(
        name="l2rpn_2019",
        estimated_size_gb=0.22,
        grid_size="14-bus L2RPN 2019 benchmark",
        recommended_for="smallest non-test fallback when large dataset downloads are unstable",
        url="https://l2rpnukstorageprem.blob.core.windows.net/l2rpnarchive/l2rpn_2019.tar.bz2",
    ),
    DatasetCandidate(
        name="l2rpn_neurips_2020_track1_small",
        estimated_size_gb=0.9,
        grid_size="36 substations, 59 lines",
        recommended_for="default CRAFT MVP dataset: non-test, compact, competition-grade chronics",
        url=(
            "https://l2rpnukstorageprem.blob.core.windows.net/l2rpnarchive/"
            "l2rpn_neurips_2020_track1_small.tar.bz2"
        ),
        preferred=True,
    ),
    DatasetCandidate(
        name="l2rpn_icaps_2021_small",
        estimated_size_gb=1.0,
        grid_size="36 substations, 59 lines",
        recommended_for="alternative compact non-test dataset from L2RPN ICAPS 2021",
        url=(
            "https://l2rpnukstorageprem.blob.core.windows.net/l2rpncompdata/"
            "l2rpn_icaps_2021_small.tar.bz2"
        ),
    ),
    DatasetCandidate(
        name="l2rpn_wcci_2022",
        estimated_size_gb=1.7,
        grid_size="118 substations, 186 lines",
        recommended_for="larger 118-bus benchmark if we need storage units later",
        url="https://codalab.lisn.upsaclay.fr/my/datasets/download/a822a879-31a4-4634-a66a-eb851ec369c9",
    ),
    DatasetCandidate(
        name="l2rpn_neurips_2020_track2_small",
        estimated_size_gb=2.5,
        grid_size="118 substations, 186 lines",
        recommended_for="larger 118-bus NeurIPS benchmark under the 5G budget",
        url=(
            "https://l2rpnukstorageprem.blob.core.windows.net/l2rpnarchive/"
            "l2rpn_neurips_2020_track2_small.tar.bz2"
        ),
    ),
    DatasetCandidate(
        name="l2rpn_wcci_2020",
        estimated_size_gb=4.5,
        grid_size="36 substations, 59 lines",
        recommended_for="older full WCCI 2020 dataset, close to the storage cap",
        url=(
            "https://l2rpnukstorageprem.blob.core.windows.net/l2rpnarchive/"
            "l2rpn_wcci_2020.tar.bz2"
        ),
    ),
)


def _suppress_grid2op_warnings() -> None:
    warnings.filterwarnings("ignore", message="Numba cannot be loaded.*")
    warnings.filterwarnings("ignore", message="It is the first time you use the environment.*")


def get_configured_grid2op_data_dir() -> Path:
    data_dir = os.getenv(ENV_GRID2OP_DATA_DIR)
    if data_dir:
        return Path(data_dir).expanduser().resolve()
    return DEFAULT_GRID2OP_DATA_DIR.resolve()


def configure_grid2op_data_dir(data_dir: Path | None = None) -> Path:
    """Point Grid2Op to the CRAFT project-local dataset directory."""
    target = (data_dir or get_configured_grid2op_data_dir()).expanduser().resolve()
    _suppress_grid2op_warnings()
    import grid2op.MakeEnv.PathUtils as path_utils

    path_utils.DEFAULT_PATH_DATA = str(target)
    return target


def get_grid2op_data_dir() -> Path:
    return configure_grid2op_data_dir()


def get_candidate(name: str) -> DatasetCandidate:
    normalized = name.lower().strip()
    for candidate in CURATED_NON_TEST_DATASETS:
        if candidate.name == normalized:
            return candidate
    known = ", ".join(candidate.name for candidate in CURATED_NON_TEST_DATASETS)
    raise KeyError(f"Unknown curated non-test dataset '{name}'. Known datasets: {known}")


def format_size(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "unknown"
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def folder_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for root, _dirs, files in os.walk(path):
        root_path = Path(root)
        for file_name in files:
            try:
                total += (root_path / file_name).stat().st_size
            except FileNotFoundError:
                continue
    return total


def remote_content_length(url: str, *, timeout: int = 30) -> int | None:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            header = response.headers.get("Content-Length")
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        print(f"Warning: remote size probe failed, continuing without HEAD check: {exc}")
        return None
    return int(header) if header else None


def ensure_under_budget(candidate: DatasetCandidate, max_bytes: int) -> None:
    estimated_bytes = int(candidate.estimated_size_gb * 1024**3)
    if estimated_bytes > max_bytes:
        raise ValueError(
            f"{candidate.name} is estimated at {candidate.estimated_size_gb:.1f} GB, "
            f"above the configured budget of {format_size(max_bytes)}."
        )


def apply_dataset_compatibility_patches(
    name: str,
    dataset_dir: Path | None = None,
) -> tuple[str, ...]:
    """Patch known legacy dataset config issues for newer Grid2Op releases."""
    if dataset_dir is None:
        dataset_dir = get_grid2op_data_dir() / name
    if name != "l2rpn_2019":
        return ()

    config_path = dataset_dir / "config.py"
    if not config_path.exists():
        return ()

    text = config_path.read_text(encoding="utf-8")
    if L2RPN_2019_OLD_IMPORT not in text:
        return ()

    config_path.write_text(
        text.replace(L2RPN_2019_OLD_IMPORT, L2RPN_2019_NEW_IMPORT),
        encoding="utf-8",
    )
    return ("patched l2rpn_2019 ReadPypowNetData import for Grid2Op >=1.12",)


def _safe_extract_tar_bz2(archive_path: Path, destination: Path, max_bytes: int) -> None:
    destination_resolved = destination.resolve()
    with tarfile.open(archive_path, "r:bz2") as archive:
        members = archive.getmembers()
        total_uncompressed = sum(member.size for member in members)
        if total_uncompressed > max_bytes:
            raise ValueError(
                "Refusing to extract dataset because the uncompressed size "
                f"{format_size(total_uncompressed)} exceeds {format_size(max_bytes)}."
            )
        for member in members:
            target = (destination / member.name).resolve()
            if destination_resolved not in (target, *target.parents):
                raise ValueError(f"Unsafe archive path detected: {member.name}")
            if member.islnk() or member.issym():
                raise ValueError(f"Refusing to extract archive link: {member.name}")
        archive.extractall(destination, members=members)


def _download_to_file(url: str, output_path: Path, *, timeout: int = 60) -> int:
    request = urllib.request.Request(url)
    downloaded = 0
    next_report = time.monotonic() + 5
    with urllib.request.urlopen(request, timeout=timeout) as response:
        total_header = response.headers.get("Content-Length")
        total = int(total_header) if total_header else None
        with output_path.open("wb") as output:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now >= next_report:
                    if total:
                        pct = downloaded / total * 100
                        print(
                            f"  downloaded {format_size(downloaded)} / "
                            f"{format_size(total)} ({pct:.1f}%)"
                        )
                    else:
                        print(f"  downloaded {format_size(downloaded)}")
                    next_report = now + 5
    return downloaded


def _curl_download_command(url: str, output_path: Path, *, resume: bool) -> list[str]:
    curl = shutil.which("curl")
    if curl is None:
        raise RuntimeError("curl is not available on this host.")

    command = [
        curl,
        "-L",
        "--fail",
        "--retry",
        "8",
        "--retry-delay",
        "5",
        "--connect-timeout",
        "30",
        "--speed-time",
        "120",
        "--speed-limit",
        "1024",
        "--output",
        str(output_path),
        url,
    ]
    if resume:
        command[3:3] = ["--continue-at", "-"]
    return command


def _download_with_curl(url: str, output_path: Path) -> int:
    resume = output_path.exists() and output_path.stat().st_size > 0
    cmd = _curl_download_command(url, output_path, resume=resume)
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        if exc.returncode != 33:
            raise
        if output_path.exists():
            print("curl resume failed with HTTP range error; restarting from scratch.")
            output_path.unlink()
        subprocess.run(_curl_download_command(url, output_path, resume=False), check=True)
    return output_path.stat().st_size


def download_dataset(
    name: str = DEFAULT_NON_TEST_DATASET,
    *,
    max_bytes: int = MAX_DATASET_BYTES,
    keep_archive: bool = False,
    prefer_curl: bool = True,
) -> Path:
    candidate = get_candidate(name)
    ensure_under_budget(candidate, max_bytes)
    data_dir = get_grid2op_data_dir()
    dataset_dir = data_dir / candidate.name
    if dataset_dir.exists():
        print(f"Dataset already exists: {dataset_dir}")
        print(f"Disk usage: {format_size(folder_size_bytes(dataset_dir))}")
        return dataset_dir

    remote_size = remote_content_length(candidate.url)
    if remote_size is not None and remote_size > max_bytes:
        raise ValueError(
            f"Remote archive size {format_size(remote_size)} exceeds {format_size(max_bytes)}."
        )

    data_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir = data_dir / ".downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    archive_path = downloads_dir / f"{candidate.name}.tar.bz2"
    try:
        print(f"Downloading {candidate.name}")
        print(f"Source: {candidate.url}")
        if remote_size is not None:
            print(f"Remote archive size: {format_size(remote_size)}")

        if prefer_curl and shutil.which("curl") is not None:
            print("Downloader: curl with resume/retry support")
            downloaded = _download_with_curl(candidate.url, archive_path)
        else:
            print("Downloader: Python urllib")
            with NamedTemporaryFile(
                prefix=f"{candidate.name}.",
                suffix=".tar.bz2.part",
                dir=downloads_dir,
                delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
            try:
                downloaded = _download_to_file(candidate.url, tmp_path)
                tmp_path.replace(archive_path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()

        if remote_size is not None and downloaded != remote_size:
            raise ValueError(
                f"Downloaded archive size {format_size(downloaded)} does not match "
                f"remote size {format_size(remote_size)}. Re-run the command to resume."
            )
        print(f"Downloaded: {format_size(downloaded)}")

        print(f"Extracting to {data_dir}")
        _safe_extract_tar_bz2(archive_path, data_dir, max_bytes)

        actual_size = folder_size_bytes(dataset_dir)
        if actual_size > max_bytes:
            raise ValueError(
                f"Extracted dataset uses {format_size(actual_size)}, "
                f"above {format_size(max_bytes)}."
            )

        _suppress_grid2op_warnings()
        from grid2op.MakeEnv.UpdateEnv import _update_files  # type: ignore[import-untyped]

        _update_files(candidate.name)
        for patch_message in apply_dataset_compatibility_patches(candidate.name, dataset_dir):
            print(f"Compatibility patch: {patch_message}")
        print(f"Ready: {dataset_dir}")
        print(f"Disk usage: {format_size(actual_size)}")
        return dataset_dir
    finally:
        if dataset_dir.exists() and archive_path.exists() and not keep_archive:
            archive_path.unlink()


def inspect_dataset(name: str = DEFAULT_NON_TEST_DATASET) -> dict[str, Any]:
    _suppress_grid2op_warnings()
    import grid2op

    dataset_dir = get_grid2op_data_dir() / name
    for patch_message in apply_dataset_compatibility_patches(name, dataset_dir):
        print(f"Compatibility patch: {patch_message}")

    env = grid2op.make(name, test=False)
    try:
        obs = env.reset()
        return {
            "name": env.name,
            "path": str(get_grid2op_data_dir() / name),
            "backend": type(env.backend).__name__,
            "n_sub": int(env.n_sub),
            "n_line": int(env.n_line),
            "n_gen": int(env.n_gen),
            "n_load": int(env.n_load),
            "max_rho_after_reset": float(obs.rho.max()),
            "disk_usage": format_size(folder_size_bytes(get_grid2op_data_dir() / name)),
        }
    finally:
        env.close()


def _print_candidates(candidates: Iterable[DatasetCandidate]) -> None:
    print(f"Grid2Op data dir: {get_grid2op_data_dir()}")
    print("Curated non-test datasets under the 5G budget:")
    for candidate in candidates:
        marker = "*" if candidate.preferred else "-"
        print(
            f" {marker} {candidate.name:34} "
            f"~{candidate.estimated_size_gb:.1f} GB | {candidate.grid_size} | "
            f"{candidate.recommended_for}"
        )


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Manage compact non-test Grid2Op datasets for CRAFT.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="list curated non-test datasets")

    download_parser = subparsers.add_parser("download", help="download a curated non-test dataset")
    download_parser.add_argument("name", nargs="?", default=DEFAULT_NON_TEST_DATASET)
    download_parser.add_argument("--max-gb", type=float, default=5.0)
    download_parser.add_argument("--keep-archive", action="store_true")
    download_parser.add_argument(
        "--python-download",
        action="store_true",
        help="disable curl resume/retry and use Python urllib instead",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="load and summarize a downloaded dataset",
    )
    inspect_parser.add_argument("name", nargs="?", default=DEFAULT_NON_TEST_DATASET)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "list":
        _print_candidates(CURATED_NON_TEST_DATASETS)
        return 0
    if args.command == "download":
        max_bytes = int(args.max_gb * 1024**3)
        download_dataset(
            args.name,
            max_bytes=max_bytes,
            keep_archive=args.keep_archive,
            prefer_curl=not args.python_download,
        )
        return 0
    if args.command == "inspect":
        info = inspect_dataset(args.name)
        for key, value in info.items():
            print(f"{key}: {value}")
        return 0
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

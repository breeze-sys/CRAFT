import subprocess
import urllib.error
from pathlib import Path

from craft import grid2op_datasets


def test_curl_range_error_restarts_from_scratch(monkeypatch, tmp_path: Path) -> None:
    archive_path = tmp_path / "dataset.tar.bz2"
    archive_path.write_bytes(b"partial")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *, check: bool) -> None:
        assert check
        calls.append(cmd)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(33, cmd)
        archive_path.write_bytes(b"complete")

    monkeypatch.setattr(grid2op_datasets.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(grid2op_datasets.subprocess, "run", fake_run)

    downloaded = grid2op_datasets._download_with_curl(
        "https://example.com/data.tar.bz2",
        archive_path,
    )

    assert downloaded == len(b"complete")
    assert "--continue-at" in calls[0]
    assert "--continue-at" not in calls[1]


def test_remote_content_length_failure_is_non_fatal(monkeypatch) -> None:
    def fake_urlopen(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(grid2op_datasets.urllib.request, "urlopen", fake_urlopen)

    assert grid2op_datasets.remote_content_length("https://example.com/data.tar.bz2") is None


def test_l2rpn_2019_legacy_import_patch_is_idempotent(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "l2rpn_2019"
    dataset_dir.mkdir()
    config_path = dataset_dir / "config.py"
    config_path.write_text(
        "from grid2op.Chronics import Multifolder\n"
        "from grid2op.Chronics import ReadPypowNetData\n",
        encoding="utf-8",
    )

    changes = grid2op_datasets.apply_dataset_compatibility_patches("l2rpn_2019", dataset_dir)
    assert changes == ("patched l2rpn_2019 ReadPypowNetData import for Grid2Op >=1.12",)
    assert grid2op_datasets.L2RPN_2019_NEW_IMPORT in config_path.read_text(encoding="utf-8")

    assert grid2op_datasets.apply_dataset_compatibility_patches("l2rpn_2019", dataset_dir) == ()


def test_default_grid2op_data_dir_is_project_local(monkeypatch) -> None:
    monkeypatch.delenv(grid2op_datasets.ENV_GRID2OP_DATA_DIR, raising=False)

    assert grid2op_datasets.get_configured_grid2op_data_dir() == (
        grid2op_datasets.REPO_ROOT / "data" / "grid2op"
    )

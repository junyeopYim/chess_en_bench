"""Tests for the safe upload transport (P1.2): a hostile archive must be
rejected before anything is written outside the destination."""

import io
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from ceb.hosted.upload import safe_extract_archive, UploadError


def _tar_gz(tmp_path, members):
    """members: list of (name, data_bytes) regular files."""
    path = tmp_path / "ws.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def _tar_with_member(tmp_path, info_mutator):
    path = tmp_path / "evil.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo("placeholder")
        info_mutator(info, tar)
    return path


def test_clean_tar_gz_extracts(tmp_path):
    archive = _tar_gz(tmp_path, [("engine", b"#!/bin/bash\n"),
                                 ("src/a.cpp", b"int main(){}\n")])
    dest = safe_extract_archive(archive, tmp_path / "out")
    assert (dest / "engine").read_bytes() == b"#!/bin/bash\n"
    assert (dest / "src" / "a.cpp").is_file()


def test_clean_zip_extracts(tmp_path):
    path = tmp_path / "ws.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("engine", "#!/bin/bash\n")
        zf.writestr("src/b.cpp", "int main(){}\n")
    dest = safe_extract_archive(path, tmp_path / "out")
    assert (dest / "engine").is_file() and (dest / "src" / "b.cpp").is_file()


def test_path_traversal_tar_rejected(tmp_path):
    def add(_info, tar):
        evil = tarfile.TarInfo("../escape.txt")
        evil.size = 3
        tar.addfile(evil, io.BytesIO(b"bad"))
    archive = _tar_with_member(tmp_path, add)
    with pytest.raises(UploadError, match="traversal"):
        safe_extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_absolute_path_tar_rejected(tmp_path):
    def add(_info, tar):
        evil = tarfile.TarInfo("/abs.txt")
        evil.size = 1
        tar.addfile(evil, io.BytesIO(b"x"))
    archive = _tar_with_member(tmp_path, add)
    with pytest.raises(UploadError, match="absolute"):
        safe_extract_archive(archive, tmp_path / "out")


def test_symlink_tar_rejected(tmp_path):
    def add(_info, tar):
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tar.addfile(link)
    archive = _tar_with_member(tmp_path, add)
    with pytest.raises(UploadError, match="link"):
        safe_extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()  # cleaned up on rejection


def test_symlink_zip_rejected(tmp_path):
    path = tmp_path / "evil.zip"
    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(UploadError, match="symlink"):
        safe_extract_archive(path, tmp_path / "out")


def test_oversized_file_rejected(tmp_path):
    archive = _tar_gz(tmp_path, [("big", b"x" * 2048)])
    with pytest.raises(UploadError, match="per-file limit"):
        safe_extract_archive(archive, tmp_path / "out", max_file_bytes=1024)


def test_destination_must_not_exist(tmp_path):
    archive = _tar_gz(tmp_path, [("a", b"1")])
    (tmp_path / "out").mkdir()
    with pytest.raises(UploadError, match="already exists"):
        safe_extract_archive(archive, tmp_path / "out")


def test_cli_submit_archive(tmp_path, capsys):
    from ceb.cli import main
    from ceb.hosted import db as hosted_db

    example = Path(__file__).resolve().parents[1] / "examples" / "submissions" \
        / "minimal_uci_engine_python"
    archive = tmp_path / "sub.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for f in ("engine", "engine.py", "build.sh"):
            data = (example / f).read_bytes()
            info = tarfile.TarInfo(f)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    db = str(tmp_path / "h.sqlite")
    assert main(["hosted", "init", "--db", db]) == 0
    rc = main(["hosted", "submit", "--track", "A", "--archive", str(archive),
               "--run-id", "arch_run", "--db", db])
    assert rc == 0, capsys.readouterr().out
    conn = hosted_db.connect(db)
    try:
        assert hosted_db.latest_submission(conn, "arch_run") is not None
    finally:
        conn.close()

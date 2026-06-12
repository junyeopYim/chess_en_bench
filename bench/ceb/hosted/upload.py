"""Safe workspace upload transport (P1.2).

`safe_extract_archive` extracts a .tar.gz/.tar/.zip workspace upload into a
fresh directory, rejecting the classic archive attacks before writing anything:

  - absolute member paths (/etc/passwd),
  - path traversal (.. escaping the destination),
  - symlinks and hardlinks (which could later be followed out of the jail),
  - non-regular members (devices, fifos),
  - too many members or oversized members/total (zip/tar bombs).

It never uses tarfile.extractall / ZipFile.extractall (which are unsafe);
each member is validated and written by hand. After extraction the caller
snapshots and hashes the tree with the existing submission machinery.
"""

import os
import stat
import tarfile
import zipfile
from pathlib import Path

from ceb.sanitize import SanitizedError

DEFAULT_MAX_FILES = 10_000
DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024       # 50 MiB per file
DEFAULT_MAX_TOTAL_BYTES = 200 * 1024 * 1024     # 200 MiB total


class UploadError(SanitizedError, ValueError):
    pass


def _safe_relpath(name, dest):
    """Validate an archive member name; return the resolved target path."""
    if not name or name in (".", "./"):
        return None  # skip the archive root entry
    pure = name.replace("\\", "/")
    if pure.startswith("/") or (len(pure) > 1 and pure[1] == ":"):
        raise UploadError("archive rejected: absolute path %r" % name)
    parts = [p for p in pure.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise UploadError("archive rejected: path traversal in %r" % name)
    target = (dest / "/".join(parts)).resolve()
    dest_resolved = dest.resolve()
    if target != dest_resolved and dest_resolved not in target.parents:
        raise UploadError("archive rejected: member escapes destination: %r"
                          % name)
    return target


def _check_limits(count, total, size, name, max_files, max_total, max_file):
    if count > max_files:
        raise UploadError("archive rejected: too many files (> %d)" % max_files)
    if size > max_file:
        raise UploadError("archive rejected: %r exceeds per-file limit (%d bytes)"
                          % (name, max_file))
    if total > max_total:
        raise UploadError("archive rejected: total size exceeds %d bytes"
                          % max_total)


def _extract_tar(archive_path, dest, max_files, max_file, max_total):
    count = total = 0
    with tarfile.open(archive_path, "r:*") as tar:
        for member in tar:
            if member.isdir():
                target = _safe_relpath(member.name, dest)
                if target:
                    target.mkdir(parents=True, exist_ok=True)
                continue
            if member.issym() or member.islnk():
                raise UploadError("archive rejected: link member %r (symlinks "
                                  "and hardlinks are not allowed)" % member.name)
            if not member.isfile():
                raise UploadError("archive rejected: non-regular member %r"
                                  % member.name)
            target = _safe_relpath(member.name, dest)
            if target is None:
                continue
            count += 1
            total += member.size
            _check_limits(count, total, member.size, member.name,
                          max_files, max_total, max_file)
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            with open(target, "wb") as fh:
                if src is not None:
                    fh.write(src.read())


def _extract_zip(archive_path, dest, max_files, max_file, max_total):
    count = total = 0
    with zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.endswith("/"):
                target = _safe_relpath(name, dest)
                if target:
                    target.mkdir(parents=True, exist_ok=True)
                continue
            # zip stores unix mode in the high 16 bits of external_attr.
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode and stat.S_ISLNK(mode):
                raise UploadError("archive rejected: symlink member %r" % name)
            target = _safe_relpath(name, dest)
            if target is None:
                continue
            count += 1
            total += info.file_size
            _check_limits(count, total, info.file_size, name,
                          max_files, max_total, max_file)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as fh:
                fh.write(src.read())


def safe_extract_archive(archive_path, dest, *, max_files=DEFAULT_MAX_FILES,
                         max_file_bytes=DEFAULT_MAX_FILE_BYTES,
                         max_total_bytes=DEFAULT_MAX_TOTAL_BYTES):
    """Extract a .tar.gz/.tar/.zip archive into dest (must not exist).

    Returns the destination Path. Raises UploadError on any unsafe member.
    """
    archive_path = Path(archive_path)
    dest = Path(dest)
    if dest.exists():
        raise UploadError("extraction destination already exists: %s" % dest)
    if not archive_path.is_file():
        raise UploadError("archive not found: %s" % archive_path.name)
    dest.mkdir(parents=True)

    name = archive_path.name.lower()
    try:
        if name.endswith(".zip"):
            _extract_zip(archive_path, dest, max_files, max_file_bytes,
                         max_total_bytes)
        elif (name.endswith(".tar.gz") or name.endswith(".tgz")
              or name.endswith(".tar")):
            _extract_tar(archive_path, dest, max_files, max_file_bytes,
                         max_total_bytes)
        else:
            raise UploadError("unsupported archive type %r (use .tar.gz, .tgz, "
                              ".tar, or .zip)" % archive_path.name)
    except (tarfile.TarError, zipfile.BadZipFile) as exc:
        import shutil
        shutil.rmtree(dest, ignore_errors=True)
        raise UploadError("archive could not be read (corrupt or unsupported)",
                          "archive read error: %s" % exc)
    except UploadError:
        import shutil
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest

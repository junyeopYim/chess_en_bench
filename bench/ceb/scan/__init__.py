"""Anti-cheating scanners for submissions."""

from ceb.scan.static_scan import scan_workspace
from ceb.scan.track_b_scan import scan_track_b

__all__ = ["scan_workspace", "scan_track_b"]

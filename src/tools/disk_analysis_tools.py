"""
Disk and File Usage Analysis & Cleanup Tools.

Provides Laya with the capability to analyze file usage/access timestamps,
identify stale, unneeded, or duplicate files (old installers, temp cache,
large unused files), and recommend or perform safe cleanup.
"""

from __future__ import annotations

import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.tools.base import PermissionLevel, ToolParameter, ToolResult
from src.tools.registry import register
from src.utils.logger import get_logger

logger = get_logger("tools.disk_analysis")

# Common installer and archive extensions frequently left in Downloads
_INSTALLER_EXTENSIONS = {".exe", ".msi", ".iso", ".dmg", ".pkg", ".vhd", ".appx"}
_ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz"}


def _get_file_last_used_timestamp(stat_res: os.stat_result) -> float:
    """
    Get the most accurate last-used timestamp on Windows.
    On NTFS, st_atime may be delayed or disabled, so we use max(st_atime, st_mtime).
    """
    return max(stat_res.st_atime, stat_res.st_mtime)


def _format_size(size_bytes: int | float) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.2f} GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{int(size_bytes)} B"


@register(
    name="analyze_unneeded_files",
    description="Scan and analyze files in your system (Downloads, Temp cache, large unused files) to determine what files are unnecessary, unneeded, or stale based on their last usage/access time and size. ALWAYS call this when the user asks to analyze, inspect, or identify unused/unneeded files.",
    permission=PermissionLevel.SAFE,
    category="system",
    parameters=[
        ToolParameter(
            name="target_area",
            type="string",
            description="Target area to analyze: 'all' (default), 'downloads', 'temp', or 'large_files'",
            required=False,
            default="all",
        ),
        ToolParameter(
            name="min_age_days",
            type="integer",
            description="Minimum number of days since last use/modification to consider a file stale (default 30 days)",
            required=False,
            default=30,
        ),
        ToolParameter(
            name="min_size_mb",
            type="float",
            description="Minimum file size in megabytes to include in large unused files (default 20.0 MB)",
            required=False,
            default=20.0,
        ),
    ],
)
def analyze_unneeded_files(
    target_area: str = "all",
    min_age_days: int = 30,
    min_size_mb: float = 20.0,
    **kwargs: Any,
) -> ToolResult:
    """
    Scan user directories for files that are likely unnecessary based on their
    last usage/access time and type.
    """
    now = time.time()
    min_age_seconds = max(1, min_age_days) * 86400
    min_size_bytes = max(0.0, min_size_mb) * (1024 * 1024)
    target = target_area.lower().strip()

    home = Path.home()
    downloads_dir = home / "Downloads"
    temp_dir_str = os.environ.get("TEMP", "")
    temp_dir = Path(temp_dir_str) if temp_dir_str else (home / "AppData" / "Local" / "Temp")

    results: Dict[str, Any] = {
        "old_installers": [],
        "stale_downloads": [],
        "temp_and_cache": [],
        "large_unused_files": [],
        "total_unneeded_bytes": 0,
    }

    # 1. Analyze Downloads
    if target in ("all", "downloads", "download"):
        if downloads_dir.exists() and downloads_dir.is_dir():
            try:
                for entry in downloads_dir.iterdir():
                    if not entry.is_file():
                        continue
                    try:
                        stat = entry.stat()
                        last_used = _get_file_last_used_timestamp(stat)
                        age_days = int((now - last_used) / 86400)
                        size = stat.st_size
                        ext = entry.suffix.lower()

                        if age_days >= min_age_days:
                            item = {
                                "name": entry.name,
                                "path": str(entry),
                                "size_bytes": size,
                                "size_formatted": _format_size(size),
                                "age_days": age_days,
                                "last_used": datetime.fromtimestamp(last_used).strftime("%Y-%m-%d"),
                            }
                            if ext in _INSTALLER_EXTENSIONS or ext in _ARCHIVE_EXTENSIONS:
                                item["type"] = "Installer/Archive"
                                results["old_installers"].append(item)
                            else:
                                item["type"] = "Stale File"
                                results["stale_downloads"].append(item)
                            results["total_unneeded_bytes"] += size
                    except (PermissionError, FileNotFoundError):
                        continue
            except Exception as e:
                logger.warning(f"Error scanning downloads: {e}")

    # 2. Analyze Temp & Cache Junk
    if target in ("all", "temp", "cache"):
        if temp_dir.exists() and temp_dir.is_dir():
            temp_age_seconds = max(7, min_age_days // 4) * 86400  # Temp files older than 7 days
            try:
                temp_bytes = 0
                temp_count = 0
                for root, _, files in os.walk(temp_dir):
                    for fn in files:
                        fp = Path(root) / fn
                        try:
                            stat = fp.stat()
                            last_used = _get_file_last_used_timestamp(stat)
                            if (now - last_used) >= temp_age_seconds:
                                temp_bytes += stat.st_size
                                temp_count += 1
                        except (PermissionError, FileNotFoundError):
                            continue
                if temp_count > 0:
                    results["temp_and_cache"].append({
                        "name": f"Windows User Temp Cache ({temp_count} files)",
                        "path": str(temp_dir),
                        "size_bytes": temp_bytes,
                        "size_formatted": _format_size(temp_bytes),
                        "file_count": temp_count,
                        "type": "Temporary Cache",
                    })
                    results["total_unneeded_bytes"] += temp_bytes
            except Exception as e:
                logger.warning(f"Error scanning temp directory: {e}")

    # 3. Analyze Large Inactive Files in User Documents / Media / Projects
    if target in ("all", "large_files", "large"):
        candidate_dirs = [
            downloads_dir,
            home / "Documents",
            home / "OneDrive" / "Documents",
            home / "Videos",
        ]
        skip_names = {
            ".git", "node_modules", ".venv", "venv", "appdata",
            "__pycache__", "target", "build", "dist", ".vscode", ".idea", ".cache"
        }
        scanned_paths = set()

        def _scan_bounded(dir_path: Path, depth: int = 0) -> None:
            if depth > 3:
                return
            try:
                if not dir_path.exists():
                    return
                with os.scandir(dir_path) as it:
                    for entry in it:
                        name_lower = entry.name.lower()
                        if entry.is_dir(follow_symlinks=False):
                            if name_lower not in skip_names and not name_lower.startswith("."):
                                _scan_bounded(Path(entry.path), depth + 1)
                        elif entry.is_file(follow_symlinks=False):
                            str_path = str(entry.path)
                            if str_path in scanned_paths:
                                continue
                            scanned_paths.add(str_path)

                            try:
                                stat = entry.stat()
                                if stat.st_size >= min_size_bytes:
                                    last_used = _get_file_last_used_timestamp(stat)
                                    age_days = int((now - last_used) / 86400)
                                    if age_days >= min_age_days:
                                        if not any(oi["path"] == str_path for oi in results["old_installers"]):
                                            results["large_unused_files"].append({
                                                "name": entry.name,
                                                "path": str_path,
                                                "size_bytes": stat.st_size,
                                                "size_formatted": _format_size(stat.st_size),
                                                "age_days": age_days,
                                                "last_used": datetime.fromtimestamp(last_used).strftime("%Y-%m-%d"),
                                            })
                            except (PermissionError, FileNotFoundError, OSError):
                                continue
            except (PermissionError, OSError):
                return
            except Exception as e:
                logger.debug(f"Error scanning directory {dir_path}: {e}")

        for c_dir in candidate_dirs:
            if c_dir.exists() and c_dir.is_dir():
                _scan_bounded(c_dir, 0)

    # Sort items by size descending
    results["old_installers"].sort(key=lambda x: x["size_bytes"], reverse=True)
    results["stale_downloads"].sort(key=lambda x: x["size_bytes"], reverse=True)
    results["large_unused_files"].sort(key=lambda x: x["size_bytes"], reverse=True)

    # Compute summary metrics
    total_size_fmt = _format_size(results["total_unneeded_bytes"])
    installer_bytes = sum(x["size_bytes"] for x in results["old_installers"])
    stale_bytes = sum(x["size_bytes"] for x in results["stale_downloads"])
    temp_bytes = sum(x["size_bytes"] for x in results["temp_and_cache"])
    large_bytes = sum(x["size_bytes"] for x in results["large_unused_files"])

    summary_paragraphs = []
    summary_paragraphs.append(
        f"I analyzed your system files. You have approximately {total_size_fmt} of potentially unneeded files based on usage time (untouched for {min_age_days}+ days):"
    )

    if results["old_installers"]:
        top_inst = results["old_installers"][:3]
        sample = ", ".join(f"{x['name']} ({x['size_formatted']}, {x['age_days']} days old)" for x in top_inst)
        summary_paragraphs.append(
            f"- Old Installers & Archives: {_format_size(installer_bytes)} across {len(results['old_installers'])} files (e.g. {sample})."
        )

    if results["temp_and_cache"]:
        summary_paragraphs.append(
            f"- Temporary Cache Junk: {_format_size(temp_bytes)} in your Windows temp directory that can safely be cleared."
        )

    if results["stale_downloads"]:
        summary_paragraphs.append(
            f"- Stale Downloads: {_format_size(stale_bytes)} across {len(results['stale_downloads'])} files not opened in over {min_age_days} days."
        )

    if results["large_unused_files"]:
        top_large = results["large_unused_files"][:3]
        sample_l = ", ".join(f"{x['name']} ({x['size_formatted']}, {x['age_days']} days old)" for x in top_large)
        summary_paragraphs.append(
            f"- Large Inactive Files: {_format_size(large_bytes)} across {len(results['large_unused_files'])} files (e.g. {sample_l})."
        )

    summary_paragraphs.append(
        "Analysis complete. You can review these files or ask me to clean up your temporary cache files."
    )

    final_msg = "\n".join(summary_paragraphs)

    return ToolResult(
        success=True,
        message=final_msg,
        data={
            "total_unneeded_bytes": results["total_unneeded_bytes"],
            "total_unneeded_formatted": total_size_fmt,
            "old_installers_count": len(results["old_installers"]),
            "old_installers_bytes": installer_bytes,
            "old_installers_sample": results["old_installers"][:10],
            "stale_downloads_count": len(results["stale_downloads"]),
            "stale_downloads_bytes": stale_bytes,
            "temp_cache_bytes": temp_bytes,
            "large_unused_count": len(results["large_unused_files"]),
            "large_unused_sample": results["large_unused_files"][:10],
        },
    )


@register(
    name="clean_unneeded_files",
    description="Permanently delete and purge unneeded temporary cache files or old installers from disk to reclaim storage. NEVER call this to analyze or inspect files; only call this when the user explicitly asks to delete, purge, or clean files.",
    permission=PermissionLevel.DANGEROUS,
    category="system",
    parameters=[
        ToolParameter(
            name="category",
            type="string",
            description="What category to clean: 'temp' (Windows temporary cache files, safest) or 'downloads_installers' (old setup/installer files in Downloads)",
            required=False,
            default="temp",
        ),
        ToolParameter(
            name="min_age_days",
            type="integer",
            description="Minimum age in days of files to delete (default 7 days for temp, 30 days for downloads)",
            required=False,
            default=7,
        ),
        ToolParameter(
            name="confirm",
            type="boolean",
            description="Set to True to actually perform deletion. If False, only previews what files and space will be freed.",
            required=False,
            default=False,
        ),
    ],
)
def clean_unneeded_files(
    category: str = "temp",
    min_age_days: int = 7,
    confirm: bool = False,
    **kwargs: Any,
) -> ToolResult:
    """Safely delete unneeded temporary files or old installers with preview and confirmation."""
    cat = category.lower().strip()
    now = time.time()
    min_seconds = max(1, min_age_days) * 86400

    deleted_count = 0
    deleted_bytes = 0
    errors_count = 0

    if cat in ("temp", "cache", "temporary"):
        temp_dir_str = os.environ.get("TEMP", "")
        if not temp_dir_str:
            return ToolResult(success=False, error="TEMP environment variable not found", message="Could not locate TEMP folder.")
        temp_path = Path(temp_dir_str)

        # 1. Preview
        files_to_delete = []
        for root, dirs, files in os.walk(temp_path):
            for fn in files:
                fp = Path(root) / fn
                try:
                    stat = fp.stat()
                    last_used = _get_file_last_used_timestamp(stat)
                    if (now - last_used) >= min_seconds:
                        files_to_delete.append((fp, stat.st_size))
                except (PermissionError, FileNotFoundError):
                    continue

        total_bytes = sum(s for _, s in files_to_delete)
        total_fmt = _format_size(total_bytes)

        if not confirm:
            return ToolResult(
                success=True,
                message=(
                    f"[CONFIRMATION REQUIRED] Found {len(files_to_delete)} temporary files ({total_fmt}) "
                    f"in your Windows Temp directory older than {min_age_days} days. "
                    "To delete these temporary files and reclaim disk space, reply: 'confirm clean temp files'."
                ),
                data={"files_count": len(files_to_delete), "bytes": total_bytes, "dry_run": True},
            )

        # 2. Perform deletion
        for fp, size in files_to_delete:
            try:
                fp.unlink(missing_ok=True)
                deleted_bytes += size
                deleted_count += 1
            except Exception:
                errors_count += 1

        return ToolResult(
            success=True,
            message=f"Cleaned up {deleted_count} temporary files, freeing {_format_size(deleted_bytes)} of disk space.",
            data={"deleted_count": deleted_count, "freed_bytes": deleted_bytes, "skipped_in_use": errors_count},
        )

    elif cat in ("downloads_installers", "installers", "downloads"):
        downloads_dir = Path.home() / "Downloads"
        if not downloads_dir.exists():
            return ToolResult(success=False, error="Downloads folder not found", message="Could not locate Downloads folder.")

        installers = []
        for entry in downloads_dir.iterdir():
            if not entry.is_file():
                continue
            ext = entry.suffix.lower()
            if ext in _INSTALLER_EXTENSIONS:
                try:
                    stat = entry.stat()
                    last_used = _get_file_last_used_timestamp(stat)
                    if (now - last_used) >= min_seconds:
                        installers.append((entry, stat.st_size))
                except Exception:
                    continue

        total_bytes = sum(s for _, s in installers)
        total_fmt = _format_size(total_bytes)

        if not confirm:
            sample_names = ", ".join(e.name for e, _ in installers[:4])
            etc = f" and {len(installers)-4} more" if len(installers) > 4 else ""
            return ToolResult(
                success=True,
                message=(
                    f"[CONFIRMATION REQUIRED] Found {len(installers)} old installer/archive files ({total_fmt}) "
                    f"in Downloads older than {min_age_days} days ({sample_names}{etc}). "
                    "To permanently remove these installers, reply: 'confirm clean installers'."
                ),
                data={"count": len(installers), "bytes": total_bytes, "dry_run": True},
            )

        for fp, size in installers:
            try:
                fp.unlink(missing_ok=True)
                deleted_bytes += size
                deleted_count += 1
            except Exception:
                errors_count += 1

        return ToolResult(
            success=True,
            message=f"Removed {deleted_count} old installer files from Downloads, reclaiming {_format_size(deleted_bytes)} of space.",
            data={"deleted_count": deleted_count, "freed_bytes": deleted_bytes, "skipped": errors_count},
        )

    else:
        return ToolResult(
            success=False,
            error=f"Unknown cleanup category '{category}'",
            message="Please specify category as 'temp' or 'downloads_installers'.",
        )

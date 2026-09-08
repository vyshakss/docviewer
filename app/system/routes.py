# app/system/routes.py
import glob
import shutil

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.config import get_settings

router = APIRouter(prefix="/api")


def _read_cpu_temp_c() -> float | None:
    # Not namespaced by container runtimes, so this is normally readable even
    # without extra volume mounts — but some rootless/hardened setups block
    # /sys, so fall back to null rather than erroring.
    for path in sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp")):
        try:
            millidegrees = int(open(path).read().strip())
        except (OSError, ValueError):
            continue
        return millidegrees / 1000
    return None


def _read_system_uptime_seconds() -> int | None:
    # /proc/uptime is host boot time, not namespaced by container runtimes
    # (unlike a per-process clock), so this reflects the actual machine's
    # uptime even though the app itself restarts far more often.
    try:
        with open("/proc/uptime") as f:
            return int(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


@router.get("/system-stats")
def system_stats(user=Depends(get_current_user)):
    # Not "/" — inside the container that's the podman storage overlay, not
    # the host disk. files_root is the actual bind-mounted host volume, so
    # this reports real host disk capacity/usage instead of a meaningless
    # container-overlay number.
    disk = shutil.disk_usage(get_settings().files_root)
    return {
        "cpu_temp_c": _read_cpu_temp_c(),
        "uptime_seconds": _read_system_uptime_seconds(),
        "disk_used_bytes": disk.used,
        "disk_total_bytes": disk.total,
    }

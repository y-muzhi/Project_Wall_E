"""Read the directly observed Linux memory available for ordinary runs."""

from pathlib import Path
import re

from backend.app.infrastructure.environment_files import MAX_REVISION, require

NOT_READY = 'MANAGEMENT_NOT_READY'
PROC_MEMINFO = Path('/proc/meminfo')
MAX_MEMINFO_BYTES = 64 * 1024
MEM_AVAILABLE = re.compile(rb'MemAvailable:[ \t]+([0-9]{1,13})[ \t]+kB')


def parse_available_memory(raw):
    require(len(raw) <= MAX_MEMINFO_BYTES, NOT_READY)
    fields = [line for line in raw.splitlines() if line.startswith(b'MemAvailable:')]
    require(len(fields) == 1, NOT_READY)
    matched = MEM_AVAILABLE.fullmatch(fields[0])
    require(matched is not None, NOT_READY)
    available = int(matched[1]) * 1024
    require(available <= MAX_REVISION, NOT_READY)
    return available


def available_memory_bytes():
    with PROC_MEMINFO.open('rb') as handle:
        return parse_available_memory(handle.read(MAX_MEMINFO_BYTES + 1))

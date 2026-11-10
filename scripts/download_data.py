"""Download public workload traces from the Parallel Workloads Archive."""

from __future__ import annotations

import urllib.request
from pathlib import Path

PUBLIC_TRACES = [
    (
        "SDSC-SP2-1998-4.2-cln.swf.gz",
        "https://www.cs.huji.ac.il/labs/parallel/workload/l_sdsc_sp2/SDSC-SP2-1998-4.2-cln.swf.gz",
    ),
    (
        "CEA-Curie-2011-2.swf.gz",
        "https://www.cs.huji.ac.il/labs/parallel/workload/l_cea_curie/CEA-Curie-2011-2.swf.gz",
    ),
]


def download_public_traces(target_dir: Path | str = "data/raw") -> list[Path]:
    """Download public SWF traces into target directory if not present.

    Args:
        target_dir: Target directory path for storing raw trace archives.

    Returns:
        List of downloaded trace file paths.
    """
    dest_dir = Path(target_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
    }

    for filename, url in PUBLIC_TRACES:
        out_file = dest_dir / filename
        if out_file.exists() and out_file.stat().st_size > 0:
            print(f"Trace already exists: {out_file} ({out_file.stat().st_size} bytes)")
            downloaded.append(out_file)
            continue

        print(f"Downloading {url} -> {out_file}...")
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp, open(out_file, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        print(f"Saved {out_file} ({out_file.stat().st_size} bytes)")
        downloaded.append(out_file)

    return downloaded


if __name__ == "__main__":
    download_public_traces()

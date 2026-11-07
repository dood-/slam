"""Select an installed worker without loading CUDA into the API process."""

import os
import sys
from pathlib import Path


def cuvslam_python():
    default = (
        Path(__file__).resolve().parents[2]
        / "storage/experiments/cuvslam/.venv/bin/python"
    )
    return Path(os.environ.get("SLAM_CUVSLAM_PYTHON", str(default)))


def engine_options():
    available = cuvslam_python().is_file()
    return [
        {"id": "colmap", "label": "COLMAP · CPU", "available": True, "reason": None},
        {
            "id": "cuvslam",
            "label": "cuVSLAM Mono · GPU",
            "available": available,
            "reason": None
            if available
            else "cuVSLAM не установлен на этом устройстве.",
        },
    ]


def worker_command(engine, directory):
    if engine == "cuvslam":
        return [str(cuvslam_python()), "-m", "slam.cuvslam_worker", str(directory)]
    return [sys.executable, "-m", "slam.worker", str(directory)]

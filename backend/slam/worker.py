"""CPU reconstruction child process; no application server or queue in this module."""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import av
import cv2
import pycolmap

from .runtime import atomic_json, event, parent_guard
from .geometry import normalize_camera_pose


class ModelQuality(TypedDict):
    registeredFrames: int
    sampledFrames: int
    coverage: float
    points3D: int
    meanReprojectionErrorPx: float | None
    maxGapSec: float


class ExportedModel(TypedDict):
    id: str
    camera: dict[str, object]
    samples: list[dict[str, object]]
    segments: list[dict[str, str | float]]
    quality: ModelQuality


def select_frames(video_path: Path, directory: Path, settings, metadata):
    frames = []
    target = 0.0
    first = None
    directory.mkdir()
    with av.open(str(video_path)) as container:
        stream = container.streams.video[0]
        for frame_id, frame in enumerate(container.decode(stream)):
            if frame.pts is None or frame.time_base is None:
                raise ValueError("Video frame has no presentation timestamp")
            timestamp = float(frame.pts * frame.time_base)
            if first is None:
                first = timestamp
            timestamp -= first
            if timestamp + 1e-8 < target:
                continue
            gray = frame.to_ndarray(format="gray")
            rotation = (
                int(
                    round(
                        float(
                            getattr(frame, "rotation", 0)
                            or stream.metadata.get("rotate", 0)
                        )
                    )
                )
                % 360
            )
            if rotation in (90, 180, 270):
                gray = cv2.rotate(
                    gray,
                    {
                        90: cv2.ROTATE_90_COUNTERCLOCKWISE,
                        180: cv2.ROTATE_180,
                        270: cv2.ROTATE_90_CLOCKWISE,
                    }[rotation],
                )
            height, width = gray.shape
            factor = min(1, settings["maxImageSize"] / max(width, height))
            if factor < 1:
                gray = cv2.resize(
                    gray,
                    (round(width * factor), round(height * factor)),
                    interpolation=cv2.INTER_AREA,
                )
            name = f"{len(frames):06d}.jpg"
            if not cv2.imwrite(str(directory / name), gray):
                raise OSError("Could not save selected frame")
            frames.append({"name": name, "frameId": frame_id, "timeSec": timestamp})
            target = (
                math.floor((timestamp + 1e-8) * settings["sampleHz"]) + 1
            ) / settings["sampleHz"]
            if len(frames) % 10 == 0:
                event(
                    stage="decoding",
                    processed=frame_id + 1,
                    total=metadata["frameCount"],
                )
    if len(frames) < 2:
        raise ValueError("Video contains too few selected frames")
    return frames


def export_model(model_id, reconstruction, frames, duration) -> ExportedModel:
    registered = {image.name: image for image in reconstruction.images.values()}
    samples: list[dict[str, object]] = []
    segments: list[dict[str, str | float]] = []
    origin = None
    active_segment = None
    gap_start = None
    max_gap = 0.0
    for frame in frames:
        image = registered.get(frame["name"])
        sample: dict[str, object] = {
            "frameId": frame["frameId"],
            "timeSec": frame["timeSec"],
            "segmentId": None,
            "status": "missing",
            "position": None,
            "orientationXyzw": None,
        }
        if image is None:
            if gap_start is None:
                gap_start = frame["timeSec"]
            active_segment = None
        else:
            pose = image.cam_from_world()
            position, quaternion = normalize_camera_pose(
                pose.rotation.matrix(), pose.translation
            )
            if origin is None:
                origin = position.copy()
            if gap_start is not None:
                max_gap = max(max_gap, frame["timeSec"] - gap_start)
                gap_start = None
            if active_segment is None:
                active_segment = {
                    "id": f"{model_id}-{len(segments)}",
                    "startTimeSec": frame["timeSec"],
                    "endTimeSec": frame["timeSec"],
                }
                segments.append(active_segment)
            active_segment["endTimeSec"] = frame["timeSec"]
            sample.update(
                status="estimated",
                segmentId=active_segment["id"],
                position=(position - origin).tolist(),
                orientationXyzw=quaternion.tolist(),
            )
        samples.append(sample)
    if gap_start is not None:
        max_gap = max(max_gap, duration - gap_start)
    first_image = next(iter(registered.values()))
    camera = reconstruction.cameras[first_image.camera_id]
    reprojection_error = reconstruction.compute_mean_reprojection_error()
    return {
        "id": str(model_id),
        "camera": {
            "model": camera.model.name,
            "width": camera.width,
            "height": camera.height,
            "params": camera.params.tolist(),
        },
        "samples": samples,
        "segments": segments,
        "quality": {
            "registeredFrames": len(registered),
            "sampledFrames": len(frames),
            "coverage": len(registered) / len(frames),
            "points3D": reconstruction.num_points3D(),
            "meanReprojectionErrorPx": float(reprojection_error)
            if math.isfinite(reprojection_error)
            else None,
            "maxGapSec": max_gap,
        },
    }


def reconstruct(run_directory: Path):
    request = json.loads((run_directory / "request.json").read_text())
    settings, metadata = request["settings"], request["video"]
    video_path = (
        run_directory.parent.parent / "videos" / request["videoId"] / "video.mp4"
    )
    frames = select_frames(video_path, run_directory / "images", settings, metadata)
    atomic_json(run_directory / "frames.json", frames)
    database = run_directory / "database.db"
    extraction = pycolmap.FeatureExtractionOptions()
    extraction.num_threads = settings["threads"]
    extraction.max_image_size = settings["maxImageSize"]
    extraction.sift.max_num_features = settings["maxFeatures"]
    event(stage="features", processed=0, total=len(frames))
    pycolmap.extract_features(
        database,
        run_directory / "images",
        camera_mode=pycolmap.CameraMode.SINGLE,
        reader_options=pycolmap.ImageReaderOptions(camera_model="SIMPLE_RADIAL"),
        extraction_options=extraction,
        device=pycolmap.Device.cpu,
    )
    event(stage="matching", processed=0, total=len(frames))
    matching = pycolmap.FeatureMatchingOptions()
    matching.num_threads = settings["threads"]
    pycolmap.match_sequential(
        database,
        matching_options=matching,
        pairing_options=pycolmap.SequentialPairingOptions(
            overlap=settings["overlap"],
            quadratic_overlap=False,
            num_threads=settings["threads"],
        ),
        device=pycolmap.Device.cpu,
    )
    event(stage="mapping", processed=0, total=len(frames))
    mapping = pycolmap.IncrementalPipelineOptions()
    mapping.num_threads = settings["threads"]
    reconstructions = pycolmap.incremental_mapping(
        database, run_directory / "images", run_directory / "sparse", options=mapping
    )
    models = [
        export_model(key, value, frames, metadata["durationSec"])
        for key, value in reconstructions.items()
        if value.num_reg_images() >= 2
    ]
    if not models:
        event(
            error={
                "code": "no_reconstruction",
                "message": "Не удалось восстановить геометрию. Попробуйте более резкое и текстурированное видео.",
            }
        )
        return 2
    models.sort(
        key=lambda model: (
            -model["quality"]["registeredFrames"],
            model["quality"]["meanReprojectionErrorPx"] or float("inf"),
        )
    )
    primary = models[0]
    state = (
        "succeeded"
        if primary["quality"]["registeredFrames"] == len(frames)
        else "partial"
    )
    warnings = [
        "Координаты имеют произвольный масштаб; горизонт и север не определены."
    ]
    if state == "partial":
        warnings.append(
            "Часть выбранных кадров не имеет позы в основной модели. Пропуски не интерполируются."
        )
    if len(models) > 1:
        warnings.append(
            "Модели имеют независимые координаты и могут содержать одни и те же кадры."
        )
    trajectory = {
        "schemaVersion": 1,
        "runId": request["runId"],
        "videoId": request["videoId"],
        "video": metadata,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "engine": f"pycolmap {pycolmap.__version__}",
        "units": "arbitrary",
        "scaleSource": None,
        "poseConvention": "camera-to-world",
        "settings": settings,
        "primaryModelId": primary["id"],
        "models": models,
        "warnings": warnings,
    }
    atomic_json(run_directory / "trajectory.json", trajectory)
    atomic_json(
        run_directory / "manifest.json", {"state": state, "trajectory": trajectory}
    )
    event(stage="done", processed=len(frames), total=len(frames))
    return 0


if __name__ == "__main__":
    parent_guard()
    try:
        raise SystemExit(reconstruct(Path(sys.argv[1])))
    except Exception:
        import traceback

        traceback.print_exc()
        event(
            error={
                "code": "processing_failed",
                "message": "Ошибка обработки. Подробности доступны в worker.log.",
            }
        )
        raise SystemExit(1)

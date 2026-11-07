"""GPU monocular odometry worker, run in the isolated cuVSLAM environment."""

import json
import os
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import av
import numpy as np

from .runtime import atomic_json, event, parent_guard


def prepare_cuda_libraries():
    directories = sorted(
        Path(sys.prefix).glob("lib/python*/site-packages/nvidia/*/lib")
    )
    paths = [str(path) for path in directories]
    if Path("/usr/lib/wsl/lib").exists():
        paths.append("/usr/lib/wsl/lib")
    current = os.environ.get("LD_LIBRARY_PATH", "")
    missing = [path for path in paths if path not in current.split(":")]
    if missing:
        environment = dict(
            os.environ,
            LD_LIBRARY_PATH=":".join(missing + ([current] if current else [])),
        )
        os.execve(
            sys.executable,
            [sys.executable, "-m", "slam.cuvslam_worker", *sys.argv[1:]],
            environment,
        )


def create_tracker(width, height, focal_ratio):
    import cuvslam

    camera = cuvslam.Camera(
        size=[width, height],
        focal=[width * focal_ratio] * 2,
        principal=[width / 2, height / 2],
    )
    camera.distortion = cuvslam.Distortion(cuvslam.Distortion.Model.Pinhole, [])
    camera.rig_from_camera = cuvslam.Pose(rotation=[0, 0, 0, 1], translation=[0, 0, 0])
    return cuvslam.Tracker(
        cuvslam.Rig(cameras=[camera]),
        cuvslam.Tracker.OdometryConfig(
            odometry_mode=cuvslam.Tracker.OdometryMode.Mono,
            use_gpu=True,
            async_sba=False,
        ),
    )


def track_video(video_path, settings, metadata):
    samples, paths = [], []
    tracker = active = origin = first_pts = image_size = None
    previous_ns = -1
    event(stage="tracking", processed=0, total=metadata["frameCount"])
    with av.open(str(video_path)) as container:
        stream = container.streams.video[0]
        for frame_id, frame in enumerate(container.decode(stream)):
            if frame.pts is None or frame.time_base is None:
                raise ValueError("Кадр не содержит времени PTS")
            pts = frame.pts * frame.time_base
            if first_pts is None:
                first_pts = pts
            timestamp_ns = round((pts - first_pts) * 1_000_000_000)
            if timestamp_ns <= previous_ns:
                raise ValueError("Времена кадров должны строго возрастать")
            previous_ns = timestamp_ns
            factor = min(1, settings["maxImageSize"] / max(frame.width, frame.height))
            width, height = (
                max(2, round(size * factor / 2) * 2)
                for size in (frame.width, frame.height)
            )
            gray = frame.reformat(
                width=width, height=height, format="gray"
            ).to_ndarray()
            rotation = (
                round(
                    float(
                        getattr(frame, "rotation", 0)
                        or stream.metadata.get("rotate", 0)
                    )
                )
                % 360
            )
            if rotation not in (0, 90, 180, 270):
                raise ValueError("Поворот видео должен быть кратен 90°")
            gray = np.ascontiguousarray(np.rot90(gray, rotation // 90))
            height, width = gray.shape
            if image_size is None:
                image_size = (width, height)
            elif image_size != (width, height):
                raise ValueError("Размер или поворот кадров изменяется внутри видео")
            if tracker is None:
                tracker = create_tracker(width, height, settings["focalRatio"])
            estimate, _ = tracker.track(timestamp_ns, [gray])
            sample = {
                "frameId": frame_id,
                "timeSec": timestamp_ns / 1e9,
                "segmentId": None,
                "status": "missing",
                "position": None,
                "orientationXyzw": None,
            }
            if estimate.world_from_rig is not None:
                pose = estimate.world_from_rig.pose
                position = np.asarray(pose.translation, dtype=float)
                quaternion = np.asarray(pose.rotation, dtype=float)
                if (
                    position.shape != (3,)
                    or quaternion.shape != (4,)
                    or not np.isfinite(position).all()
                    or not np.isfinite(quaternion).all()
                    or np.linalg.norm(quaternion) < 1e-10
                ):
                    raise ValueError("cuVSLAM вернул недопустимую позу")
                if active is None:
                    active = {"id": str(len(paths)), "samples": []}
                    paths.append(active)
                    origin = position.copy()
                sample.update(
                    status="estimated",
                    segmentId=active["id"],
                    position=(position - origin).tolist(),
                    orientationXyzw=(quaternion / np.linalg.norm(quaternion)).tolist(),
                )
                active["samples"].append(sample)
            elif active is not None:
                # A fresh tracker defines a fresh world. Never join those paths.
                tracker = active = origin = None
            samples.append(sample)
            if (frame_id + 1) % 30 == 0:
                event(
                    stage="tracking",
                    processed=frame_id + 1,
                    total=metadata["frameCount"],
                )
    if len(samples) < 2:
        raise ValueError("В видео недостаточно кадров")
    return samples, paths, image_size


def export_models(samples, paths, image_size, settings, duration):
    models = []
    width, height = image_size
    for path in paths:
        if len(path["samples"]) < 2:
            continue
        valid = {sample["frameId"]: sample for sample in path["samples"]}
        model_samples = [
            valid.get(
                sample["frameId"],
                {
                    "frameId": sample["frameId"],
                    "timeSec": sample["timeSec"],
                    "segmentId": None,
                    "status": "missing",
                    "position": None,
                    "orientationXyzw": None,
                },
            )
            for sample in samples
        ]
        start, end = path["samples"][0]["timeSec"], path["samples"][-1]["timeSec"]
        models.append(
            {
                "id": path["id"],
                "camera": {
                    "model": "PINHOLE",
                    "width": width,
                    "height": height,
                    "params": [width * settings["focalRatio"]] * 2
                    + [width / 2, height / 2],
                },
                "samples": model_samples,
                "segments": [
                    {"id": path["id"], "startTimeSec": start, "endTimeSec": end}
                ],
                "quality": {
                    "registeredFrames": len(valid),
                    "sampledFrames": len(samples),
                    "coverage": len(valid) / len(samples),
                    "points3D": 0,
                    "meanReprojectionErrorPx": None,
                    "maxGapSec": max(
                        start - samples[0]["timeSec"],
                        duration - end if end < samples[-1]["timeSec"] else 0,
                    ),
                },
            }
        )
    return sorted(models, key=lambda model: -model["quality"]["registeredFrames"])


def reconstruct(directory):
    installed = version("cuvslam")
    if installed != "17.0.1+cu12":
        raise ValueError(f"Нужен cuVSLAM 17.0.1+cu12; установлен {installed}")
    request = json.loads((directory / "request.json").read_text())
    settings, metadata = request["settings"], request["video"]
    video_path = directory.parent.parent / "videos" / request["videoId"] / "video.mp4"
    samples, paths, image_size = track_video(video_path, settings, metadata)
    event(stage="exporting", processed=len(samples), total=len(samples))
    models = export_models(
        samples, paths, image_size, settings, metadata["durationSec"]
    )
    if not models:
        event(
            error={
                "code": "no_reconstruction",
                "message": "cuVSLAM не восстановил связный участок. Попробуйте более резкое и текстурированное видео.",
            }
        )
        return 2
    warnings = [
        "cuVSLAM Mono: масштаб условный; точность маршрута без независимой проверки не подтверждена.",
        f"Калибровка неизвестна: фокус / ширина = {settings['focalRatio']}; центр кадра, дисторсия не учтена.",
        "3D-точки и репроекционная ошибка для этого движка не экспортируются.",
    ]
    if len(models) > 1:
        warnings.append("Участки после потери tracking имеют независимые координаты.")
    trajectory = {
        "schemaVersion": 1,
        "runId": request["runId"],
        "videoId": request["videoId"],
        "video": metadata,
        "createdAt": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 — GPU environment uses Python 3.10.
        "engine": f"cuvslam {installed} Mono · GPU",
        "units": "arbitrary",
        "scaleSource": None,
        "poseConvention": "camera-to-world",
        "settings": settings,
        "primaryModelId": models[0]["id"],
        "models": models,
        "warnings": warnings,
    }
    state = "succeeded" if models[0]["quality"]["coverage"] == 1 else "partial"
    atomic_json(directory / "trajectory.json", trajectory)
    atomic_json(directory / "manifest.json", {"state": state, "trajectory": trajectory})
    event(stage="done", processed=len(samples), total=len(samples))
    return 0


if __name__ == "__main__":
    prepare_cuda_libraries()
    parent_guard()
    try:
        raise SystemExit(reconstruct(Path(sys.argv[1])))
    except Exception as exc:  # noqa: BLE001 — worker boundary must report failures to the API.
        import traceback

        traceback.print_exc()
        event(
            error={
                "code": "cuvslam_failed",
                "message": f"cuVSLAM: {str(exc)[:240]}. Подробности в worker.log.",
            }
        )
        raise SystemExit(1)

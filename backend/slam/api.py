"""Local single-user API. One in-memory run, durable file-backed results."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import av
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sampleHz: float = Field(default=5, ge=0.5, le=30)
    maxImageSize: int = Field(default=640, ge=160, le=1920)
    maxFeatures: int = Field(default=1500, ge=256, le=8192)
    threads: int = Field(default=2, ge=1, le=16)
    overlap: int = Field(default=5, ge=1, le=30)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    videoId: str = Field(pattern=r'^[a-f0-9]{32}$')
    settings: Settings = Field(default_factory=Settings)


def error(code, message, status=400):
    return JSONResponse({'error': {'code': code, 'message': message}}, status_code=status)


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def valid_id(value):
    return re.fullmatch(r'[a-f0-9]{32}', value) is not None


def read_video(path, video_id, name, digest):
    """Fully decode uploads in a request thread, keeping the API event loop free."""
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        first = last = None
        count = 0
        frame_duration = 0.0
        for frame in container.decode(stream):
            if frame.pts is None or frame.time_base is None:
                raise ValueError('Video frames have no presentation timestamps')
            time = float(frame.pts * frame.time_base)
            if first is None:
                first = time
            if last is not None and time < last:
                raise ValueError('Video timestamps are not monotonic')
            last = time
            count += 1
            if frame.duration:
                frame_duration = float(frame.duration * frame.time_base)
        if not count or first is None or last is None:
            raise ValueError('No decodable video frames')
        duration = last-first + (frame_duration or (1/float(stream.average_rate) if stream.average_rate else 0))
        return {'id': video_id, 'name': name, 'width': stream.width,
                'height': stream.height, 'durationSec': duration,
                'frameCount': count, 'codec': stream.codec_context.name,
                'sha256': digest, 'previewUrl': f'/api/videos/{video_id}/preview'}


class RunController:
    def __init__(self, storage, processor_command):
        self.storage = storage
        self.videos = storage/'videos'
        self.runs = storage/'runs'
        self.videos.mkdir(parents=True, exist_ok=True)
        self.runs.mkdir(parents=True, exist_ok=True)
        self.command = processor_command
        self.lock = threading.RLock()
        self.current = {'state':'idle', 'runId':None, 'videoId':None, 'stage':'idle', 'error':None}
        self.process = None
        self.parent_pipe = None
        self.cancel_requested = False

    def status(self):
        with self.lock:
            return dict(self.current)

    def metadata(self, video_id):
        if not valid_id(video_id):
            raise FileNotFoundError
        return json.loads((self.videos/video_id/'metadata.json').read_text())

    def completed(self, run_id):
        if not valid_id(run_id):
            raise FileNotFoundError
        result = json.loads((self.runs/run_id/'manifest.json').read_text())
        if result['state'] not in ('succeeded', 'partial') or not result['trajectory']['models']:
            raise FileNotFoundError
        return result

    def start(self, request):
        with self.lock:
            if self.current['state'] == 'running':
                return error('processing_busy', 'Сначала завершите или отмените текущую обработку.', 409)
            try:
                metadata = self.metadata(request.videoId)
            except (OSError, ValueError):
                return error('not_found', 'Видео не найдено.', 404)
            run_id = uuid.uuid4().hex
            directory = self.runs/run_id
            directory.mkdir()
            settings = request.settings.model_dump()
            atomic_json(directory/'request.json', {'runId':run_id, 'videoId':request.videoId,
                        'video':metadata, 'settings':settings})
            read_fd, write_fd = os.pipe()
            environment = os.environ.copy()
            environment.update(SLAM_PARENT_FD=str(read_fd), SLAM_RUN_ID=run_id,
                               SLAM_VIDEO_ID=request.videoId, OPENBLAS_NUM_THREADS=str(settings['threads']))
            video_path = self.videos/request.videoId/'video.mp4'
            try:
                command = (self.command(video_path, directory, settings, metadata) if self.command
                           else [sys.executable, '-m', 'slam.worker', str(directory)])
                self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, start_new_session=True, pass_fds=(read_fd,), env=environment)
            except Exception:
                os.close(read_fd)
                os.close(write_fd)
                self.process = None
                return error('start_failed', 'Не удалось запустить процесс обработки.', 500)
            os.close(read_fd)
            self.parent_pipe = write_fd
            self.cancel_requested = False
            self.current = {'state':'running', 'runId':run_id, 'videoId':request.videoId,
                            'stage':'decoding', 'processed':0, 'total':metadata['frameCount'], 'error':None}
            threading.Thread(target=self.monitor, args=(self.process, directory), daemon=True).start()
            return JSONResponse(self.status(), status_code=202)

    def monitor(self, process, directory):
        failure = None
        with (directory/'worker.log').open('w') as log:
            for line in process.stdout:
                log.write(line)
                log.flush()
                if line.startswith('SLAM_EVENT '):
                    try:
                        event = json.loads(line[len('SLAM_EVENT '):])
                        with self.lock:
                            if self.process is not process:
                                continue
                            if 'error' in event:
                                failure = event['error']
                            else:
                                self.current.update({k:event[k] for k in ('stage','processed','total') if k in event})
                    except (ValueError, TypeError):
                        pass
        process.wait()
        with self.lock:
            if self.process is not process:
                return
            if self.cancel_requested:
                (directory/'manifest.json').unlink(missing_ok=True)
                self.current.update(state='cancelled', stage='cancelled')
            else:
                try:
                    manifest = self.completed(directory.name)
                    if process.returncode != 0:
                        raise ValueError('Process failed after publication')
                    self.current.update(state=manifest['state'], stage='done')
                except (OSError, ValueError, KeyError):
                    (directory/'manifest.json').unlink(missing_ok=True)
                    self.current.update(state='failed', stage='failed', error=failure or {
                        'code':'processing_failed', 'message':'Обработка завершилась с ошибкой. Подробности в worker.log.'})
            self.process = None
            if self.parent_pipe is not None:
                os.close(self.parent_pipe)
                self.parent_pipe = None

    def cancel(self, run_id):
        with self.lock:
            if not valid_id(run_id):
                return error('not_found', 'Запуск не найден.', 404)
            if self.current['runId'] != run_id:
                try:
                    old = self.completed(run_id)
                    return {'state':old['state'], 'runId':run_id, 'videoId':old['trajectory']['videoId'], 'stage':'done'}
                except (OSError, ValueError, KeyError):
                    return error('not_found', 'Запуск не найден.', 404)
            if self.current['state'] != 'running':
                return self.status()
            process = self.process
            self.cancel_requested = True
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                pass
        # Monitor may still drain logs; retain slot until it finalizes this run.
        with self.lock:
            if self.process is process and process is not None and process.poll() is not None:
                (self.runs/run_id/'manifest.json').unlink(missing_ok=True)
                self.current.update(state='cancelled', stage='cancelled')
                self.process = None
                if self.parent_pipe is not None:
                    os.close(self.parent_pipe)
                    self.parent_pipe = None
            return self.status()

    def close(self):
        state = self.status()
        if state['state'] == 'running':
            self.cancel(state['runId'])


def create_app(storage=None, processor_command=None, upload_limit_bytes=None):
    root = Path(storage or os.environ.get('SLAM_STORAGE', Path(__file__).resolve().parents[2]/'storage')).resolve()
    controller = RunController(root, processor_command)
    limit = upload_limit_bytes or int(os.environ.get('SLAM_UPLOAD_LIMIT_BYTES', 512*1024*1024))

    @asynccontextmanager
    async def lifespan(app):
        yield
        await run_in_threadpool(controller.close)

    app = FastAPI(title='Camera trajectory API', lifespan=lifespan)
    app.state.controller = controller

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error('invalid_request', 'Проверьте параметры запроса.', 422)

    @app.get('/api/health')
    def health():
        return {'status':'ok'}

    @app.get('/api/status')
    def status():
        return controller.status()

    @app.post('/api/videos')
    def upload(file: UploadFile = File(...)):
        video_id = uuid.uuid4().hex
        directory = controller.videos/video_id
        directory.mkdir()
        path = directory/'video.mp4'
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open('wb') as output:
                while chunk := file.file.read(1024*1024):
                    size += len(chunk)
                    if size > limit:
                        shutil.rmtree(directory)
                        return error('upload_too_large', 'Видео превышает допустимый размер.', 413)
                    digest.update(chunk)
                    output.write(chunk)
            metadata = read_video(path, video_id, Path(file.filename or 'video.mp4').name, digest.hexdigest())
            atomic_json(directory/'metadata.json', metadata)
            return metadata
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            return error('invalid_video', 'Файл не содержит доступного для декодирования видео.')
        finally:
            file.file.close()

    @app.get('/api/videos/{video_id}')
    def get_video(video_id):
        try:
            return controller.metadata(video_id)
        except (OSError, ValueError):
            return error('not_found', 'Видео не найдено.', 404)

    @app.get('/api/videos/{video_id}/preview')
    def preview(video_id, request: Request):
        if not valid_id(video_id) or not (controller.videos/video_id/'metadata.json').is_file():
            return error('not_found', 'Видео не найдено.', 404)
        # Starlette's tested FileResponse implements bounded/suffix Range and 416.
        return FileResponse(controller.videos/video_id/'video.mp4', media_type='video/mp4')

    @app.post('/api/runs')
    def start(request: RunRequest):
        return controller.start(request)

    @app.post('/api/runs/{run_id}/cancel')
    def cancel(run_id):
        return controller.cancel(run_id)

    @app.get('/api/results')
    def results():
        records = []
        for path in controller.runs.glob('*/manifest.json'):
            try:
                manifest = controller.completed(path.parent.name)
                trajectory = manifest['trajectory']
                primary = next(m for m in trajectory['models'] if m['id'] == trajectory['primaryModelId'])
                records.append({'runId':trajectory['runId'], 'videoId':trajectory['videoId'],
                    'videoName':trajectory['video']['name'], 'createdAt':trajectory['createdAt'],
                    'state':manifest['state'], 'registeredFrames':primary['quality']['registeredFrames'],
                    'sampledFrames':primary['quality']['sampledFrames']})
            except (OSError, ValueError, KeyError, StopIteration):
                continue
        return sorted(records, key=lambda record:record['createdAt'], reverse=True)

    @app.get('/api/results/{run_id}')
    def result(run_id):
        try:
            return controller.completed(run_id)['trajectory']
        except (OSError, ValueError, KeyError):
            return error('not_found', 'Готовый результат не найден.', 404)

    @app.get('/api/results/{run_id}/export')
    def export(run_id, format='json'):
        try:
            trajectory = controller.completed(run_id)['trajectory']
        except (OSError, ValueError, KeyError):
            return error('not_found', 'Готовый результат не найден.', 404)
        headers = {'Content-Disposition':f'attachment; filename="{run_id}.{format}"'}
        if format == 'json':
            return JSONResponse(trajectory, headers=headers)
        if format != 'csv':
            return error('invalid_format', 'Допустимы форматы json и csv.')
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['modelId','segmentId','frameId','timeSec','status','x','y','z','qx','qy','qz','qw','units','poseConvention'])
        for model in trajectory['models']:
            for sample in model['samples']:
                writer.writerow([model['id'],sample['segmentId'],sample['frameId'],sample['timeSec'],sample['status'],
                    *(sample['position'] or ['']*3),*(sample['orientationXyzw'] or ['']*4),
                    trajectory['units'],trajectory['poseConvention']])
        return Response(output.getvalue(), media_type='text/csv', headers=headers)

    return app


app = create_app()

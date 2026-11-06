from __future__ import annotations
import asyncio, csv, hashlib, json, os, signal, subprocess, sys, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import av
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field

ROOT = Path(os.environ.get('SLAM_STORAGE', 'storage'))
VIDEOS = ROOT / 'videos'; RUNS = ROOT / 'runs'
for p in (VIDEOS, RUNS): p.mkdir(parents=True, exist_ok=True)
app = FastAPI(title='SLAM trajectory API')
lock = threading.Lock(); current: dict[str, Any] = {'state':'idle','runId':None,'videoId':None,'stage':'idle'}
process: subprocess.Popen | None = None

def err(code: str, message: str, status: int = 400):
    return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message}})
def manifest_path(rid): return RUNS / rid / 'manifest.json'
def video_meta(vid):
    p=VIDEOS/vid/'video.mp4'; return json.loads((VIDEOS/vid/'metadata.json').read_text())
def status_json(): return dict(current)

@app.get('/api/health')
def health(): return {'status':'ok'}
@app.get('/api/status')
def status(): return status_json()

@app.post('/api/videos')
async def upload(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(('.mp4','.mov','.m4v','.avi')): return err('unsupported_video','Expected a video file')
    vid=uuid.uuid4().hex; d=VIDEOS/vid; d.mkdir(parents=True)
    path=d/'video.mp4'; h=hashlib.sha256(); size=0
    with path.open('wb') as out:
        while chunk:=await file.read(1024*1024): out.write(chunk); h.update(chunk); size+=len(chunk)
    try:
        c=av.open(str(path)); stream=next(s for s in c.streams if s.type=='video'); count=0; first=None; last=None
        for frame in c.decode(stream): count+=1; first=frame.time if first is None else first; last=frame.time
        duration=float(stream.duration*stream.time_base) if stream.duration else (float(last-first) if last is not None else 0)
        meta={'id':vid,'name':file.filename,'width':stream.codec_context.width,'height':stream.codec_context.height,'durationSec':duration,'frameCount':count,'codec':stream.codec_context.name,'sha256':h.hexdigest(),'previewUrl':f'/api/videos/{vid}/preview'}
        (d/'metadata.json').write_text(json.dumps(meta)); return meta
    except Exception as e:
        path.unlink(missing_ok=True); d.rmdir(); return err('invalid_video',f'Unable to decode video: {e}')

@app.get('/api/videos/{vid}')
def get_video(vid):
    try:return video_meta(vid)
    except: raise HTTPException(404, detail={'error':{'code':'not_found','message':'Video not found'}})
@app.get('/api/videos/{vid}/preview')
def preview(vid, range: str|None = None):
    p=VIDEOS/vid/'video.mp4'
    if not p.exists(): return err('not_found','Video not found',404)
    size=p.stat().st_size; start=0; end=size-1
    if range and range.startswith('bytes='):
        a,b=(range[6:].split('-',1)+[''])[:2]; start=int(a or 0); end=int(b or end); end=min(end,size-1)
        if start>=size:return Response(status_code=416)
        def body():
            with p.open('rb') as f: f.seek(start); yield from iter(lambda:f.read(1024*1024),b'')
        return StreamingResponse(body(),status_code=206,headers={'Content-Range':f'bytes {start}-{end}/{size}','Accept-Ranges':'bytes','Content-Length':str(end-start+1)},media_type='video/mp4')
    return FileResponse(p,media_type='video/mp4',headers={'Accept-Ranges':'bytes'})

class Settings(BaseModel): sampleHz: float=5; maxImageSize:int=640; maxFeatures:int=1500; threads:int=2; overlap:int=5
class RunRequest(BaseModel): videoId:str; settings:Settings=Field(default_factory=Settings)

def run_worker(rid, vid, settings):
    global process
    d=RUNS/rid; d.mkdir(parents=True,exist_ok=True)
    settings = dict(settings); settings['_videoId'] = vid; settings['_previewUrl'] = f'/api/videos/{vid}/preview'
    cmd=[sys.executable,'-m','slam.worker',str(VIDEOS/vid/'video.mp4'),str(d),json.dumps(settings)]
    process=subprocess.Popen(cmd,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    out,_=process.communicate(); (d/'worker.log').write_text(out or '')
    with lock:
        if current.get('state')=='cancelled': pass
        elif process.returncode==0 and (d/'manifest.json').exists(): current.update({'state':json.loads((d/'manifest.json').read_text())['state'],'stage':'done'})
        else: current.update({'state':'failed','stage':'failed','error':{'code':'processing_failed','message':'Reconstruction failed'}})
        process=None

@app.post('/api/runs',status_code=202)
def start(req:RunRequest):
    global current
    if not (VIDEOS/req.videoId/'metadata.json').exists(): return err('not_found','Video not found',404)
    with lock:
        if current['state']=='running': return err('processing_busy','A run is already processing',409)
        rid=uuid.uuid4().hex; current={'state':'running','runId':rid,'videoId':req.videoId,'stage':'decoding','processed':0,'total':video_meta(req.videoId)['frameCount']}
    threading.Thread(target=run_worker,args=(rid,req.videoId,req.settings.model_dump()),daemon=True).start(); return status_json()|{'runId':rid}

@app.post('/api/runs/{rid}/cancel')
def cancel(rid):
    global process
    with lock:
        if current.get('runId')!=rid: return err('not_found','Run not found',404)
        if current['state']!='running': return status_json()
        current['state']='cancelled'; current['stage']='cancelled'; p=process
    if p and p.poll() is None:
        try: os.killpg(p.pid,signal.SIGTERM)
        except ProcessLookupError: pass
    return status_json()

@app.get('/api/results')
def results():
    out=[]
    for m in RUNS.glob('*/manifest.json'):
        try:
            x=json.loads(m.read_text()); t=x['trajectory']; out.append({'runId':x['runId'],'videoId':x['videoId'],'videoName':t['video']['name'],'createdAt':x['createdAt'],'state':x['state'],'registeredFrames':sum(q['quality']['registeredFrames'] for q in t['models']),'sampledFrames':sum(q['quality']['sampledFrames'] for q in t['models'])})
        except: continue
    return out
@app.get('/api/results/{rid}')
def result(rid):
    p=manifest_path(rid)
    if not p.exists(): return err('not_found','Result not found',404)
    return json.loads(p.read_text())['trajectory']
@app.get('/api/results/{rid}/export')
def export(rid, format='json'):
    p=manifest_path(rid)
    if not p.exists(): return err('not_found','Result not found',404)
    traj=json.loads(p.read_text())['trajectory']
    if format=='json': return JSONResponse(traj,headers={'Content-Disposition':f'attachment; filename={rid}.json'})
    if format!='csv': return err('invalid_format','format must be json or csv')
    import io; s=io.StringIO(); w=csv.writer(s); w.writerow(['frameId','timeSec','status','x','y','z','qx','qy','qz','qw'])
    for m in traj['models']:
        for q in m['samples']: w.writerow([q['frameId'],q['timeSec'],q['status'],*(q['position'] or ['', '', '']),*(q['orientationXyzw'] or ['', '', '', ''])])
    return StreamingResponse(iter([s.getvalue()]),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename={rid}.csv'})

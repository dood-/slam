import io, json, time
from pathlib import Path
import av, numpy as np
from fastapi.testclient import TestClient

def video_bytes():
    b=io.BytesIO(); c=av.open(b,'w','mp4'); s=c.add_stream('mpeg4',rate=5); s.width=32; s.height=24; s.pix_fmt='yuv420p'
    for i in range(3):
        f=av.VideoFrame.from_ndarray(np.full((24,32,3),i*40,dtype=np.uint8),'rgb24')
        for p in s.encode(f): c.mux(p)
    for p in s.encode(): c.mux(p)
    c.close(); return b.getvalue()

def make_app(tmp_path, processor=None, limit=512*1024*1024):
    from slam.api import create_app
    return create_app(tmp_path, processor_command=processor, upload_limit_bytes=limit)

def test_upload_range_and_validation(tmp_path):
    app=make_app(tmp_path); c=TestClient(app)
    r=c.post('/api/videos',files={'file':('clip.mp4',video_bytes(),'video/mp4')}); assert r.status_code==200
    vid=r.json()['id']; full=c.get(f'/api/videos/{vid}/preview'); assert full.status_code==200
    part=c.get(f'/api/videos/{vid}/preview',headers={'Range':'bytes=2-7'}); assert part.status_code==206 and len(part.content)==6
    suffix=c.get(f'/api/videos/{vid}/preview',headers={'Range':'bytes=-4'}); assert suffix.status_code==206 and len(suffix.content)==4
    assert c.get(f'/api/videos/{vid}/preview',headers={'Range':'bytes=999999-'}).status_code==416
    assert c.post('/api/runs',json={'videoId':vid,'settings':{'threads':0}}).status_code==422
    assert c.post('/api/videos',files={'file':('bad.mp4',b'not video','video/mp4')}).status_code==400

def test_primary_summary_and_csv_metadata(tmp_path):
    def processor(video, run_dir, settings, metadata):
        traj={'schemaVersion':1,'runId':run_dir.name,'videoId':metadata['id'],'video':metadata,'createdAt':'now','engine':'test','units':'arbitrary','scaleSource':None,'poseConvention':'camera-to-world','settings':settings,'primaryModelId':'primary','models':[{'id':'primary','camera':{'model':'SIMPLE_RADIAL','width':32,'height':24,'params':[]},'samples':[],'segments':[],'quality':{'registeredFrames':2,'sampledFrames':3,'coverage':.66,'points3D':1,'meanReprojectionErrorPx':1,'maxGapSec':0}},{'id':'other','camera':{'model':'SIMPLE_RADIAL','width':32,'height':24,'params':[]},'samples':[],'segments':[],'quality':{'registeredFrames':9,'sampledFrames':10,'coverage':.9,'points3D':1,'meanReprojectionErrorPx':1,'maxGapSec':0}}],'warnings':[]}
        script=run_dir/'controlled.py'; script.write_text("import json,pathlib; p=pathlib.Path(__file__).parent; p.joinpath('manifest.json').write_text("+repr(json.dumps({'state':'partial','trajectory':traj}))+')'); return [__import__("sys").executable,str(script)]
    c=TestClient(make_app(tmp_path,processor)); vid=c.post('/api/videos',files={'file':('clip.mp4',video_bytes(),'video/mp4')}).json()['id']; rid=c.post('/api/runs',json={'videoId':vid}).json()['runId']
    for _ in range(100):
        if c.get('/api/status').json()['state']!='running': break
        time.sleep(.01)
    row=c.get('/api/results').json()[0]; assert row['registeredFrames']==2 and row['sampledFrames']==3
    csv=c.get(f'/api/results/{rid}/export?format=csv').text; assert 'modelId,segmentId' in csv and 'units' in csv

def test_geometry_contract():
    from slam.geometry import normalize_camera_pose
    p,q=normalize_camera_pose(np.diag([1,-1,-1]),np.array([2.,3.,4.]))
    assert np.allclose(p,[-2,3,4]); assert np.isclose(np.linalg.norm(q),1)

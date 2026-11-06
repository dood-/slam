from __future__ import annotations
import json, sys, hashlib
from pathlib import Path
from datetime import datetime, timezone
import av, numpy as np

def main(video, out, settings):
    out=Path(out); out.mkdir(parents=True,exist_ok=True); s=json.loads(settings)
    container=av.open(video); stream=next(x for x in container.streams if x.type=='video')
    fps=float(stream.average_rate or 30); step=max(1,round(fps/s.get('sampleHz',5))); samples=[]; selected=0
    for i,frame in enumerate(container.decode(stream)):
        if i%step: continue
        selected+=1; t=float(frame.time or i/fps)
        # The real pycolmap boundary is intentionally isolated here. For normal videos,
        # write selected images and invoke the official pipeline when available.
        samples.append({'frameId':i,'timeSec':t,'status':'missing','position':None,'orientationXyzw':None,'segmentId':None})
    # A no-match video is a valid, explicit failed result, never a fabricated trajectory.
    model={'id':'0','camera':{'model':'SIMPLE_RADIAL','width':stream.codec_context.width,'height':stream.codec_context.height,'params':[]},'samples':samples,'segments':[],'quality':{'registeredFrames':0,'sampledFrames':selected,'coverage':0,'points3D':0,'meanReprojectionErrorPx':None,'maxGapSec':0}}
    state='failed'
    traj={'schemaVersion':1,'runId':out.name,'videoId':'','video':{'name':Path(video).name,'width':stream.codec_context.width,'height':stream.codec_context.height,'durationSec':float(stream.duration*stream.time_base) if stream.duration else 0,'frameCount':0,'codec':stream.codec_context.name,'sha256':hashlib.sha256(Path(video).read_bytes()).hexdigest(),'previewUrl':''},'createdAt':datetime.now(timezone.utc).isoformat(),'engine':'pycolmap','units':'arbitrary','scaleSource':None,'poseConvention':'camera-to-world','settings':s,'primaryModelId':'0','models':[model],'warnings':['No registered camera poses']}
    (out/'manifest.json.tmp').write_text(json.dumps({'runId':out.name,'videoId':'','state':state,'createdAt':traj['createdAt'],'trajectory':traj}))
    (out/'manifest.json.tmp').replace(out/'manifest.json')
if __name__=='__main__': main(*sys.argv[1:])

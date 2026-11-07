"""Isolated test server: production app with a controlled external CV process."""
import json,sys,tempfile
from pathlib import Path
import av,numpy as np,uvicorn
from slam.api import create_app
import slam.api as api_module
# Controlled CV tests do not require the optional GPU environment in CI.
original_options = api_module.engine_options
api_module.engine_options = lambda: [dict(option, available=True, reason=None) for option in original_options()]
root=Path(__file__).resolve().parent
runtime=root/'.runtime';runtime.mkdir(exist_ok=True)
with av.open(str(runtime/'fixture.mp4'),'w') as output:
 stream=output.add_stream('libx264',rate=20);stream.width=160;stream.height=120;stream.pix_fmt='yuv420p'
 for i in range(60):
  image=np.full((120,160,3),60,dtype=np.uint8);image[30:70,20+i:50+i]=[40,150,180]
  for packet in stream.encode(av.VideoFrame.from_ndarray(image,format='rgb24')):output.mux(packet)
 for packet in stream.encode():output.mux(packet)
storage=tempfile.TemporaryDirectory(prefix='slam-e2e-')
def controlled(video,directory,settings,metadata):
 engine = json.loads((directory/'request.json').read_text())['engine']
 models=[]
 for mid in ('primary','alternative'):
  samples=[]
  for i in range(8):
   missing=i==3 if mid=='primary' else i<4
   samples.append({'frameId':i*8,'timeSec':i*.4,'segmentId':None if missing else f'{mid}-{int(i>3)}','status':'missing' if missing else 'estimated','position':None if missing else [float(i),float(i%3),float(i*.5)],'orientationXyzw':None if missing else [0.,0.,0.,1.]})
  count=sum(s['status']=='estimated' for s in samples)
  models.append({'id':mid,'camera':{'model':'SIMPLE_RADIAL','width':160,'height':120,'params':[160,80,60,0]},'samples':samples,'segments':[],'quality':{'registeredFrames':count,'sampledFrames':8,'coverage':count/8,'points3D':100,'meanReprojectionErrorPx':.5,'maxGapSec':.4 if mid=='primary' else 1.6}})
 trajectory={'schemaVersion':1,'runId':directory.name,'videoId':metadata['id'],'video':metadata,'createdAt':'2026-11-06T12:00:00Z','engine':'cuvslam controlled fixture' if engine == 'cuvslam' else 'pycolmap controlled fixture','units':'arbitrary','scaleSource':None,'poseConvention':'camera-to-world','settings':settings,'primaryModelId':'primary','models':models,'warnings':['Тестовый результат с пропуском.']}
 (directory/'controlled.json').write_text(json.dumps({'state':'partial','trajectory':trajectory}))
 return [sys.executable,str(root/'processor.py'),str(directory)]
app=create_app(storage.name,processor_command=controlled)
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=18000)

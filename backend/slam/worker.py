from __future__ import annotations
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
import av,cv2,numpy as np,pycolmap

def main(video,out,settings):
    out=Path(out); out.mkdir(parents=True,exist_ok=True); s=json.loads(settings); video_id=s.pop('_videoId',''); preview=s.pop('_previewUrl',''); imgs=out/'images'; imgs.mkdir()
    c=av.open(video); stream=next(x for x in c.streams if x.type=='video'); times=[]; target=0.; step=1/max(float(s.get('sampleHz',5)),.01)
    for frame in c.decode(stream):
        t=float(frame.pts*frame.time_base) if frame.pts is not None else float(frame.time or 0)
        if t+1e-8<target: continue
        arr=frame.to_ndarray(format='gray'); h,w=arr.shape; maxw=int(s.get('maxImageSize',640))
        if w>maxw: arr=cv2.resize(arr,(maxw,round(h*maxw/w)))
        cv2.imwrite(str(imgs/f'{len(times):05}.jpg'),arr); times.append(t); target+=step
    ex=pycolmap.FeatureExtractionOptions(); ex.num_threads=int(s.get('threads',2)); ex.sift.max_num_features=int(s.get('maxFeatures',1500)); ex.max_image_size=int(s.get('maxImageSize',640)); db=out/'database.db'
    pycolmap.extract_features(db,imgs,camera_mode=pycolmap.CameraMode.SINGLE,reader_options={'camera_model':'SIMPLE_RADIAL'},extraction_options=ex,device=pycolmap.Device.cpu)
    ma=pycolmap.FeatureMatchingOptions(); ma.num_threads=int(s.get('threads',2)); pycolmap.match_sequential(db,matching_options=ma,pairing_options={'overlap':int(s.get('overlap',5)),'quadratic_overlap':False,'num_threads':int(s.get('threads',2))},device=pycolmap.Device.cpu)
    opts=pycolmap.IncrementalPipelineOptions(); opts.num_threads=int(s.get('threads',2)); models=pycolmap.incremental_mapping(db,imgs,out/'sparse',options=opts) or {}; all_models=[]
    for mid,rec in models.items():
        reg={Path(rec.image(i).name).stem:rec.image(i) for i in rec.reg_image_ids()}; samples=[]; segments=[]; seg=None; start=last=None
        for i,t in enumerate(times):
            im=reg.get(f'{i:05}')
            if im is None: samples.append({'frameId':i,'timeSec':t,'status':'missing','position':None,'orientationXyzw':None,'segmentId':None}); seg=None; continue
            pose=im.cam_from_world(); R=np.asarray(pose.rotation.matrix()); tv=np.asarray(pose.translation); q=pose.rotation.quat.tolist(); pos=(-R.T@tv).tolist()
            if seg is None: seg=f'{mid}-{len(segments)}'; start=t
            samples.append({'frameId':i,'timeSec':t,'status':'estimated','position':pos,'orientationXyzw':[q[1],q[2],q[3],q[0]],'segmentId':seg}); last=t
            if i+1==len(times) or f'{i+1:05}' not in reg: segments.append({'id':seg,'startTimeSec':start,'endTimeSec':last})
        cam=rec.camera(rec.image(next(iter(rec.reg_image_ids()))).camera_id); all_models.append({'id':str(mid),'camera':{'model':cam.model_name,'width':cam.width,'height':cam.height,'params':cam.params.tolist()},'samples':samples,'segments':segments,'quality':{'registeredFrames':rec.num_reg_images(),'sampledFrames':len(times),'coverage':rec.num_reg_images()/len(times) if times else 0,'points3D':rec.num_points3D(),'meanReprojectionErrorPx':rec.compute_mean_reprojection_error(),'maxGapSec':0}})
    state='succeeded' if all_models and all(m['quality']['registeredFrames']==len(times) for m in all_models) else ('partial' if all_models else 'failed'); meta={'id':video_id,'name':Path(video).name,'width':w,'height':h,'durationSec':times[-1] if times else 0,'frameCount':len(times),'codec':stream.codec_context.name,'sha256':hashlib.sha256(Path(video).read_bytes()).hexdigest(),'previewUrl':preview}; now=datetime.now(timezone.utc).isoformat(); traj={'schemaVersion':1,'runId':out.name,'videoId':video_id,'video':meta,'createdAt':now,'engine':'pycolmap 4.2.1','units':'arbitrary','scaleSource':None,'poseConvention':'camera-to-world','settings':s,'primaryModelId':max(all_models,key=lambda m:m['quality']['coverage'])['id'] if all_models else '','models':all_models,'warnings':[] if state=='succeeded' else ['Some selected frames have no registered camera pose']}; (out/'manifest.json.tmp').write_text(json.dumps({'runId':out.name,'videoId':video_id,'state':state,'createdAt':now,'trajectory':traj})); (out/'manifest.json.tmp').replace(out/'manifest.json')
if __name__=='__main__': main(*sys.argv[1:])

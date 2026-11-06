# Shared implementation contract

Specification: `.scratch/video-trajectory/spec.md`. All JSON keys use camelCase. API base `/api`.

- POST /videos multipart `file`: `{id,name,width,height,durationSec,frameCount,codec,sha256,previewUrl}` (Video). GET /videos/{id} same. GET /videos/{id}/preview supports HTTP Range.
- POST /runs JSON `{videoId,settings?:{sampleHz?:5,maxImageSize?:640,maxFeatures?:1500,threads?:2,overlap?:5}}` -> RunStatus, 202. 409 `{error:{code:'processing_busy',message:string}}` when occupied.
- GET /status -> RunStatus: `{state:'idle'|'running'|'succeeded'|'partial'|'failed'|'cancelled',runId:string|null,videoId:string|null,stage:string,processed?:number,total?:number,error?:{code,message}|null}`.
- POST /runs/{id}/cancel -> RunStatus, idempotent for same completed/cancelled run; cannot cancel a different running run.
- GET /results -> array ResultSummary `{runId,videoId,videoName,createdAt,state:'succeeded'|'partial',registeredFrames,sampledFrames}`.
- GET /results/{id} -> Trajectory. GET /results/{id}/export?format=json|csv -> download.
- GET /health -> `{status:'ok'}`. All failures use `{error:{code,message}}`.

Trajectory: `{schemaVersion:1,runId,videoId,video:Video,createdAt,engine:string,units:'arbitrary',scaleSource:null,poseConvention:'camera-to-world',settings,primaryModelId:string,models:Model[],warnings:string[]}`.
Model: `{id:string,camera:{model,width,height,params:number[]},samples:Sample[],segments:{id:string,startTimeSec,endTimeSec}[],quality:{registeredFrames,sampledFrames,coverage:number,points3D:number,meanReprojectionErrorPx:number|null,maxGapSec:number}}`.
Sample: `{frameId:number,timeSec:number,segmentId:string|null,status:'estimated'|'missing',position:[number,number,number]|null,orientationXyzw:[number,number,number,number]|null}`. Every selected frame included in each model; missing entries break lines. Estimated positions translated to first camera origin, rotations retain COLMAP world axes. Segment IDs change after missing frames. Model coordinates independent. Times relative to first decoded source PTS. Settings complete as above.

Files saved atomically; final manifest written last. Current status in API memory; completed results listed from manifests. Service host 127.0.0.1, one worker. Default storage `storage/` (SLAM_STORAGE override). Root project videos not committed. Backend package `slam` under backend/, run `uv run --project backend uvicorn slam.api:app --host 127.0.0.1 --port 8000` (verify packaging). Tests may inject a controlled process runner at external CV boundary; production must always run real reconstruction.

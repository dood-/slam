<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, type Status, type Video, type Trajectory } from './api'
import { poseAt } from './trajectory'
import Route2D from './components/Route2D.vue'
import Route3D from './components/Route3D.vue'

const selectedFile=ref<File|null>(null), localUrl=ref(''), video=ref<Video|null>(null)
const trajectory=ref<Trajectory|null>(null), modelId=ref(''), view=ref<'2D'|'3D'>('2D')
const status=ref<Status>({state:'idle',runId:null,videoId:null,stage:'idle'})
const history=ref<Awaited<ReturnType<typeof api.results>>>([]), error=ref(''), pending=ref(false)
const media=ref<HTMLVideoElement|null>(null), time=ref(0), speed=ref(1), playing=ref(false)
const settings=ref({sampleHz:5,maxImageSize:640,maxFeatures:1500,threads:2,overlap:5})
const source=computed(()=>trajectory.value?.video.previewUrl||localUrl.value||video.value?.previewUrl||'')
const model=computed(()=>trajectory.value?.models.find(m=>m.id===modelId.value))
const pose=computed(()=>model.value?poseAt(model.value.samples,time.value):null)
const duration=ref(0)
const stateLabels:Record<string,string>={idle:'Готово к запуску',running:'Обработка',succeeded:'Восстановлено',partial:'Частичный результат',failed:'Ошибка обработки',cancelled:'Обработка отменена'}
const stageLabels:Record<string,string>={decoding:'Подготовка кадров',features:'Поиск ключевых точек',matching:'Сопоставление кадров',mapping:'Восстановление геометрии',done:'Результат готов'}
const poseLabel=computed(()=>pose.value?.status==='estimated'?'Измеренная поза':pose.value?'Интерполированная поза':'Поза недоступна')
const timeline=computed(()=>model.value?.samples.map((sample,i,array)=>({start:sample.timeSec,end:array[i+1]?.timeSec||duration.value,valid:sample.status==='estimated'&&array[i+1]?.status==='estimated'&&sample.segmentId===array[i+1]?.segmentId}))||[])
let poll:ReturnType<typeof setTimeout>|undefined, disposed=false, frameCallback:number|undefined, callbackVideo:HTMLVideoElement|null=null
let loadedRun=''
async function perform(action:()=>Promise<void>) { error.value='';try{await action()}catch(e){error.value=e instanceof Error?e.message:String(e)} }
async function loadHistory(){history.value=await api.results()}
async function loadResult(id:string){await perform(async()=>{
  trajectory.value=await api.result(id);loadedRun=id;modelId.value=trajectory.value.primaryModelId
  video.value=trajectory.value.video;selectedFile.value=null;time.value=0
  await nextTick();if(media.value){media.value.currentTime=0;media.value.pause()}
})}
async function refresh(){
  if(disposed)return
  try{
    status.value=await api.status()
    if(status.value.state==='running'){poll=setTimeout(refresh,1000)}
    else {
      if(status.value.error)error.value=status.value.error.message
      if(status.value.runId&&['succeeded','partial'].includes(status.value.state)&&loadedRun!==status.value.runId){await loadResult(status.value.runId);await loadHistory()}
    }
  }catch(e){error.value=(e as Error).message;if(!disposed)poll=setTimeout(refresh,2000)}
}
function choose(event:Event){
  const file=(event.target as HTMLInputElement).files?.[0];if(!file)return
  if(localUrl.value)URL.revokeObjectURL(localUrl.value)
  selectedFile.value=file;localUrl.value=URL.createObjectURL(file);video.value=null;trajectory.value=null;time.value=0;error.value=''
}
async function upload(){if(!selectedFile.value)return;video.value=await api.upload(selectedFile.value)}
async function start(){
  if(pending.value||status.value.state==='running')return
  pending.value=true
  await perform(async()=>{
    if(!video.value)await upload()
    if(!video.value)return
    trajectory.value=null;media.value?.pause();status.value=await api.start(video.value.id,settings.value)
    if(poll)clearTimeout(poll);await refresh()
  })
  pending.value=false
}
async function cancel(){if(status.value.runId)await perform(async()=>{status.value=await api.cancel(status.value.runId!);if(poll)clearTimeout(poll);await refresh()})}
function sync(){if(media.value){time.value=media.value.currentTime;playing.value=!media.value.paused;duration.value=Number.isFinite(media.value.duration)?media.value.duration:0}}
function seek(value:number){if(media.value){media.value.currentTime=value;time.value=value}}
async function toggle(){await perform(async()=>{if(!media.value)return;if(media.value.paused)await media.value.play();else media.value.pause()})}
function setRate(){if(media.value)media.value.playbackRate=speed.value}
function stopFrameClock(){if(callbackVideo&&frameCallback!==undefined)callbackVideo.cancelVideoFrameCallback?.(frameCallback);frameCallback=undefined;callbackVideo=null}
watch(media,element=>{
  stopFrameClock()
  if(!element)return
  callbackVideo=element
  if(element.requestVideoFrameCallback){const tick=(_:number,metadata:VideoFrameCallbackMetadata)=>{if(disposed||callbackVideo!==element)return;time.value=metadata.mediaTime;frameCallback=element.requestVideoFrameCallback(tick)};frameCallback=element.requestVideoFrameCallback(tick)}
})
watch(source,()=>{time.value=0;playing.value=false})
onMounted(async()=>{await perform(loadHistory);await refresh()})
onBeforeUnmount(()=>{disposed=true;if(poll)clearTimeout(poll);stopFrameClock();if(localUrl.value)URL.revokeObjectURL(localUrl.value)})
function number(value:number|undefined){return value===undefined?'—':value.toLocaleString('ru-RU')}
</script>

<template>
  <div class="app-shell">
    <header class="app-header"><a class="brand" href="/" aria-label="Траектория — главная"><svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true"><path d="M5 24V12L15 5l10 7v12L15 17Z" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="15" cy="17" r="3" fill="currentColor"/></svg>Траектория</a><span>Видео → движение камеры</span><span class="local-label">Локальная рабочая область</span></header>
    <main>
      <div class="page-heading"><div><h1>Маршрут из видео</h1><p>Сопоставьте восстановленное движение камеры с записью.</p></div><span class="status-label" role="status">{{stateLabels[status.state]}}</span></div>
      <div v-if="error" class="error-message" role="alert">{{error}}<button aria-label="Закрыть сообщение" @click="error=''">×</button></div>
      <section class="input-panel" aria-labelledby="source-title"><div class="source-controls"><h2 id="source-title">Исходное видео</h2><label class="file-picker"><span>{{selectedFile?.name||video?.name||'Выбрать MP4'}}</span><input aria-label="Выбрать MP4" type="file" accept="video/mp4,.mp4" :disabled="pending||status.state==='running'" @change="choose"></label><button class="primary" :disabled="(!selectedFile&&!video)||pending||status.state==='running'" @click="start">{{pending?'Подготовка…':'Восстановить маршрут'}}</button></div>
      <div v-if="video" class="metadata">{{video.width}} × {{video.height}} · {{video.durationSec.toFixed(2)}} с · {{number(video.frameCount)}} кадров · {{video.codec}}</div>
      <details class="parameters"><summary>Параметры обработки</summary><div class="parameter-grid"><label>Выборка, кадров/с<input v-model.number="settings.sampleHz" type="number" min="0.5" max="30" step="0.5" :disabled="status.state==='running'"></label><label>Размер, px<input v-model.number="settings.maxImageSize" type="number" min="160" max="1920" :disabled="status.state==='running'"></label><label>Признаки на кадр<input v-model.number="settings.maxFeatures" type="number" min="256" max="8192" :disabled="status.state==='running'"></label><label>Потоки CPU<input v-model.number="settings.threads" type="number" min="1" max="16" :disabled="status.state==='running'"></label><label>Окно сопоставления<input v-model.number="settings.overlap" type="number" min="1" max="30" :disabled="status.state==='running'"></label></div></details></section>
      <section v-if="status.state==='running'" class="processing" aria-label="Ход обработки"><div><h2>{{stageLabels[status.stage]||status.stage}}</h2><p v-if="status.total">{{number(status.processed||0)}} / {{number(status.total)}} · счётчик текущего этапа</p><p v-else>Выполняются вычисления на CPU</p></div><span class="activity" aria-hidden="true"></span><button @click="cancel">Отменить обработку</button></section>
      <div class="workspace">
        <section class="video-panel" aria-labelledby="video-title"><div class="panel-heading"><h2 id="video-title">Видеозапись</h2><span>{{time.toFixed(2)}} с</span></div><div class="video-frame"><video v-if="source" :key="source" ref="media" :src="source" controls preload="metadata" @timeupdate="sync" @seeked="sync" @loadedmetadata="sync" @play="sync" @pause="sync" @ended="sync" @error="error='Браузер не смог открыть видео. Проверьте поддержку кодека.'"></video><div v-else class="empty-video"><svg width="60" height="60" viewBox="0 0 60 60" aria-hidden="true"><rect x="7" y="13" width="35" height="34" rx="3" fill="none" stroke="currentColor" stroke-width="2"/><path d="m42 24 12-7v26l-12-7" fill="none" stroke="currentColor" stroke-width="2"/></svg><p>Выберите запись для предпросмотра</p></div></div><div class="transport"><button :disabled="!source" :aria-label="playing?'Пауза':'Воспроизвести'" @click="toggle">{{playing?'Пауза':'Воспроизвести'}}</button><input aria-label="Время видео" type="range" min="0" :max="duration||1" step="0.001" :value="time" :disabled="!source" @input="seek(Number(($event.target as HTMLInputElement).value))"><label>Скорость<select v-model.number="speed" aria-label="Скорость воспроизведения" @change="setRate"><option :value=".5">0.5×</option><option :value="1">1×</option><option :value="2">2×</option></select></label></div></section>
        <section class="trajectory-panel" aria-labelledby="route-title"><div class="panel-heading"><h2 id="route-title">Путь камеры</h2><div class="view-switch" role="group" aria-label="Вид маршрута"><button :aria-pressed="view==='2D'" @click="view='2D'">2D</button><button :aria-pressed="view==='3D'" @click="view='3D'">3D</button></div></div><template v-if="model"><Route2D v-if="view==='2D'" :model="model" :time="time" @seek="seek"/><Route3D v-else :model="model" :time="time"/><div class="pose-status" data-testid="pose-status">{{poseLabel}}<span v-if="pose?.position">{{pose.position.map(n=>n.toFixed(2)).join(' / ')}}</span></div></template><div v-else class="empty-route"><span class="route-symbol" aria-hidden="true">↗</span><h3>Пока нет траектории</h3><p>Запустите обработку или откройте сохранённый результат.</p></div></section>
      </div>
      <section v-if="trajectory&&model" class="result-panel" aria-labelledby="result-title"><div class="panel-heading"><div><h2 id="result-title">Результат реконструкции</h2><p>{{trajectory.video.name}}</p></div><div class="export-actions"><a :href="`/api/results/${trajectory.runId}/export?format=json`" download>JSON ↓</a><a :href="`/api/results/${trajectory.runId}/export?format=csv`" download>CSV ↓</a></div></div><div class="result-controls"><label>Модель<select v-model="modelId" aria-label="Модель реконструкции"><option v-for="m in trajectory.models" :key="m.id" :value="m.id">Модель {{m.id}} · {{m.quality.registeredFrames}} поз{{m.id===trajectory.primaryModelId?' · основная':''}}</option></select></label><span>{{trajectory.engine}} · {{trajectory.poseConvention}}</span></div><dl class="metrics"><div><dt>Покрытие кадров</dt><dd>{{(model.quality.coverage*100).toFixed(1)}}<small>%</small></dd></div><div><dt>Восстановлено кадров</dt><dd>{{model.quality.registeredFrames}}<small>/ {{model.quality.sampledFrames}}</small></dd></div><div><dt>Разреженные точки</dt><dd>{{number(model.quality.points3D)}}</dd></div><div><dt>Репроекция</dt><dd>{{model.quality.meanReprojectionErrorPx?.toFixed(2)??'—'}}<small>px</small></dd></div></dl><div class="coverage-heading"><h3>Покрытие по времени</h3><span>Наибольший пропуск: {{model.quality.maxGapSec.toFixed(2)}} с</span></div><div class="coverage" role="group" aria-label="Временные интервалы поз"><button v-for="(interval,i) in timeline" :key="i" :class="interval.valid?'covered':'missing'" :style="{width:Math.max(0,(interval.end-interval.start)/(duration||1)*100)+'%'}" :aria-label="`${interval.valid?'Есть позы':'Нет позы'} с ${interval.start.toFixed(2)} секунды`" :title="`${interval.start.toFixed(2)} с: ${interval.valid?'позы доступны':'пропуск'}`" @click="seek(interval.start)"></button></div><p class="hint">Цвет — восстановленный интервал; серый — отсутствие позы. Между моделями нет общей системы координат.</p><ul class="warnings"><li v-for="warning in trajectory.warnings" :key="warning">{{warning}}</li></ul><p class="hint">Репроекционная ошибка дана в пикселях обработанного кадра и не является точностью маршрута в метрах. Координаты — в условном масштабе, без геопривязки.</p><details><summary>Настройки этого результата</summary><dl class="run-settings"><template v-for="(value,key) in trajectory.settings" :key="key"><dt>{{key}}</dt><dd>{{value}}</dd></template></dl><p class="hint">{{trajectory.createdAt}} · {{trajectory.runId}}</p></details></section>
      <section class="history-panel" aria-labelledby="history-title"><div class="panel-heading"><h2 id="history-title">Сохранённые маршруты</h2><button @click="perform(loadHistory)">Обновить</button></div><p v-if="!history.length" class="hint">Здесь появятся завершённые результаты. Они сохраняются после перезапуска приложения.</p><ul class="history-list"><li v-for="item in history" :key="item.runId"><button @click="loadResult(item.runId)"><span><strong>{{item.videoName}}</strong><small>{{new Date(item.createdAt).toLocaleString('ru-RU')}}</small></span><span>{{item.state==='partial'?'Частично':'Восстановлено'}} · {{item.registeredFrames}} / {{item.sampledFrames}} кадров <b aria-hidden="true">↗</b></span></button></li></ul></section>
    </main><footer>Траектория камеры · локальная реконструкция · условный масштаб</footer>
  </div>
</template>

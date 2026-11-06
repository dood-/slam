<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Model } from '../api'
import { contiguousSegments, poseAt, projection, type Plane } from '../trajectory'
const props = defineProps<{ model: Model; time: number }>()
const emit = defineEmits<{ seek: [time: number] }>()
const plane = ref<Plane>('XZ')
const box = ref([0, 0, 800, 450])
const points = computed(() => projection(props.model, plane.value, 800, 450))
const segments = computed(() => contiguousSegments(props.model.samples))
const pose = computed(() => poseAt(props.model.samples, props.time))
const currentPoint = computed(() => {
  if (!pose.value?.position) return null
  const augmented = { samples: [...props.model.samples, { ...pose.value, status: 'estimated' as const }] }
  const projected=projection(augmented, plane.value, 800, 450)
  return projected[projected.length-1]
})
function path(samples: typeof props.model.samples) {
  return samples.map((sample, i) => {
    const point = points.value.find(p => p.sample.frameId === sample.frameId)!
    return `${i ? 'L' : 'M'}${point.x},${point.y}`
  }).join(' ')
}
function fit() { box.value = [0, 0, 800, 450] }
function zoom(factor: number) {
  const [x,y,w,h] = box.value
  box.value = [x+w*(1-factor)/2, y+h*(1-factor)/2, w*factor, h*factor]
}
function pan(x: number, y: number) { box.value = [box.value[0]+x,box.value[1]+y,...box.value.slice(2)] }
let drag: {x:number;y:number} | null = null
function dragStart(event: PointerEvent) { if ((event.target as Element).tagName === 'circle') return; drag={x:event.clientX,y:event.clientY}; (event.currentTarget as Element).setPointerCapture(event.pointerId) }
function dragMove(event: PointerEvent) {
  if (!drag) return
  const rect=(event.currentTarget as Element).getBoundingClientRect()
  pan(-(event.clientX-drag.x)*box.value[2]/rect.width, -(event.clientY-drag.y)*box.value[3]/rect.height)
  drag={x:event.clientX,y:event.clientY}
}
watch(() => props.model.id, fit)
</script>
<template>
  <div class="route-toolbar"><label>Проекция <select v-model="plane" aria-label="Плоскость проекции"><option>XY</option><option>XZ</option><option>YZ</option></select></label><span>Оси модели · условные единицы</span></div>
  <svg class="route-2d" :viewBox="box.join(' ')" role="img" aria-label="Траектория камеры в 2D" @pointerdown="dragStart" @pointermove="dragMove" @pointerup="drag=null" @pointercancel="drag=null">
    <path v-for="(segment,index) in segments" :key="index" :d="path(segment)" class="future-route" />
    <path v-for="(segment,index) in segments" :key="'past'+index" :d="path(segment.filter(s=>s.timeSec<=time))" class="past-route" />
    <circle v-for="point in points" :key="point.sample.frameId" :cx="point.x" :cy="point.y" r="5" class="sample-point" @click="emit('seek',point.sample.timeSec)"><title>{{point.sample.timeSec.toFixed(2)}} с</title></circle>
    <circle v-if="currentPoint" data-testid="pose-marker" :cx="currentPoint.x" :cy="currentPoint.y" r="9" class="current-point" />
  </svg>
  <div class="route-controls"><button @click="fit">Весь путь</button><button aria-label="Приблизить 2D" @click="zoom(.8)">+</button><button aria-label="Отдалить 2D" @click="zoom(1.25)">−</button><button aria-label="Сдвинуть влево" @click="pan(-40,0)">←</button><button aria-label="Сдвинуть вправо" @click="pan(40,0)">→</button><button aria-label="Сдвинуть вверх" @click="pan(0,-40)">↑</button><button aria-label="Сдвинуть вниз" @click="pan(0,40)">↓</button></div>
  <label class="point-seek">Перейти к позе <select aria-label="Выбрать позу" @change="emit('seek',Number(($event.target as HTMLSelectElement).value))"><option disabled selected>Время кадра</option><option v-for="point in points" :key="point.sample.frameId" :value="point.sample.timeSec">{{point.sample.timeSec.toFixed(2)}} с</option></select></label>
</template>

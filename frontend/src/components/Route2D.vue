<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { Model } from "../api";
import {
  contiguousSegments,
  poseAt,
  projection,
  type Plane,
} from "../trajectory";
const props = defineProps<{ model: Model; time: number }>();
const emit = defineEmits<{ seek: [time: number] }>();
const plane = ref<Plane>("XZ");
const axisLabels = computed(
  () =>
    ({
      XY: "X · Вертикаль: Y",
      XZ: "X · Вертикаль: Z",
      YZ: "Y · Вертикаль: Z",
    })[plane.value],
);
const box = ref([0, 0, 800, 450]);
const points = computed(() => projection(props.model, plane.value, 800, 450));
const segments = computed(() => contiguousSegments(props.model.samples));
const pose = computed(() => poseAt(props.model.samples, props.time));
const currentPoint = computed(() => {
  if (!pose.value?.position) return null;
  const augmented = {
    samples: [
      ...props.model.samples,
      { ...pose.value, status: "estimated" as const },
    ],
  };
  const projected = projection(augmented, plane.value, 800, 450);
  return projected[projected.length - 1];
});
function path(samples: typeof props.model.samples) {
  return samples
    .map((sample, i) => {
      const point = points.value.find(
        (p) => p.sample.frameId === sample.frameId,
      )!;
      return `${i ? "L" : "M"}${point.x},${point.y}`;
    })
    .join(" ");
}
function fit() {
  box.value = [0, 0, 800, 450];
}
function zoom(factor: number) {
  const [x, y, w, h] = box.value;
  box.value = [
    x + (w * (1 - factor)) / 2,
    y + (h * (1 - factor)) / 2,
    w * factor,
    h * factor,
  ];
}
function pan(x: number, y: number) {
  box.value = [box.value[0] + x, box.value[1] + y, ...box.value.slice(2)];
}
let drag: { x: number; y: number } | null = null;
function dragStart(event: PointerEvent) {
  if ((event.target as Element).tagName === "circle") return;
  drag = { x: event.clientX, y: event.clientY };
  (event.currentTarget as Element).setPointerCapture(event.pointerId);
}
function dragMove(event: PointerEvent) {
  if (!drag) return;
  const rect = (event.currentTarget as Element).getBoundingClientRect();
  pan(
    (-(event.clientX - drag.x) * box.value[2]) / rect.width,
    (-(event.clientY - drag.y) * box.value[3]) / rect.height,
  );
  drag = { x: event.clientX, y: event.clientY };
}
watch(() => props.model.id, fit);
</script>
<template>
  <div
    class="flex min-h-11 flex-wrap items-center justify-between gap-2 px-4 py-2 text-[13px] text-muted"
  >
    <label class="flex items-center gap-2"
      >Проекция
      <select
        v-model="plane"
        class="field h-8 w-17 px-2 md:h-8"
        aria-label="Плоскость проекции"
      >
        <option>XY</option>
        <option>XZ</option>
        <option>YZ</option>
      </select></label
    >
    <span>Горизонталь: {{ axisLabels }}</span>
  </div>
  <svg
    class="block h-[240px] w-full touch-none bg-raised sm:h-[260px] xl:h-[200px]"
    :viewBox="box.join(' ')"
    role="group"
    aria-label="Траектория камеры в 2D"
    @pointerdown="dragStart"
    @pointermove="dragMove"
    @pointerup="drag = null"
    @pointercancel="drag = null"
  >
    <path
      v-for="(segment, index) in segments"
      :key="index"
      :d="path(segment)"
      class="fill-none stroke-route-future stroke-[3] [vector-effect:non-scaling-stroke]"
    />
    <path
      v-for="(segment, index) in segments"
      :key="'past' + index"
      :d="path(segment.filter((s) => s.timeSec <= time))"
      class="fill-none stroke-accent stroke-[3] [vector-effect:non-scaling-stroke]"
    />
    <circle
      v-for="point in points"
      :key="point.sample.frameId"
      :cx="point.x"
      :cy="point.y"
      r="8"
      class="cursor-pointer fill-transparent hover:fill-accent focus:fill-accent"
      role="button"
      tabindex="0"
      :aria-label="`Перейти к ${point.sample.timeSec.toFixed(2)} с`"
      @click="emit('seek', point.sample.timeSec)"
      @keydown.enter.prevent="emit('seek', point.sample.timeSec)"
      @keydown.space.prevent="emit('seek', point.sample.timeSec)"
    >
      <title>{{ point.sample.timeSec.toFixed(2) }} с</title>
    </circle>
    <circle
      v-if="currentPoint"
      data-testid="pose-marker"
      :cx="currentPoint.x"
      :cy="currentPoint.y"
      r="9"
      class="pointer-events-none fill-accent stroke-white stroke-2 [vector-effect:non-scaling-stroke]"
    />
  </svg>
  <div class="flex flex-wrap gap-1.5 px-4 py-2">
    <button class="route-control mr-auto" @click="fit">Весь путь</button
    ><button
      class="route-control"
      aria-label="Приблизить 2D"
      @click="zoom(0.8)"
    >
      +</button
    ><button class="route-control" aria-label="Отдалить 2D" @click="zoom(1.25)">
      −
    </button>
    <div class="flex basis-full gap-1.5 sm:basis-auto">
      <button
        class="route-control flex-1 sm:flex-none"
        aria-label="Сдвинуть влево"
        @click="pan(-40, 0)"
      >
        ←</button
      ><button
        class="route-control flex-1 sm:flex-none"
        aria-label="Сдвинуть вправо"
        @click="pan(40, 0)"
      >
        →</button
      ><button
        class="route-control flex-1 sm:flex-none"
        aria-label="Сдвинуть вверх"
        @click="pan(0, -40)"
      >
        ↑</button
      ><button
        class="route-control flex-1 sm:flex-none"
        aria-label="Сдвинуть вниз"
        @click="pan(0, 40)"
      >
        ↓
      </button>
    </div>
  </div>
  <label
    class="flex flex-wrap items-center justify-between gap-2 px-4 pb-3 text-[13px] text-muted"
    >Перейти к позе
    <select
      class="field h-8 w-36 px-2 md:h-8"
      aria-label="Выбрать позу"
      @change="emit('seek', Number(($event.target as HTMLSelectElement).value))"
    >
      <option disabled selected>Время кадра</option>
      <option
        v-for="point in points"
        :key="point.sample.frameId"
        :value="point.sample.timeSec"
      >
        {{ point.sample.timeSec.toFixed(2) }} с
      </option>
    </select></label
  >
</template>

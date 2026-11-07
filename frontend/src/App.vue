<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { api, type Status, type Video, type Trajectory, type EngineId, type EngineOption } from "./api";
import { poseAt } from "./trajectory";
import UiIcon from "./components/UiIcon.vue";
import Route2D from "./components/Route2D.vue";
const Route3D = defineAsyncComponent(() => import("./components/Route3D.vue"));

const fileInput = ref<HTMLInputElement | null>(null);
const dragging = ref(false);
const parametersOpen = ref(window.matchMedia("(min-width: 1024px)").matches);
const parameterFields = [
  {
    key: "sampleHz",
    label: "Выборка",
    unit: "кадров/с",
    min: 0.5,
    max: 30,
    step: 0.5,
  },
  {
    key: "maxImageSize",
    label: "Размер кадра",
    unit: "px",
    min: 160,
    max: 1920,
    step: 1,
  },
  {
    key: "maxFeatures",
    label: "Признаки на кадр",
    unit: "",
    min: 256,
    max: 8192,
    step: 1,
  },
  { key: "threads", label: "Потоки CPU", unit: "", min: 1, max: 16, step: 1 },
  {
    key: "overlap",
    label: "Окно сопоставления",
    unit: "кадров",
    min: 1,
    max: 30,
    step: 1,
  },
  { key: "focalRatio", label: "Фокус / ширина", unit: "", min: 0.1, max: 5, step: 0.05 },
] as const;
const engine = ref<EngineId>("colmap");
const engines = ref<EngineOption[]>([
  { id: "colmap", label: "COLMAP · CPU", available: true, reason: null },
  { id: "cuvslam", label: "cuVSLAM Mono · GPU", available: false, reason: "Проверка доступности…" },
]);
const selectedEngine = computed(() => engines.value.find(option => option.id === engine.value));
const visibleParameterFields = computed(() => parameterFields.filter(field =>
  engine.value === "cuvslam"
    ? ["maxImageSize", "focalRatio"].includes(field.key)
    : field.key !== "focalRatio",
));
function engineLabel(value: string | undefined) {
  if (value?.toLowerCase().startsWith("cuvslam")) return "cuVSLAM · GPU";
  if (!value || value === "colmap" || value.toLowerCase().startsWith("pycolmap")) return "COLMAP · CPU";
  return value;
}
const selectedFile = ref<File | null>(null),
  localUrl = ref(""),
  video = ref<Video | null>(null);
const trajectory = ref<Trajectory | null>(null),
  modelId = ref(""),
  view = ref<"2D" | "3D">("2D");
const status = ref<Status>({
  state: "idle",
  runId: null,
  videoId: null,
  stage: "idle",
});
const history = ref<Awaited<ReturnType<typeof api.results>>>([]),
  error = ref(""),
  pending = ref(false);
const media = ref<HTMLVideoElement | null>(null),
  time = ref(0),
  speed = ref(1),
  playing = ref(false);
const colmapSettings = ref<Record<string, number>>({
  sampleHz: 5,
  maxImageSize: 640,
  maxFeatures: 1500,
  threads: 2,
  overlap: 5,
});
const cuvslamSettings = ref<Record<string, number>>({ maxImageSize: 960, focalRatio: 0.8 });
const settings = computed(() => engine.value === "cuvslam" ? cuvslamSettings.value : colmapSettings.value);
const source = computed(
  () =>
    trajectory.value?.video.previewUrl ||
    localUrl.value ||
    video.value?.previewUrl ||
    "",
);
const model = computed(() =>
  trajectory.value?.models.find((m) => m.id === modelId.value),
);
const pose = computed(() =>
  model.value ? poseAt(model.value.samples, time.value) : null,
);
const duration = ref(0),
  localMeta = ref<{ width: number; height: number; duration: number } | null>(
    null,
  );
const stateLabels: Record<string, string> = {
  idle: "Готово к запуску",
  running: "Обработка",
  succeeded: "Восстановлено",
  partial: "Частичный результат",
  failed: "Ошибка обработки",
  cancelled: "Обработка отменена",
};
const stageLabels: Record<string, string> = {
  decoding: "Подготовка кадров",
  features: "Поиск ключевых точек",
  matching: "Сопоставление кадров",
  mapping: "Восстановление геометрии",
  tracking: "Отслеживание камеры",
  exporting: "Сохранение траектории",
  done: "Результат готов",
};
const poseLabel = computed(() =>
  pose.value?.status === "estimated"
    ? "Оценённая поза"
    : pose.value
      ? "Интерполированная поза"
      : "Поза недоступна",
);
const timeline = computed(
  () =>
    model.value?.samples.map((sample, i, array) => ({
      start: sample.timeSec,
      end: array[i + 1]?.timeSec || duration.value,
      valid:
        sample.status === "estimated" &&
        array[i + 1]?.status === "estimated" &&
        sample.segmentId === array[i + 1]?.segmentId,
    })) || [],
);
let poll: ReturnType<typeof setTimeout> | undefined,
  disposed = false,
  frameCallback: number | undefined,
  callbackVideo: HTMLVideoElement | null = null;
let loadedRun = "";
async function perform(action: () => Promise<void>) {
  error.value = "";
  try {
    await action();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}
async function loadHistory() {
  history.value = await api.results();
}
async function loadResult(id: string) {
  await perform(async () => {
    trajectory.value = await api.result(id);
    loadedRun = id;
    modelId.value = trajectory.value.primaryModelId;
    video.value = trajectory.value.video;
    selectedFile.value = null;
    time.value = 0;
    await nextTick();
    if (media.value) {
      media.value.currentTime = 0;
      media.value.pause();
    }
  });
}
async function refresh() {
  if (disposed) return;
  try {
    status.value = await api.status();
    if (status.value.state === "running") {
      poll = setTimeout(refresh, 1000);
    } else {
      if (status.value.error) error.value = status.value.error.message;
      if (
        status.value.runId &&
        ["succeeded", "partial"].includes(status.value.state) &&
        loadedRun !== status.value.runId
      ) {
        await loadResult(status.value.runId);
        await loadHistory();
      }
    }
  } catch (e) {
    error.value = (e as Error).message;
    if (!disposed) poll = setTimeout(refresh, 2000);
  }
}
function choose(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (file) selectFile(file);
}
function dropFile(event: DragEvent) {
  dragging.value = false;
  if (pending.value || status.value.state === "running") return;
  const file = event.dataTransfer?.files[0];
  if (file) selectFile(file);
}
function selectFile(file: File) {
  if (!file.name.toLowerCase().endsWith(".mp4")) {
    error.value = "Выберите видео в формате MP4.";
    return;
  }
  if (localUrl.value) URL.revokeObjectURL(localUrl.value);
  localMeta.value = null;
  selectedFile.value = file;
  localUrl.value = URL.createObjectURL(file);
  video.value = null;
  trajectory.value = null;
  duration.value = 0;
  time.value = 0;
  error.value = "";
}
async function upload() {
  if (!selectedFile.value) return;
  video.value = await api.upload(selectedFile.value);
}
async function start() {
  if (pending.value || status.value.state === "running") return;
  pending.value = true;
  await perform(async () => {
    if (!video.value) await upload();
    if (!video.value) return;
    trajectory.value = null;
    media.value?.pause();
    status.value = await api.start(video.value.id, settings.value, engine.value);
    if (poll) clearTimeout(poll);
    await refresh();
  });
  pending.value = false;
}
async function cancel() {
  if (status.value.runId)
    await perform(async () => {
      status.value = await api.cancel(status.value.runId!);
      if (poll) clearTimeout(poll);
      await refresh();
    });
}
function sync() {
  if (media.value) {
    time.value = media.value.currentTime;
    playing.value = !media.value.paused;
    duration.value = Number.isFinite(media.value.duration)
      ? media.value.duration
      : 0;
    localMeta.value = {
      width: media.value.videoWidth,
      height: media.value.videoHeight,
      duration: duration.value,
    };
  }
}
function seek(value: number) {
  if (media.value) {
    media.value.currentTime = value;
    time.value = value;
  }
}
async function toggle() {
  await perform(async () => {
    if (!media.value) return;
    if (media.value.paused) await media.value.play();
    else media.value.pause();
  });
}
function setRate() {
  if (media.value) media.value.playbackRate = speed.value;
}
function stopFrameClock() {
  if (callbackVideo && frameCallback !== undefined)
    callbackVideo.cancelVideoFrameCallback?.(frameCallback);
  frameCallback = undefined;
  callbackVideo = null;
}
watch(media, (element) => {
  stopFrameClock();
  if (!element) return;
  callbackVideo = element;
  if (element.requestVideoFrameCallback) {
    const tick = (_: number, metadata: VideoFrameCallbackMetadata) => {
      if (disposed || callbackVideo !== element) return;
      time.value = metadata.mediaTime;
      frameCallback = element.requestVideoFrameCallback(tick);
    };
    frameCallback = element.requestVideoFrameCallback(tick);
  }
});
watch(source, () => {
  time.value = 0;
  playing.value = false;
});
onMounted(async () => {
  await perform(async () => { engines.value = await api.engines(); });
  await perform(loadHistory);
  await refresh();
});
onBeforeUnmount(() => {
  disposed = true;
  if (poll) clearTimeout(poll);
  stopFrameClock();
  if (localUrl.value) URL.revokeObjectURL(localUrl.value);
});
function clock(value: number) {
  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60)
    .toString()
    .padStart(2, "0");
  return `${minutes}:${seconds}`;
}
function number(value: number | undefined) {
  return value === undefined ? "—" : value.toLocaleString("ru-RU");
}
</script>

<template>
  <div class="min-h-screen font-sans">
    <header class="flex h-14 items-center justify-between gap-4 px-4 lg:px-6">
      <a
        href="/"
        class="flex items-center gap-2.5 text-lg font-semibold tracking-tight"
        aria-label="Траектория — главная"
      >
        <UiIcon name="route" :size="25" class="text-accent" />Траектория
      </a>
      <div class="flex items-center gap-6 text-[13px] text-muted">
        <span class="hidden items-center gap-2 sm:flex"
          ><span class="size-1.5 rounded-full bg-accent"></span>Локальная
          рабочая область</span
        >
        <span class="flex items-center gap-2"
          ><UiIcon name="cpu" :size="15" /><span class="hidden sm:inline">{{ status.state === 'running' ? 'Обработка:' : 'Новый запуск:' }}</span>
          {{ engineLabel(status.state === 'running' ? status.engine : engine) }}</span
        >
      </div>
    </header>

    <!-- Desktop: 272px configuration frame + fluid white sheet + 8px outer inset. -->
    <div class="grid items-start lg:grid-cols-[272px_minmax(0,1fr)]">
      <aside
        class="min-w-0 px-4 pb-6 lg:px-6"
        aria-label="Настройки реконструкции"
      >
        <form class="space-y-4 lg:space-y-6" @submit.prevent="start">
          <div class="lg:pt-3">
            <div
              class="mb-4 hidden items-center gap-2 text-sm font-medium lg:flex"
            >
              <UiIcon name="video" :size="17" />
              <h2>Исходное видео</h2>
            </div>
            <input
              ref="fileInput"
              class="sr-only"
              tabindex="-1"
              aria-label="Выбрать MP4"
              type="file"
              accept="video/mp4,.mp4"
              :disabled="pending || status.state === 'running'"
              @change="choose"
            />
            <button
              type="button"
              aria-label="Выбрать исходное видео"
              class="flex w-full items-center gap-3 rounded-lg border border-control bg-surface p-3 text-left transition-colors hover:border-muted disabled:cursor-not-allowed"
              :disabled="pending || status.state === 'running'"
              @click="fileInput?.click()"
            >
              <UiIcon
                :name="selectedFile || video ? 'video' : 'upload'"
                :size="20"
                class="text-muted"
              />
              <span class="min-w-0 flex-1"
                ><span class="block truncate text-sm font-medium">{{
                  selectedFile?.name || video?.name || "Выбрать MP4"
                }}</span
                ><span class="meta">{{
                  selectedFile || video
                    ? "Заменить видео"
                    : "Запись с вашей камеры"
                }}</span></span
              >
              <UiIcon name="chevron" :size="14" class="text-muted" />
            </button>
            <div
              v-if="video || localMeta"
              class="mt-3 grid grid-cols-2 gap-2 text-[13px] text-muted tabular-nums"
            >
              <span
                >{{ video?.width || localMeta?.width }} ×
                {{ video?.height || localMeta?.height }} px</span
              >
              <span class="text-right"
                >{{
                  (video?.durationSec || localMeta?.duration || 0).toFixed(2)
                }}
                с</span
              >
              <span v-if="video">{{ number(video.frameCount) }} кадров</span
              ><span v-if="video" class="text-right">{{ video.codec }}</span>
            </div>
            <p
              v-else
              class="mt-3 hidden text-[13px] leading-5 text-muted lg:block"
            >
              Видео остаётся на этом устройстве. Обработка выполняется локально.
            </p>
          </div>

          <div>
            <label for="engine" class="mb-1.5 block text-sm font-medium">Движок обработки</label>
            <select
              id="engine"
              v-model="engine"
              class="field"
              :disabled="pending || status.state === 'running'"
              aria-describedby="engine-description"
            >
              <option v-for="option in engines" :key="option.id" :value="option.id" :disabled="!option.available">
                {{ option.label }}{{ option.available ? '' : ' · недоступен' }}
              </option>
            </select>
            <p id="engine-description" class="mt-2 text-[13px] leading-5 text-muted">
              {{ engine === 'cuvslam'
                ? 'Все кадры видео на NVIDIA GPU. Масштаб условный; параметры камеры приближённые.'
                : 'Офлайн-реконструкция на CPU с оценкой параметров камеры.' }}
            </p>
            <p v-if="engines.find(option => option.id === 'cuvslam')?.reason" class="mt-2 text-[13px] leading-5 text-muted">
              {{ engines.find(option => option.id === 'cuvslam')?.reason }}
            </p>
          </div>

          <details
            class="group lg:border-t lg:border-line lg:pt-5"
            :open="parametersOpen"
            @toggle="
              parametersOpen = ($event.target as HTMLDetailsElement).open
            "
          >
            <summary
              class="flex list-none items-center justify-between gap-2 text-sm font-medium [&::-webkit-details-marker]:hidden"
            >
              <span class="flex items-center gap-2"
                ><UiIcon name="settings" :size="17" />Параметры обработки</span
              >
              <UiIcon
                name="chevron"
                :size="14"
                class="rotate-90 transition-transform group-not-open:rotate-0"
              />
            </summary>
            <div class="mt-5 grid grid-cols-2 gap-4 lg:grid-cols-1">
              <label
                v-for="field in visibleParameterFields"
                :key="field.key"
                class="block min-w-0"
              >
                <span
                  class="mb-1.5 flex flex-wrap items-baseline justify-between gap-1 text-sm"
                  ><span>{{ field.label }}</span
                  ><span class="text-[13px] text-muted">{{
                    field.unit
                  }}</span></span
                >
                <input
                  v-model.number="settings[field.key]"
                  class="field"
                  type="number"
                  :min="field.min"
                  :max="field.max"
                  :step="field.step"
                  required
                  :disabled="pending || status.state === 'running'"
                />
              </label>
            </div>
            <p v-if="engine === 'cuvslam'" class="mt-3 text-[13px] leading-5 text-muted">
              Фокус / ширина — предположение о камере, не измеренная калибровка. Начальное значение 0,8.
            </p>
          </details>
          <div class="space-y-2 lg:space-y-3">
            <button
              type="submit"
              class="btn btn-primary w-full"
              :disabled="
                (!selectedFile && !video) ||
                pending ||
                status.state === 'running' ||
                !selectedEngine?.available
              "
            >
              <UiIcon name="route" :size="16" />{{
                pending ? "Подготовка…" : "Восстановить маршрут"
              }}
            </button>
            <p class="text-[13px] leading-5 text-muted">
              {{
                !selectedFile && !video
                  ? "Выберите видео, чтобы начать."
                  : "Маршрут и исходная запись будут синхронизированы по времени."
              }}
            </p>
          </div>
        </form>
        <div class="mt-6 hidden border-t border-line pt-5 lg:block">
          <p class="flex items-center gap-2 text-[13px] font-medium">
            <UiIcon name="info" :size="15" />О координатах
          </p>
          <p class="mt-2 text-[13px] leading-5 text-muted">
            Масштаб условный, без геопривязки. Пропуски между сегментами не
            соединяются.
          </p>
        </div>
      </aside>

      <main
        class="min-w-0 bg-surface px-4 py-5 lg:mr-2 lg:mb-2 lg:min-h-[calc(100vh-64px)] lg:rounded-2xl lg:border lg:border-line lg:p-6"
      >
        <div class="mb-6 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 class="text-[22px] leading-8 font-semibold tracking-tight">
              Маршрут из видео
            </h1>
            <p class="mt-1 text-sm text-muted">
              Движение камеры, кадр за кадром.
            </p>
            <p v-if="trajectory" class="mt-1 text-[13px] text-muted" data-testid="result-engine">
              Движок результата: {{ engineLabel(trajectory.engine) }}
            </p>
          </div>
          <span
            class="inline-flex min-h-8 items-center gap-2 rounded-md bg-raised px-3 text-[13px]"
            role="status"
            ><span
              class="size-1.5 rounded-full"
              :class="
                status.state === 'failed'
                  ? 'bg-negative'
                  : status.state === 'running'
                    ? 'bg-accent'
                    : 'bg-muted'
              "
            ></span
            >{{ stateLabels[status.state] }}</span
          >
        </div>

        <div
          v-if="error"
          class="mb-6 flex items-start justify-between gap-4 rounded-lg bg-negative-soft p-4 text-sm text-negative"
          role="alert"
        >
          <span>{{ error }}</span
          ><button
            class="shrink-0 rounded p-1"
            aria-label="Закрыть сообщение"
            @click="error = ''"
          >
            <UiIcon name="close" :size="16" />
          </button>
        </div>
        <section
          v-if="status.state === 'running'"
          class="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-lg bg-accent-soft p-4"
          aria-label="Ход обработки"
        >
          <div class="flex items-center gap-3">
            <UiIcon name="cpu" class="text-accent" />
            <div>
              <h2 class="font-medium">
                {{ stageLabels[status.stage] || status.stage }}
              </h2>
              <p class="meta">
                {{
                  status.total
                    ? `${number(status.processed || 0)} / ${number(status.total)} · текущий этап`
                    : "Выполняются вычисления на CPU"
                }}
              </p>
            </div>
          </div>
          <button class="btn" @click="cancel">Отменить обработку</button>
        </section>

        <div class="grid gap-6 xl:grid-cols-2">
          <section class="panel flex flex-col" aria-labelledby="video-title">
            <div class="panel-title">
              <h2 id="video-title" class="panel-name">
                <UiIcon name="video" :size="17" class="text-muted" />Видеозапись
              </h2>
              <span class="meta tabular-nums">{{ time.toFixed(2) }} с</span>
            </div>
            <div
              class="relative flex h-[240px] items-center justify-center bg-stage sm:h-[320px] xl:h-[300px]"
              @dragover.prevent="dragging = true"
              @dragleave.prevent="dragging = false"
              @drop.prevent="dropFile"
            >
              <video
                v-if="source"
                :key="source"
                ref="media"
                :src="source"
                class="h-full w-full object-contain"
                controls
                preload="metadata"
                @timeupdate="sync"
                @seeked="sync"
                @loadedmetadata="sync"
                @play="sync"
                @pause="sync"
                @ended="sync"
                @error="
                  error =
                    'Браузер не смог открыть видео. Проверьте поддержку кодека.'
                "
              ></video>
              <div
                v-else
                class="flex max-w-72 flex-col items-center px-4 text-center"
              >
                <UiIcon name="video" :size="32" class="mb-4 text-stage-muted" />
                <p class="text-base font-medium text-white">
                  Начните с вашей записи
                </p>
                <p class="mt-2 text-sm leading-6 text-stage-muted">
                  Перетащите MP4 сюда или выберите файл на устройстве.
                </p>
                <button
                  class="mt-5 inline-flex min-h-10 items-center gap-2 rounded-md border border-white/40 px-4 text-sm font-medium text-white transition-colors hover:bg-white/10 disabled:text-stage-muted"
                  :disabled="pending || status.state === 'running'"
                  @click="fileInput?.click()"
                >
                  <UiIcon name="upload" :size="16" />Выбрать видео
                </button>
              </div>
              <div
                v-if="dragging"
                class="pointer-events-none absolute inset-2 flex items-center justify-center rounded-lg border-2 border-dashed border-accent bg-stage text-sm text-white"
              >
                Отпустите MP4 для загрузки
              </div>
            </div>
            <div class="flex flex-1 flex-wrap items-center gap-3 px-4 py-3">
              <button
                class="btn btn-quiet px-2"
                :disabled="!source"
                :aria-label="playing ? 'Пауза' : 'Воспроизвести'"
                @click="toggle"
              >
                <UiIcon :name="playing ? 'pause' : 'play'" :size="16" />
              </button>
              <span class="text-[13px] tabular-nums"
                >{{ clock(time)
                }}<span class="text-muted"> / {{ clock(duration) }}</span></span
              >
              <input
                class="order-last h-6 w-full min-w-12 sm:order-none sm:w-auto sm:flex-1"
                aria-label="Время видео"
                type="range"
                min="0"
                :max="duration || 1"
                step="0.001"
                :value="time"
                :disabled="!source"
                @input="seek(Number(($event.target as HTMLInputElement).value))"
              />
              <label class="ml-auto flex items-center gap-2"
                ><span class="sr-only">Скорость</span
                ><select
                  v-model.number="speed"
                  class="field h-8 w-17 px-2 md:h-8"
                  aria-label="Скорость воспроизведения"
                  @change="setRate"
                >
                  <option :value="0.5">0.5×</option>
                  <option :value="1">1×</option>
                  <option :value="2">2×</option>
                </select></label
              >
            </div>
          </section>

          <section class="panel flex flex-col" aria-labelledby="route-title">
            <div class="panel-title">
              <h2 id="route-title" class="panel-name">
                <UiIcon name="route" :size="17" class="text-muted" />Путь камеры
              </h2>
              <div
                class="flex items-center"
                role="group"
                aria-label="Вид маршрута"
              >
                <button
                  class="view-tab"
                  :aria-pressed="view === '2D'"
                  @click="view = '2D'"
                >
                  2D</button
                ><button
                  class="view-tab"
                  :aria-pressed="view === '3D'"
                  @click="view = '3D'"
                >
                  3D
                </button>
              </div>
            </div>
            <template v-if="model">
              <Route2D
                v-if="view === '2D'"
                :model="model"
                :time="time"
                @seek="seek"
              /><Route3D v-else :model="model" :time="time" />
              <div
                class="flex flex-wrap items-center justify-between gap-2 border-t border-line bg-raised px-4 py-3 text-[13px]"
                data-testid="pose-status"
              >
                <span class="flex items-center gap-2"
                  ><span
                    class="size-1.5 rounded-full"
                    :class="pose ? 'bg-accent' : 'bg-muted'"
                  ></span
                  >{{ poseLabel }}</span
                ><span v-if="pose?.position" class="tabular-nums text-muted">{{
                  pose.position.map((n) => n.toFixed(2)).join(" / ")
                }}</span>
              </div>
            </template>
            <div
              v-else
              class="flex min-h-[300px] flex-1 flex-col items-center justify-center bg-raised px-6 py-8 text-center"
            >
              <UiIcon name="cube" :size="32" class="mb-4 text-muted" />
              <h3 class="text-base font-medium">Здесь появится путь камеры</h3>
              <p class="mt-2 max-w-64 text-sm leading-6 text-muted">
                Восстановите маршрут, чтобы увидеть положение камеры в каждом
                кадре.
              </p>
              <div class="mt-5 flex items-center gap-4 text-[13px] text-muted">
                <span>2D-проекция</span
                ><span class="size-1 rounded-full bg-control"></span
                ><span>3D-пространство</span>
              </div>
            </div>
          </section>
        </div>

        <section
          v-if="trajectory && model"
          class="panel mt-6"
          aria-labelledby="result-title"
        >
          <div class="panel-title">
            <div>
              <h2 id="result-title" class="text-base font-medium">
                Результат реконструкции
              </h2>
              <p class="meta mt-0.5 break-all">{{ trajectory.video.name }}</p>
            </div>
            <div class="flex gap-2">
              <a
                class="btn"
                :href="`/api/results/${trajectory.runId}/export?format=json`"
                download
                >JSON ↓</a
              ><a
                class="btn"
                :href="`/api/results/${trajectory.runId}/export?format=csv`"
                download
                >CSV ↓</a
              >
            </div>
          </div>
          <div class="space-y-5 p-4">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <label class="flex min-w-0 flex-wrap items-center gap-2 text-sm"
                ><span>Модель</span
                ><select
                  v-model="modelId"
                  class="field w-full max-w-80 sm:w-auto"
                  aria-label="Модель реконструкции"
                >
                  <option
                    v-for="m in trajectory.models"
                    :key="m.id"
                    :value="m.id"
                  >
                    Модель {{ m.id }} · {{ m.quality.registeredFrames }} поз{{
                      m.id === trajectory.primaryModelId ? " · основная" : ""
                    }}
                  </option>
                </select></label
              >
            </div>
            <dl
              class="grid grid-cols-2 gap-5 border-y border-line py-4 sm:grid-cols-4"
            >
              <div>
                <dt class="meta">Покрытие кадров</dt>
                <dd
                  class="mt-1 text-[28px] leading-9 tracking-tight tabular-nums"
                >
                  {{ (model.quality.coverage * 100).toFixed(1)
                  }}<small class="ml-1 text-sm text-muted">%</small>
                </dd>
              </div>
              <div>
                <dt class="meta">Восстановлено кадров</dt>
                <dd class="mt-1 text-2xl leading-9 tabular-nums">
                  {{ model.quality.registeredFrames
                  }}<small class="ml-1 text-sm text-muted"
                    >/ {{ model.quality.sampledFrames }}</small
                  >
                </dd>
              </div>
              <div>
                <dt class="meta">Разреженные точки</dt>
                <dd class="mt-1 text-2xl leading-9 tabular-nums">
                  {{ number(model.quality.points3D) }}
                </dd>
              </div>
              <div>
                <dt class="meta">Репроекция</dt>
                <dd class="mt-1 text-2xl leading-9 tabular-nums">
                  {{ model.quality.meanReprojectionErrorPx?.toFixed(2) ?? "—"
                  }}<small class="ml-1 text-sm text-muted">px</small>
                </dd>
              </div>
            </dl>
            <div>
              <div
                class="mb-3 flex flex-wrap items-center justify-between gap-2"
              >
                <h3 class="text-sm font-medium">Покрытие по времени</h3>
                <span class="meta tabular-nums"
                  >Наибольший пропуск:
                  {{ model.quality.maxGapSec.toFixed(2) }} с</span
                >
              </div>
              <div
                class="flex h-7 w-full overflow-hidden rounded bg-active"
                role="group"
                aria-label="Временные интервалы поз"
              >
                <button
                  v-for="(interval, i) in timeline"
                  :key="i"
                  class="h-full min-w-0 shrink-0 hover:opacity-70 focus-visible:z-10 focus-visible:outline-offset-[-2px]"
                  :class="interval.valid ? 'bg-accent' : 'bg-control'"
                  :style="{
                    width:
                      Math.max(
                        0,
                        ((interval.end - interval.start) / (duration || 1)) *
                          100,
                      ) + '%',
                  }"
                  :aria-label="`${interval.valid ? 'Есть позы' : 'Нет позы'} с ${interval.start.toFixed(2)} секунды`"
                  :title="`${interval.start.toFixed(2)} с: ${interval.valid ? 'позы доступны' : 'пропуск'}`"
                  @click="seek(interval.start)"
                ></button>
              </div>
              <div
                class="mt-2 flex flex-wrap items-center justify-between gap-3 text-[13px] text-muted"
              >
                <span class="tabular-nums">0:00</span>
                <div class="flex gap-4">
                  <span class="flex items-center gap-1.5"
                    ><span class="size-2 rounded-sm bg-accent"></span>Есть
                    позы</span
                  ><span class="flex items-center gap-1.5"
                    ><span class="size-2 rounded-sm bg-control"></span
                    >Пропуск</span
                  >
                </div>
                <span class="tabular-nums">{{ clock(duration) }}</span>
              </div>
            </div>
            <div
              v-if="trajectory.warnings.length"
              class="rounded-md bg-notice-soft px-3 py-2.5 text-[13px] leading-5 text-notice"
            >
              <ul class="space-y-1">
                <li v-for="warning in trajectory.warnings" :key="warning">
                  {{ warning }}
                </li>
              </ul>
            </div>
            <p class="text-[13px] leading-5 text-muted">
              Репроекция измеряется в пикселях обработанного кадра, а не в
              метрах. Координаты имеют условный масштаб, без геопривязки. Между
              моделями нет общей системы координат.
            </p>
            <details class="border-t border-line pt-3">
              <summary class="text-[13px] font-medium text-muted">
                Настройки этого результата
              </summary>
              <dl
                class="mt-3 grid grid-cols-[1fr_auto] gap-x-6 gap-y-2 text-[13px] sm:max-w-md"
              >
                <template v-for="(value, key) in trajectory.settings" :key="key"
                  ><dt>
                    {{
                      parameterFields.find((field) => field.key === key)
                        ?.label || key
                    }}
                  </dt>
                  <dd class="text-right tabular-nums">{{ value }}</dd></template
                >
              </dl>
              <p class="meta mt-3">
                {{ trajectory.engine }} · {{ trajectory.poseConvention }}
              </p>
              <p class="meta mt-3 break-all">
                {{ trajectory.createdAt }} · {{ trajectory.runId }}
              </p>
            </details>
          </div>
        </section>

        <section class="panel mt-6" aria-labelledby="history-title">
          <div class="panel-title">
            <h2 id="history-title" class="panel-name">
              <UiIcon name="folder" :size="17" class="text-muted" />Сохранённые
              маршруты
            </h2>
            <button class="btn btn-quiet" @click="perform(loadHistory)">
              <UiIcon name="refresh" :size="14" /><span
                class="sr-only sm:not-sr-only"
                >Обновить</span
              >
            </button>
          </div>
          <div v-if="!history.length" class="flex items-start gap-3 px-4 py-5">
            <UiIcon name="clock" :size="18" class="mt-0.5 text-muted" />
            <div>
              <p class="text-sm">Ещё нет сохранённых маршрутов</p>
              <p class="mt-1 text-[13px] leading-5 text-muted">
                Завершённые результаты появятся здесь и сохранятся после
                перезапуска.
              </p>
            </div>
          </div>
          <ul v-else class="divide-y divide-line">
            <li v-for="item in history" :key="item.runId">
              <button
                class="flex w-full flex-wrap items-center justify-between gap-3 px-4 py-4 text-left transition-colors hover:bg-raised"
                @click="loadResult(item.runId)"
              >
                <span class="min-w-0 flex-1"
                  ><strong class="block break-all text-sm font-medium">{{
                    item.videoName
                  }}</strong
                  ><small class="mt-1 block text-[13px] text-muted">{{
                    new Date(item.createdAt).toLocaleString("ru-RU")
                  }} · {{ engineLabel(item.engine) }}</small></span
                ><span class="flex items-center gap-4"
                  ><span class="text-right text-[13px]"
                    ><span class="block">{{
                      item.state === "partial"
                        ? "Частичный результат"
                        : "Восстановлено"
                    }}</span
                    ><span class="mt-1 block text-muted tabular-nums"
                      >{{ item.registeredFrames }} /
                      {{ item.sampledFrames }} кадров</span
                    ></span
                  ><UiIcon name="chevron" :size="16" class="text-muted"
                /></span>
              </button>
            </li>
          </ul>
        </section>
        <footer
          class="mt-5 flex flex-wrap items-center justify-between gap-2 text-[13px] text-muted"
        >
          <span>Траектория · локальная реконструкция</span
          ><span class="flex items-center gap-1.5"
            ><UiIcon name="info" :size="13" />Условный масштаб</span
          >
        </footer>
      </main>
    </div>
  </div>
</template>

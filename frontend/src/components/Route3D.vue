<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from "vue";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { Model } from "../api";
import { contiguousSegments, poseAt } from "../trajectory";
const props = defineProps<{ model: Model; time: number }>();
const host = ref<HTMLDivElement | null>(null),
  available = ref(true);
const scene = new THREE.Scene(),
  camera = new THREE.PerspectiveCamera(45, 1, 0.01, 10000);
const routes = new THREE.Group(),
  marker = new THREE.Group();
let renderer: THREE.WebGLRenderer | undefined,
  controls: OrbitControls | undefined,
  resize: ResizeObserver | undefined,
  animation = 0;
let extent = 1;
const accent = new THREE.Color();
const future = new THREE.Color();
scene.add(routes, marker);
function disposeGroup(group: THREE.Group) {
  group.traverse((object) => {
    if (object instanceof THREE.Line || object instanceof THREE.Mesh) {
      object.geometry.dispose();
      const materials = Array.isArray(object.material)
        ? object.material
        : [object.material];
      materials.forEach((m) => m.dispose());
    }
  });
  group.clear();
}
function fit() {
  const positions = props.model.samples
    .filter((s) => s.position)
    .map((s) => new THREE.Vector3(...s.position!));
  const bounds = new THREE.Box3().setFromPoints(positions),
    center = bounds.getCenter(new THREE.Vector3());
  extent = Math.max(bounds.getSize(new THREE.Vector3()).length(), 1);
  camera.near = Math.max(extent / 10000, 0.001);
  camera.far = extent * 100;
  camera.updateProjectionMatrix();
  camera.position
    .copy(center)
    .add(new THREE.Vector3(0.8, 0.7, 1).multiplyScalar(extent));
  controls?.target.copy(center);
  controls?.update();
}
function draw() {
  disposeGroup(routes);
  disposeGroup(marker);
  for (const segment of contiguousSegments(props.model.samples)) {
    const geometry = new THREE.BufferGeometry().setFromPoints(
      segment.map((s) => new THREE.Vector3(...s.position!)),
    );
    geometry.setAttribute(
      "color",
      new THREE.Float32BufferAttribute(
        segment.flatMap(() => [future.r, future.g, future.b]),
        3,
      ),
    );
    const line = new THREE.Line(
      geometry,
      new THREE.LineBasicMaterial({ vertexColors: true }),
    );
    line.userData.times = segment.map((s) => s.timeSec);
    routes.add(line);
  }
  fit();
  // A wire camera looks along local +Z (COLMAP convention), with local +Y down.
  const size = extent * 0.018,
    vertices: number[] = [];
  const corners = [
    [-size, -size, size * 1.6],
    [size, -size, size * 1.6],
    [size, size, size * 1.6],
    [-size, size, size * 1.6],
  ];
  corners.forEach((corner, i) =>
    vertices.push(0, 0, 0, ...corner, ...corner, ...corners[(i + 1) % 4]),
  );
  const geometry = new THREE.BufferGeometry().setAttribute(
    "position",
    new THREE.Float32BufferAttribute(vertices, 3),
  );
  marker.add(
    new THREE.LineSegments(
      geometry,
      new THREE.LineBasicMaterial({ color: accent }),
    ),
  );
  updatePose();
}
function updatePose() {
  const pose = poseAt(props.model.samples, props.time);
  routes.children.forEach((object) => {
    const line = object as THREE.Line;
    const color = line.geometry.getAttribute("color");
    (line.userData.times as number[]).forEach((time, i) => {
      const past = time <= props.time;
      color.setXYZ(
        i,
        ...((past
          ? [accent.r, accent.g, accent.b]
          : [future.r, future.g, future.b]) as [number, number, number]),
      );
    });
    color.needsUpdate = true;
  });
  marker.visible = !!pose;
  if (pose?.position && pose.orientationXyzw) {
    marker.position.set(...pose.position);
    marker.quaternion.set(...pose.orientationXyzw);
  }
}
function orbit(angle: number) {
  if (!controls) return;
  camera.position
    .sub(controls.target)
    .applyAxisAngle(new THREE.Vector3(0, 1, 0), angle)
    .add(controls.target);
  controls.update();
}
function move(x: number, y: number, z: number) {
  camera.position.add(new THREE.Vector3(x, y, z).multiplyScalar(extent * 0.1));
  controls?.update();
}
onMounted(() => {
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    const tokens = getComputedStyle(document.documentElement);
    accent.set(tokens.getPropertyValue("--color-accent").trim());
    future.set(tokens.getPropertyValue("--color-route-future").trim());
    renderer.setClearColor(tokens.getPropertyValue("--color-raised").trim());
    host.value!.append(renderer.domElement);
  } catch {
    available.value = false;
    return;
  }
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  resize = new ResizeObserver(() => {
    if (!host.value || !renderer) return;
    const { clientWidth: w, clientHeight: h } = host.value;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  });
  resize.observe(host.value!);
  draw();
  const tick = () => {
    controls?.update();
    renderer?.render(scene, camera);
    animation = requestAnimationFrame(tick);
  };
  tick();
});
watch(() => props.model, draw);
watch(() => props.time, updatePose);
onBeforeUnmount(() => {
  cancelAnimationFrame(animation);
  resize?.disconnect();
  controls?.dispose();
  disposeGroup(routes);
  disposeGroup(marker);
  renderer?.dispose();
  renderer?.domElement.remove();
});
</script>
<template>
  <div
    v-if="available"
    ref="host"
    class="h-[300px] w-full min-w-0 overflow-hidden bg-raised [&_canvas]:block sm:h-[320px] xl:h-[260px]"
    aria-label="Траектория камеры в 3D"
  ></div>
  <p v-else class="bg-raised p-6 text-sm text-muted" role="status">
    WebGL недоступен. Используйте 2D-проекцию.
  </p>
  <div class="flex flex-wrap gap-1.5 px-4 py-2">
    <button class="route-control mr-auto" @click="fit">Весь путь</button
    ><button
      class="route-control"
      :disabled="!available"
      aria-label="Приблизить 3D"
      @click="camera.position.lerp(controls!.target, 0.2)"
    >
      +</button
    ><button
      class="route-control"
      :disabled="!available"
      aria-label="Отдалить 3D"
      @click="camera.position.lerp(controls!.target, -0.25)"
    >
      −
    </button>
    <div class="flex basis-full gap-1.5 sm:basis-auto">
      <button
        class="route-control flex-1 sm:flex-none"
        aria-label="Повернуть вид влево"
        @click="orbit(-0.25)"
      >
        ↶</button
      ><button
        class="route-control flex-1 sm:flex-none"
        aria-label="Повернуть вид вправо"
        @click="orbit(0.25)"
      >
        ↷</button
      ><button
        class="route-control flex-1 sm:flex-none"
        aria-label="Сдвинуть камеру влево"
        @click="move(-1, 0, 0)"
      >
        ←</button
      ><button
        class="route-control flex-1 sm:flex-none"
        aria-label="Сдвинуть камеру вправо"
        @click="move(1, 0, 0)"
      >
        →
      </button>
    </div>
  </div>
  <p class="px-4 pb-3 text-[13px] leading-5 text-muted">
    Перетаскивание — вращение, правая кнопка — сдвиг, колесо — масштаб. Каркас
    показывает направление камеры.
  </p>
</template>

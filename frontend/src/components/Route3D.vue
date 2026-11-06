<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import type { Model } from '../api'
import { contiguousSegments, poseAt } from '../trajectory'
const props=defineProps<{model:Model;time:number}>()
const host=ref<HTMLDivElement|null>(null), available=ref(true)
const scene=new THREE.Scene(), camera=new THREE.PerspectiveCamera(45,1,.01,10000)
const routes=new THREE.Group(), marker=new THREE.Group()
let renderer:THREE.WebGLRenderer|undefined, controls:OrbitControls|undefined, resize:ResizeObserver|undefined, animation=0
let extent=1
scene.add(routes,marker)
function disposeGroup(group:THREE.Group) {
  group.traverse(object=>{if(object instanceof THREE.Line||object instanceof THREE.Mesh){object.geometry.dispose();const materials=Array.isArray(object.material)?object.material:[object.material];materials.forEach(m=>m.dispose())}})
  group.clear()
}
function fit() {
  const positions=props.model.samples.filter(s=>s.position).map(s=>new THREE.Vector3(...s.position!))
  const bounds=new THREE.Box3().setFromPoints(positions), center=bounds.getCenter(new THREE.Vector3())
  extent=Math.max(bounds.getSize(new THREE.Vector3()).length(),1)
  camera.near=Math.max(extent/10000,.001);camera.far=extent*100;camera.updateProjectionMatrix()
  camera.position.copy(center).add(new THREE.Vector3(.8,.7,1).multiplyScalar(extent))
  controls?.target.copy(center);controls?.update()
}
function draw() {
  disposeGroup(routes);disposeGroup(marker)
  for(const segment of contiguousSegments(props.model.samples)) {
    const geometry=new THREE.BufferGeometry().setFromPoints(segment.map(s=>new THREE.Vector3(...s.position!)))
    geometry.setAttribute('color',new THREE.Float32BufferAttribute(segment.flatMap(()=>[.6,.67,.7]),3))
    const line=new THREE.Line(geometry,new THREE.LineBasicMaterial({vertexColors:true}))
    line.userData.times=segment.map(s=>s.timeSec)
    routes.add(line)
  }
  fit()
  // A wire camera looks along local +Z (COLMAP convention), with local +Y down.
  const size=extent*.018, vertices:number[]=[]
  const corners=[[-size,-size,size*1.6],[size,-size,size*1.6],[size,size,size*1.6],[-size,size,size*1.6]]
  corners.forEach((corner,i)=>vertices.push(0,0,0,...corner,...corner,...corners[(i+1)%4]))
  const geometry=new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(vertices,3))
  marker.add(new THREE.LineSegments(geometry,new THREE.LineBasicMaterial({color:0xb45135})))
  updatePose()
}
function updatePose() {
  const pose=poseAt(props.model.samples,props.time)
  routes.children.forEach(object=>{const line=object as THREE.Line;const color=line.geometry.getAttribute('color');(line.userData.times as number[]).forEach((time,i)=>{const past=time<=props.time;color.setXYZ(i,...(past?[.13,.4,.47]:[.62,.69,.72]) as [number,number,number])});color.needsUpdate=true})
  marker.visible=!!pose
  if(pose?.position&&pose.orientationXyzw){marker.position.set(...pose.position);marker.quaternion.set(...pose.orientationXyzw)}
}
function orbit(angle:number){if(!controls)return;camera.position.sub(controls.target).applyAxisAngle(new THREE.Vector3(0,1,0),angle).add(controls.target);controls.update()}
function move(x:number,y:number,z:number){camera.position.add(new THREE.Vector3(x,y,z).multiplyScalar(extent*.1));controls?.update()}
onMounted(()=>{
  try{renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor(0xf0f3f4);host.value!.append(renderer.domElement)}catch{available.value=false;return}
  controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true
  resize=new ResizeObserver(()=>{if(!host.value||!renderer)return;const {clientWidth:w,clientHeight:h}=host.value;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix()});resize.observe(host.value!)
  draw()
  const tick=()=>{controls?.update();renderer?.render(scene,camera);animation=requestAnimationFrame(tick)};tick()
})
watch(()=>props.model,draw);watch(()=>props.time,updatePose)
onBeforeUnmount(()=>{cancelAnimationFrame(animation);resize?.disconnect();controls?.dispose();disposeGroup(routes);disposeGroup(marker);renderer?.dispose();renderer?.domElement.remove()})
</script>
<template><div v-if="available" ref="host" class="scene-3d" aria-label="Траектория камеры в 3D"></div><p v-else role="status">WebGL недоступен. Используйте 2D-проекцию.</p><div class="route-controls"><button @click="fit">Весь путь</button><button aria-label="Приблизить 3D" @click="camera.position.lerp(controls!.target,.2)">+</button><button aria-label="Отдалить 3D" @click="camera.position.lerp(controls!.target,-.25)">−</button><button aria-label="Повернуть вид влево" @click="orbit(-.25)">↶</button><button aria-label="Повернуть вид вправо" @click="orbit(.25)">↷</button><button aria-label="Сдвинуть камеру влево" @click="move(-1,0,0)">←</button><button aria-label="Сдвинуть камеру вправо" @click="move(1,0,0)">→</button></div><p class="hint">Перетаскивание — вращение, правая кнопка — сдвиг, колесо — масштаб. Каркас показывает направление камеры.</p></template>

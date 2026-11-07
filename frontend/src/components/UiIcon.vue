<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 18 });
const paths: Record<string, string> = {
  route:
    "M5 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM19 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM5 17v-5a3 3 0 0 1 3-3h8a3 3 0 0 0 3-3",
  video:
    "M15 10l5-3v10l-5-3M4 6h9a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Z",
  upload: "M12 16V3m-5 5 5-5 5 5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4",
  play: "m9 5 11 7-11 7V5Z",
  pause: "M8 5v14M16 5v14",
  arrow: "M5 12h14m-5-5 5 5-5 5",
  chevron: "m9 5 7 7-7 7",
  download: "M12 3v12m-5-5 5 5 5-5M4 17v3h16v-3",
  settings: "M4 6h16M4 12h16M4 18h16M8 3v6M16 9v6M10 15v6",
  refresh:
    "M20 10a8 8 0 0 0-14-5L3 8m0-5v5h5M4 14a8 8 0 0 0 14 5l3-3m0 5v-5h-5",
  clock: "M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z",
  cpu: "M8 3v3m8-3v3M8 18v3m8-3v3M3 8h3m-3 8h3M18 8h3m-3 8h3M6 6h12v12H6V6Zm4 4h4v4h-4v-4Z",
  folder: "M3 7V5h6l2 2h10v13H3V7Z",
  close: "m6 6 12 12M6 18 18 6",
  check: "m5 12 4 4L19 6",
  info: "M12 11v6m0-10v.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z",
  cube: "m12 3 9 5v9l-9 5-9-5V8l9-5Zm0 10 9-5M12 13 3 8m9 5v9",
};
</script>
<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    class="shrink-0"
  >
    <path :d="paths[name] || paths.route" />
  </svg>
</template>

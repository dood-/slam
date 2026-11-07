import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";

const proxy = { "/api": process.env.SLAM_API_URL || "http://127.0.0.1:8000" };

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: { host: "127.0.0.1", proxy },
  preview: { host: "127.0.0.1", proxy },
});

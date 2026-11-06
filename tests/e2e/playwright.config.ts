import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'
const root=fileURLToPath(new URL('../../',import.meta.url))
export default defineConfig({testDir:'.',timeout:30_000,workers:1,
 use:{baseURL:'http://127.0.0.1:14173',launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE},trace:'retain-on-failure'},
 webServer:[
  {command:'PYTHONPATH=backend backend/.venv/bin/python tests/e2e/server.py',cwd:root,wait:{stderr:/Uvicorn running/}},
  {command:'npm --prefix frontend run build && npm --prefix frontend run preview -- --host 127.0.0.1 --port 14173 --strictPort',cwd:root,wait:{stdout:/Local:/},env:{SLAM_API_URL:'http://127.0.0.1:18000'},timeout:60_000}
 ]})

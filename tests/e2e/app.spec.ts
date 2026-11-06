import { test, expect } from '@playwright/test'

const fixture = process.env.E2E_FIXTURE

test.skip(!fixture, 'Set E2E_FIXTURE to a tiny H264 fixture for the controlled backend.')

test('upload, preview, controls, model switch and exports', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Выбрать MP4').setInputFiles(fixture!)
  await expect(page.locator('video')).toBeVisible()
  await page.getByRole('button', { name: 'Восстановить маршрут' }).click()
  await expect(page.getByRole('heading', { name: /Путь камеры/ })).toBeVisible()
  await expect(page.locator('canvas, svg[aria-label="Траектория камеры в 2D"]')).toHaveCount(1)
  await page.getByRole('button', { name: '3D' }).click()
  await expect(page.getByLabel('Траектория камеры в 3D')).toBeVisible()
  await page.getByRole('button', { name: '2D' }).click()
  await page.getByLabel('Время видео').fill('0.2')
  await expect(page.getByTestId('pose-status')).toBeVisible()
  await expect(page.getByRole('link', { name: 'JSON ↓' })).toHaveAttribute('href', /format=json/)
  await expect(page.getByRole('link', { name: 'CSV ↓' })).toHaveAttribute('href', /format=csv/)
})

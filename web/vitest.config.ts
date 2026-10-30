import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte({ hot: false })],
  resolve: {
    conditions: ['browser'],
    alias: { $lib: fileURLToPath(new URL('./src/lib', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest-setup.ts'],
    // vitest blanks every .css by default; tokens.test.ts reads the sources with ?raw
    css: { include: [/\.css\?raw$/] },
  },
})

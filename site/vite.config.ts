import tailwindcss from '@tailwindcss/vite'
import { tanstackStart } from '@tanstack/react-start/plugin/vite'
import viteReact from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    port: 3000,
  },
  resolve: {
    // Алиас `@/*` читается из tsconfig.json — единственный источник правды.
    tsconfigPaths: true,
  },
  plugins: [
    tailwindcss(),
    // Порядок важен: tanstackStart должен стоять перед React-плагином.
    tanstackStart({
      router: {
        // Путь относительно srcDirectory (`src`): тонкие file routes живут в FSD-слое app.
        routesDirectory: 'app/routes',
      },
    }),
    viteReact(),
  ],
})

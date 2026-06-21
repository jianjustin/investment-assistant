import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#111827',
        muted: '#6b7280',
        panel: '#f8fafc',
        line: '#d9e2ec',
        accent: '#0f766e',
        warn: '#b45309',
      },
      boxShadow: {
        soft: '0 14px 35px rgba(15, 23, 42, 0.08)',
      },
    },
  },
  plugins: [],
} satisfies Config

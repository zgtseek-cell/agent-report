/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'slate-dark': '#0D1117',
        'slate-panel': 'rgba(22, 27, 34, 0.95)',
        'emerald-theme': '#10B981',
        'emerald-hover': '#34D399',
      },
    },
  },
  plugins: [],
}

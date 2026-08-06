/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'brand-purple': '#631acb',
        'brand-purple-light': 'rgba(99, 26, 203, 0.55)',
        'dark-bg': '#0d1117',
        'dark-card': '#161b22',
        'dark-border': '#30363d',
      }
    },
  },
  plugins: [],
}

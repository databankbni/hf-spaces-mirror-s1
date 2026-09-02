import type { Config } from "tailwindcss";

export default {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        page: "#0f1117",
        panel: {
          DEFAULT: "#181c27",
          user: "#28304a",
          bot: "#1c2231",
        },
        line: "#30364d",
        accent: {
          DEFAULT: "#5c6ef7",
          hover: "#7686ff",
        },
        ink: {
          DEFAULT: "#eef1fb",
          muted: "#9ba3bd",
        },
        danger: "#e05252",
        success: "#43c78a",
        warn: "#d4a843",
      },
      fontFamily: {
        sans: ["Be Vietnam Pro", "system-ui", "sans-serif"],
      },
      keyframes: {
        bounce3: {
          "0%, 80%, 100%": { transform: "scale(.6)", opacity: ".4" },
          "40%": { transform: "scale(1)", opacity: "1" },
        },
      },
      animation: {
        bounce3: "bounce3 1.2s infinite ease-in-out",
      },
    },
  },
  plugins: [],
} satisfies Config;

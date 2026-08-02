/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "#1e40af",
          dark: "#3b82f6",
        },
        accent: "#16a34a",
      },
      fontFamily: {
        serif: ["Noto Serif SC", "Source Han Serif", "serif"],
      },
    },
  },
  plugins: [],
  darkMode: "class",
};
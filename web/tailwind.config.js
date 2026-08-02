/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: "#1e40af",
        accent: "#16a34a",
      },
      fontFamily: {
        serif: ["Noto Serif SC", "Source Han Serif", "serif"],
      },
    },
  },
  plugins: [],
};
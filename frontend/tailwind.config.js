/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "Segoe UI", "system-ui", "-apple-system", "sans-serif"] },
      colors: {
        brand: { 50: "#eef7f6", 100: "#d5ecea", 200: "#a9d8d4", 500: "#1f8a83", 600: "#17716b", 700: "#135c57", 800: "#0f4844" },
      },
    },
  },
  plugins: [],
};

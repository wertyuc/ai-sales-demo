/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#080a12",
          900: "#0c0f1a",
          850: "#111527",
          800: "#161b30",
          700: "#1e2439",
          600: "#2a3149",
          500: "#3a4260",
          400: "#586182",
        },
        brand: {
          50: "#eef2ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
        },
        hot: "#fb923c",
        warm: "#fbbf24",
        cold: "#64748b",
        critical: "#f43f5e",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Arial", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(0,0,0,.28), 0 8px 24px -12px rgba(0,0,0,.55)",
        pop: "0 12px 40px -12px rgba(0,0,0,.7)",
      },
      keyframes: {
        "fade-in": { from: { opacity: 0, transform: "translateY(4px)" }, to: { opacity: 1, transform: "none" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "pulse-ring": {
          "0%": { boxShadow: "0 0 0 0 rgba(244,63,94,.45)" },
          "70%": { boxShadow: "0 0 0 8px rgba(244,63,94,0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(244,63,94,0)" },
        },
      },
      animation: {
        "fade-in": "fade-in .22s ease-out",
        shimmer: "shimmer 1.6s infinite",
        "pulse-ring": "pulse-ring 1.8s infinite",
      },
    },
  },
  plugins: [],
};

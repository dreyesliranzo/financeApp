/** Tailwind config for Pulse Finance (used with CDN inline config in base.html) */
module.exports = {
  content: ["./templates/**/*.html", "./finance_app/**/*.py"],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: "#4f8dff", dark: "#3f6ee8" },
        accent: "#a78bfa",
        success: "#34d399",
        danger: "#ef4444",
        warning: "#fbbf24",
        info: "#38bdf8",
        bg: "#050816",
        "bg-elevated": "#0f1728",
        border: "rgba(255,255,255,0.08)",
        "text-primary": "#e8edf5",
        "text-muted": "#9bacc7",
      },
      boxShadow: {
        card: "0 18px 45px rgba(0,0,0,0.55)",
        button: "0 0 25px rgba(79,141,255,0.55)",
      },
      borderRadius: {
        xl2: "1.25rem",
      },
    },
  },
  plugins: [],
};

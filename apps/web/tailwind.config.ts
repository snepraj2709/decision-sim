import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      // Tailwind utility colors backed by the same CSS vars from tokens.css.
      // Both `bg-bg`, `text-ink`, etc. AND inline `style={{ color: "var(--ink)" }}`
      // resolve to the same values. This avoids drift between the token system
      // and Tailwind utilities.
      colors: {
        bg: "var(--bg)",
        "bg-sunken": "var(--bg-sunken)",
        "bg-elevated": "var(--bg-elevated)",
        line: "var(--line)",
        "line-strong": "var(--line-strong)",
        "line-soft": "var(--line-soft)",
        ink: "var(--ink)",
        "ink-2": "var(--ink-2)",
        "ink-3": "var(--ink-3)",
        "ink-4": "var(--ink-4)",
        accent: "var(--accent)",
        "accent-soft": "var(--accent-soft)",
        "conf-high": "var(--conf-high)",
        "conf-high-soft": "var(--conf-high-soft)",
        "conf-high-line": "var(--conf-high-line)",
        "conf-med": "var(--conf-med)",
        "conf-med-soft": "var(--conf-med-soft)",
        "conf-med-line": "var(--conf-med-line)",
        "conf-low": "var(--conf-low)",
        "conf-low-soft": "var(--conf-low-soft)",
        "conf-low-line": "var(--conf-low-line)",
      },
    },
  },
  plugins: [],
};

export default config;

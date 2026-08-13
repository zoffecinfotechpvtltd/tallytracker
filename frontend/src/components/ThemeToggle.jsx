import { useEffect, useState } from "react";

const STORAGE_KEY = "tt_theme";

function systemPrefersDark() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function readInitialTheme() {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return systemPrefersDark() ? "dark" : "light";
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(readInitialTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const isDark = theme === "dark";

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Light mode" : "Dark mode"}
    >
      <svg
        width="17"
        height="17"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={"theme-toggle-icon" + (isDark ? " is-dark" : "")}
      >
        <circle className="theme-toggle-sun" cx="12" cy="12" r="4.3" />
        <g className="theme-toggle-rays">
          <line x1="12" y1="1.5" x2="12" y2="3.7" />
          <line x1="12" y1="20.3" x2="12" y2="22.5" />
          <line x1="4.2" y1="4.2" x2="5.7" y2="5.7" />
          <line x1="18.3" y1="18.3" x2="19.8" y2="19.8" />
          <line x1="1.5" y1="12" x2="3.7" y2="12" />
          <line x1="20.3" y1="12" x2="22.5" y2="12" />
          <line x1="4.2" y1="19.8" x2="5.7" y2="18.3" />
          <line x1="18.3" y1="5.7" x2="19.8" y2="4.2" />
        </g>
        <path
          className="theme-toggle-moon"
          d="M20.5 14.8A8.5 8.5 0 1 1 9.2 3.5a7 7 0 0 0 11.3 11.3z"
        />
      </svg>
    </button>
  );
}

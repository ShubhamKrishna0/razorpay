import { NavLink, Outlet } from "react-router-dom";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { currentTheme, toggleTheme, type Theme } from "../lib/theme";
import { useAsync } from "../hooks/useAsync";

const NAV = [
  { to: "/", label: "Control Tower", end: true },
  { to: "/exceptions", label: "Exceptions" },
  { to: "/chat", label: "Finance Chat" },
  { to: "/benchmark", label: "Benchmark" },
];

export function Layout() {
  const [theme, setThemeState] = useState<Theme>(currentTheme);
  const { data: config } = useAsync(() => api.config(), []);

  useEffect(() => {
    setThemeState(currentTheme());
  }, []);

  return (
    <div className="min-h-full">
      <header
        className="sticky top-0 z-20 border-b backdrop-blur"
        style={{ borderColor: "var(--border-hairline)", background: "var(--surface-1)" }}
      >
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <span
              className="grid h-7 w-7 place-items-center rounded text-xs font-bold text-white"
              style={{ background: "var(--series-1)" }}
              aria-hidden
            >
              ₹
            </span>
            <div>
              <div className="text-sm font-semibold leading-tight text-ink">
                AI Finance Controller
              </div>
              <div className="text-[11px] leading-tight text-muted">
                Deterministic reconciliation · AI exception control
              </div>
            </div>
          </div>

          <nav className="flex flex-wrap gap-1" aria-label="Main">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                    isActive ? "text-ink" : "text-ink-2 hover:text-ink"
                  }`
                }
                style={({ isActive }) =>
                  isActive
                    ? { background: "var(--gridline)" }
                    : undefined
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            {config && (
              <span
                className="hidden items-center gap-1.5 text-[11px] text-ink-2 sm:inline-flex"
                title={
                  config.ai.configured
                    ? `${config.ai.provider} · ${config.ai.model} · effort ${config.ai.effort}`
                    : "Set ANTHROPIC_API_KEY or GEMINI_API_KEY to enable the AI controller"
                }
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{
                    background: config.ai.configured
                      ? "var(--status-good)"
                      : "var(--text-muted)",
                  }}
                  aria-hidden
                />
                {config.ai.configured ? config.ai.model : "AI not configured"}
              </span>
            )}
            <button
              type="button"
              onClick={() => setThemeState(toggleTheme())}
              className="rounded-md border px-2 py-1 text-[11px] text-ink-2 hover:text-ink"
              style={{ borderColor: "var(--border-hairline)" }}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            >
              {theme === "dark" ? "Light" : "Dark"}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>

      <footer className="mx-auto max-w-7xl px-4 pb-8 pt-2 text-[11px] text-muted">
        Deterministic engine closes the books; the AI investigates only what the rules cannot.
        Nothing is auto-resolved below the configured confidence threshold.
      </footer>
    </div>
  );
}

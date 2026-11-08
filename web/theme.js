"use strict";

// Apply the theme before the stylesheet loads to avoid a flash on return visits.
(() => {
  const storageKey = "desktop-buddy-theme";
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  let preference = null;
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === "light" || saved === "dark") preference = saved;
  } catch {
    // The switch still works when browser storage is unavailable.
  }

  function applyTheme() {
    const theme = preference || (systemTheme.matches ? "dark" : "light");
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]').content = theme === "dark" ? "#151c18" : "#f8f9f3";
    const button = document.querySelector("#theme-toggle");
    if (!button) return;
    const dark = theme === "dark";
    const label = `Switch to ${dark ? "light" : "dark"} mode`;
    button.setAttribute("aria-label", label);
    button.title = label;
    button.querySelector("use").setAttribute("href", dark ? "#sun-icon" : "#moon-icon");
    button.querySelector(".theme-label").textContent = dark ? "Light mode" : "Dark mode";
  }

  applyTheme();
  systemTheme.addEventListener("change", () => {
    if (!preference) applyTheme();
  });
  document.addEventListener("DOMContentLoaded", () => {
    const button = document.querySelector("#theme-toggle");
    button.hidden = false;
    applyTheme();
    button.addEventListener("click", () => {
      preference = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(storageKey, preference);
      } catch {
        // Keep the visitor's choice for this page even without persistence.
      }
      applyTheme();
    });
  });
})();

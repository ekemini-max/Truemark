/* Progressive enhancements: dark/light theme toggle, clipboard copy, count-up stats, password strength meter, and print handling. */
(function () {
  "use strict";

  // ---- Theme Toggle
  var THEME_KEY = "truemark_theme";

  function getStoredTheme() {
    try {
      return localStorage.getItem(THEME_KEY);
    } catch (e) {
      return null;
    }
  }

  function setStoredTheme(theme) {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (e) {}
  }

  function applyTheme(theme) {
    if (theme === "light") {
      document.documentElement.setAttribute("data-theme", "light");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
    var toggleBtn = document.querySelector("[data-theme-toggle]");
    if (toggleBtn) {
      toggleBtn.setAttribute("aria-label", theme === "light" ? "Switch to dark theme" : "Switch to light theme");
      toggleBtn.innerHTML = theme === "light"
        ? '<svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>'
        : '<svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>';
    }
  }

  function initTheme() {
    var stored = getStoredTheme();
    if (stored) {
      applyTheme(stored);
    } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
      applyTheme("light");
    } else {
      applyTheme("dark");
    }
  }

  initTheme();

  // ---- Clipboard Copy Helper
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(area);
      ok ? resolve() : reject();
    });
  }

  // ---- Password Strength Meter
  function initPasswordMeter() {
    var pwInput = document.querySelector("[data-pw-input]");
    var bar = document.querySelector("[data-pw-bar]");
    if (!pwInput || !bar) return;

    pwInput.addEventListener("input", function () {
      var val = pwInput.value;
      var score = 0;
      if (val.length >= 8) score++;
      if (val.length >= 12) score++;
      if (/[A-Z]/.test(val) && /[a-z]/.test(val)) score++;
      if (/[0-9]/.test(val)) score++;
      if (/[^A-Za-z0-9]/.test(val)) score++;

      var pct = Math.min(100, (score / 4) * 100);
      bar.style.width = pct + "%";
      if (score <= 1) bar.style.backgroundColor = "var(--coral)";
      else if (score <= 3) bar.style.backgroundColor = "var(--amber)";
      else bar.style.backgroundColor = "var(--emerald)";
    });
  }

  // ---- Animated Stat Counters
  function initCounters() {
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: reduce)").matches) return;
    var counts = document.querySelectorAll("[data-count-to]");
    counts.forEach(function (el) {
      var target = parseInt(el.getAttribute("data-count-to"), 10);
      if (isNaN(target)) return;
      var start = 0;
      var duration = 1000;
      var startTime = null;

      function step(timestamp) {
        if (!startTime) startTime = timestamp;
        var progress = Math.min((timestamp - startTime) / duration, 1);
        el.textContent = Math.floor(progress * target);
        if (progress < 1) {
          window.requestAnimationFrame(step);
        } else {
          el.textContent = target;
        }
      }
      window.requestAnimationFrame(step);
    });
  }

  // ---- Event Delegation
  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-theme-toggle]");
    if (toggle) {
      var current = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
      var next = current === "light" ? "dark" : "light";
      setStoredTheme(next);
      applyTheme(next);
      return;
    }

    var copy = event.target.closest("[data-copy]");
    if (copy) {
      var original = copy.textContent;
      copyText(copy.getAttribute("data-copy")).then(function () {
        copy.textContent = "Copied";
        setTimeout(function () { copy.textContent = original; }, 1600);
      }, function () {
        copy.textContent = "Press Ctrl+C to copy";
      });
      return;
    }

    if (event.target.closest("[data-print]")) {
      window.print();
      return;
    }

    var fill = event.target.closest("[data-fill]");
    if (fill) {
      var form = document.getElementById(fill.getAttribute("data-fill"));
      var values = {};
      try { values = JSON.parse(form.getAttribute("data-values") || "{}"); } catch (e) { values = {}; }
      Object.keys(values).forEach(function (name) {
        if (form.elements[name]) form.elements[name].value = values[name];
      });
    }
  });

  document.addEventListener("submit", function (event) {
    var message = event.target.getAttribute("data-confirm");
    if (message && !window.confirm(message)) event.preventDefault();
  });

  if (typeof document !== "undefined" && document.addEventListener) {
    document.addEventListener("DOMContentLoaded", function () {
      initPasswordMeter();
      initCounters();
    });
  }
})();

/* Small progressive enhancements. Every page works without this file. */
(function () {
  "use strict";

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

  document.addEventListener("click", function (event) {
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
})();

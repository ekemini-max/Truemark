/* Landing-page demo: edit a certificate and watch its fingerprint stop matching.
 *
 * This runs entirely in the browser. It implements the same recipe as app/hashing.py
 * (SHA-256 over salt + "|" + canonical JSON) so the numbers match the server; the test
 * suite checks that. The demo record is NOT on any ledger: the "anchored" fingerprint is
 * simply computed from the original values when the page loads.
 */
(function (root) {
  "use strict";

  var K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];

  function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }

  function sha256Bytes(bytes) {
    var h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var len = bytes.length;
    var padded = new Uint8Array(((len + 9 + 63) >> 6) << 6);
    padded.set(bytes);
    padded[len] = 0x80;
    var view = new DataView(padded.buffer);
    view.setUint32(padded.length - 8, Math.floor((len * 8) / 0x100000000));
    view.setUint32(padded.length - 4, (len * 8) >>> 0);
    var w = new Uint32Array(64);
    for (var off = 0; off < padded.length; off += 64) {
      for (var i = 0; i < 16; i++) w[i] = view.getUint32(off + i * 4);
      for (i = 16; i < 64; i++) {
        var s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        var s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
      }
      var a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
      for (i = 0; i < 64; i++) {
        var S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        var ch = (e & f) ^ (~e & g);
        var t1 = (hh + S1 + ch + K[i] + w[i]) >>> 0;
        var S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) >>> 0;
        hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      h[0] = (h[0] + a) >>> 0; h[1] = (h[1] + b) >>> 0; h[2] = (h[2] + c) >>> 0; h[3] = (h[3] + d) >>> 0;
      h[4] = (h[4] + e) >>> 0; h[5] = (h[5] + f) >>> 0; h[6] = (h[6] + g) >>> 0; h[7] = (h[7] + hh) >>> 0;
    }
    return h.map(function (x) { return ("00000000" + x.toString(16)).slice(-8); }).join("");
  }

  var FIELDS = ["course", "grade", "institution", "issued_on", "record_code", "student_name"]; // sorted, as the server does

  function normalize(value) {
    var text = String(value == null ? "" : value).normalize("NFC").trim();
    return text ? text.split(/\s+/).join(" ") : "";
  }

  function canonical(rec) {
    var data = {};
    FIELDS.forEach(function (key) { data[key] = normalize(rec[key]); });
    return JSON.stringify(data);
  }

  function fingerprint(rec, salt) {
    return "0x" + sha256Bytes(new TextEncoder().encode(salt + "|" + canonical(rec)));
  }

  root.TrueMarkDemo = { fingerprint: fingerprint, canonical: canonical, sha256Bytes: sha256Bytes };

  // ---- page wiring (browser only)

  var SALT = "demo-salt-0001";
  var ORIGINAL = {
    record_code: "TM-2026-DEMO-0001",
    institution: "Greenfield Secondary School",
    student_name: "Amara Okafor",
    course: "Mechanical Engineering",
    grade: "A",
    issued_on: "15 June 2026"
  };

  function shorten(fp) { return fp.slice(0, 18) + "…" + fp.slice(-6); }

  function init() {
    var demo = document.querySelector("[data-demo]");
    if (!demo) return;
    var inputs = demo.querySelectorAll("[data-demo-field]");
    var stamp = demo.querySelector("[data-demo-stamp]");
    var word = stamp.querySelector("b");
    var sub = stamp.querySelector("span");
    var status = demo.querySelector("[data-demo-status]");
    var anchoredEl = demo.querySelector("[data-demo-anchored]");
    var nowEl = demo.querySelector("[data-demo-now]");
    var reset = demo.querySelector("[data-demo-reset]");
    var anchored = fingerprint(ORIGINAL, SALT);
    var lastOk = true;
    anchoredEl.textContent = shorten(anchored);

    function current() {
      var rec = {};
      Object.keys(ORIGINAL).forEach(function (k) { rec[k] = ORIGINAL[k]; });
      inputs.forEach(function (el) { rec[el.getAttribute("data-demo-field")] = el.value; });
      return rec;
    }

    function update() {
      var rec = current();
      var fp = fingerprint(rec, SALT);
      var ok = fp === anchored;
      inputs.forEach(function (el) {
        var key = el.getAttribute("data-demo-field");
        el.closest(".cert__field").classList.toggle("is-changed", normalize(el.value) !== normalize(ORIGINAL[key]));
      });
      stamp.classList.toggle("stamp--altered", !ok);
      word.textContent = ok ? "Valid" : "Invalid";
      sub.textContent = ok ? "Unaltered" : "Altered";
      status.textContent = ok
        ? "This copy matches the fingerprint anchored when the record was issued."
        : "This copy no longer matches the anchored fingerprint, so a verifier would reject it.";
      nowEl.textContent = shorten(fp);
      nowEl.classList.toggle("differs", !ok);
      reset.hidden = ok;
      if (ok !== lastOk && !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) {
        stamp.classList.remove("press");
        void stamp.offsetWidth; // restart the animation
        stamp.classList.add("press");
      }
      lastOk = ok;
    }

    inputs.forEach(function (el) { el.addEventListener("input", update); });
    reset.addEventListener("click", function () {
      inputs.forEach(function (el) { el.value = ORIGINAL[el.getAttribute("data-demo-field")]; });
      update();
    });
    update();
  }

  if (typeof document !== "undefined" && document.addEventListener) {
    document.addEventListener("DOMContentLoaded", init);
  }
})(typeof window !== "undefined" ? window : globalThis);

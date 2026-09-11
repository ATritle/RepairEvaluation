/* /mobile - phone capture page. Enter a repair number, take or choose photos,
 * they upload straight into that repair's photo library (Forge.RepairEval.repair_photo).
 * /mobile/R123456 opens pre-filled (QR code on the job ticket); the address bar
 * follows the Repair # field so the link can be shared. ?r= is still accepted. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const repair = $("#repair"), status = $("#status"), grid = $("#grid"), empty = $("#empty");
  const tech = $("#tech");
  const camBtn = $("#btn-camera"), galBtn = $("#btn-gallery"), cam = $("#cam"), gal = $("#gal");
  const progress = $("#progress"), bar = $("#bar");
  const REPAIR_RE = /^[A-Za-z0-9][A-Za-z0-9 ._/\-]{0,49}$/;
  let current = "";
  let timer = null;

  function toast(msg, isError) {
    const el = $("#toast");
    el.textContent = msg; el.classList.toggle("error", !!isError); el.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2500);
  }
  function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function fmt(iso) { return iso ? new Date(iso).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : ""; }

  function syncUrl() {
    const path = REPAIR_RE.test(current) ? `/mobile/${encodeURIComponent(current)}` : "/mobile";
    if (location.pathname + location.search !== path) history.replaceState(null, "", path);
  }

  // Phones have no domain login, so the technician picks their name once; it is
  // remembered on the device and sent with every upload as uploaded_by.
  async function loadTechnicians() {
    try {
      const cfg = await (await fetch("/api/config")).json();
      for (const t of cfg.technicians || []) {
        const o = document.createElement("option"); o.value = t; o.textContent = t; tech.appendChild(o);
      }
    } catch (_) { /* leave the picker empty; upload will explain */ }
    let saved = "";
    try { saved = localStorage.getItem("ifp_mobile_tech") || ""; } catch (_) { /* ignore */ }
    if (saved && [...tech.options].some((o) => o.value === saved)) tech.value = saved;
    updateButtons();
  }
  tech.addEventListener("change", () => {
    try { localStorage.setItem("ifp_mobile_tech", tech.value); } catch (_) { /* ignore */ }
    updateButtons();
    if (tech.value && !repair.value) repair.focus();
  });

  function updateButtons() {
    const ok = REPAIR_RE.test(current) && !!tech.value;
    camBtn.disabled = galBtn.disabled = !ok;
  }

  function setRepair(v) {
    current = (v || "").trim().toUpperCase();
    const ok = REPAIR_RE.test(current);
    updateButtons();
    syncUrl();
    if (!current) { status.textContent = "Enter the repair number first."; grid.innerHTML = ""; empty.hidden = true; return; }
    if (!ok) { status.textContent = "Letters, digits, space, . _ / - only."; return; }
    try { localStorage.setItem("ifp_mobile_repair", current); } catch (_) { /* ignore */ }
    loadLibrary();
  }

  async function loadLibrary() {
    const rn = current;
    try {
      const res = await fetch(`/api/repairs/${encodeURIComponent(rn)}/photos`);
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const items = await res.json();
      if (rn !== current) return;
      status.innerHTML = `<b>${esc(rn)}</b> · ${items.length} photo${items.length === 1 ? "" : "s"} in library`;
      grid.innerHTML = "";
      empty.hidden = items.length > 0;
      for (const it of items) {
        const fig = document.createElement("figure");
        fig.innerHTML = `<img src="/photos/${encodeURIComponent(it.file)}?thumb=1" alt="" loading="lazy">` +
          (it.in_latest ? `<span class="used">on report</span>` : "") +
          `<button class="rm" title="Remove from library">✕</button>` +
          `<figcaption>${esc(fmt(it.uploaded_at))}${it.source === "mobile" ? " · 📱" : ""}</figcaption>`;
        fig.querySelector("img").addEventListener("click", () => window.open(`/photos/${encodeURIComponent(it.file)}`, "_blank"));
        fig.querySelector(".rm").addEventListener("click", async () => {
          if (!confirm(it.in_latest ? "This photo is on the current report. Remove it from the library anyway? (The report keeps it.)" : "Remove this photo from the library?")) return;
          const r = await fetch(`/api/repairs/${encodeURIComponent(rn)}/photos/${encodeURIComponent(it.file)}`, { method: "DELETE" });
          if (!r.ok) toast("Remove failed", true); else loadLibrary();
        });
        grid.appendChild(fig);
      }
    } catch (err) {
      status.textContent = `Unable to load library: ${err.message}`;
    }
  }

  function upload(files) {
    if (!files.length || !REPAIR_RE.test(current)) return;
    if (!tech.value) { toast("Pick your name first", true); tech.focus(); return; }
    const fd = new FormData();
    fd.append("repair_no", current);
    fd.append("uploaded_by", tech.value);
    for (const f of files) fd.append("files", f, f.name || "photo.jpg");
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/mobile/photos");
    progress.hidden = false; bar.style.width = "0%";
    camBtn.disabled = galBtn.disabled = true;
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.style.width = `${Math.round(e.loaded / e.total * 100)}%`; };
    xhr.onload = () => {
      progress.hidden = true; updateButtons();
      if (xhr.status >= 200 && xhr.status < 300) {
        const n = JSON.parse(xhr.responseText).length;
        toast(`Uploaded ${n} photo${n === 1 ? "" : "s"} to ${current}`);
        if (navigator.vibrate) navigator.vibrate(40);
        loadLibrary();
      } else {
        let msg = xhr.statusText;
        try { msg = JSON.parse(xhr.responseText).detail || msg; } catch (_) { /* ignore */ }
        toast(`Upload failed: ${typeof msg === "string" ? msg : JSON.stringify(msg)}`, true);
      }
    };
    xhr.onerror = () => { progress.hidden = true; updateButtons(); toast("Upload failed: network error", true); };
    xhr.send(fd);
  }

  camBtn.addEventListener("click", () => cam.click());
  galBtn.addEventListener("click", () => gal.click());
  cam.addEventListener("change", (e) => { upload(Array.from(e.target.files)); e.target.value = ""; });
  gal.addEventListener("change", (e) => { upload(Array.from(e.target.files)); e.target.value = ""; });

  repair.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => setRepair(repair.value), 350); });
  repair.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); repair.blur(); setRepair(repair.value); } });

  async function loadRecent() {
    try {
      const list = await (await fetch("/api/repairs/recent?limit=12")).json();
      const box = $("#recent-list"); box.innerHTML = "";
      for (const r of list) {
        const b = document.createElement("button");
        b.innerHTML = `<b>${esc(r.repair_no)}</b> · ${r.photos}`;
        b.addEventListener("click", () => { repair.value = r.repair_no; setRepair(r.repair_no); window.scrollTo(0, 0); });
        box.appendChild(b);
      }
      $("#recent").hidden = list.length === 0;
    } catch (_) { /* ignore */ }
  }

  // Init: /mobile/R123456 or ?r= pre-fills. A bare /mobile starts empty; the
  // last number used on this phone is offered as a tap target, not applied.
  const pathMatch = location.pathname.match(/^\/mobile\/([^/]+)\/?$/i);
  const initial = pathMatch ? decodeURIComponent(pathMatch[1]) : (new URLSearchParams(location.search).get("r") || "");
  repair.value = initial;
  setRepair(initial);
  loadTechnicians();
  if (!initial) {
    let last = "";
    try { last = localStorage.getItem("ifp_mobile_repair") || ""; } catch (_) { /* ignore */ }
    if (last) {
      status.innerHTML = `Enter the repair number, or continue with <button type="button" class="link-btn" id="use-last">${esc(last)}</button>`;
      $("#use-last").addEventListener("click", () => { repair.value = last; setRepair(last); });
    }
    if (tech.value) repair.focus();
  }
  loadRecent();
  setInterval(() => { if (REPAIR_RE.test(current)) loadLibrary(); }, 30000);
})();

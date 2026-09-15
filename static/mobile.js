/* /mobile - phone capture page.
 * Enter a repair number, take or choose photos; they are shrunk on the phone,
 * uploaded into the repair's Photos folder on the N drive, and shown here.
 * /mobile/R123456 opens pre-filled (QR code on the job ticket); the address bar
 * follows the Repair # field. ?r= is still accepted. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const repair = $("#repair"), status = $("#status"), grid = $("#grid"), empty = $("#empty");
  const tech = $("#tech");
  const camBtn = $("#btn-camera"), galBtn = $("#btn-gallery"), cam = $("#cam"), gal = $("#gal");
  const progress = $("#progress"), bar = $("#bar"), queueBox = $("#queue");
  const REPAIR_RE = /^[A-Za-z0-9][A-Za-z0-9 ._/\-]{0,49}$/;
  const MAX_EDGE = 2000;          // matches the server; a 20 MB phone shot leaves as ~1 MB
  let current = "";
  let timer = null;
  let folderOk = false;
  let signedIn = null;            // {user, name} when Windows sign-in is on

  function toast(msg, isError) {
    const el = $("#toast");
    el.textContent = msg; el.classList.toggle("error", !!isError); el.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2500);
  }
  function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function fmt(iso) { return iso ? new Date(iso).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : ""; }
  function kb(n) { return n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`; }

  // ------------------------------------------------------------ who are you
  async function loadTechnicians() {
    try {
      const me = await (await fetch("/api/me")).json();
      if (me.auth_enabled && me.user) {
        signedIn = me;
        tech.closest(".m-field").hidden = true;
        $("#whoami").innerHTML = `Signed in as <b>${esc(me.name || me.user)}</b> · <a href="/logout">sign out</a>`;
        $("#whoami").hidden = false;
        updateButtons();
        return;
      }
    } catch (_) { /* fall through to the picker */ }
    try {
      const cfg = await (await fetch("/api/config")).json();
      for (const t of cfg.technicians || []) {
        const o = document.createElement("option"); o.value = t; o.textContent = t; tech.appendChild(o);
      }
    } catch (_) { /* leave the picker empty */ }
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
    const ok = REPAIR_RE.test(current) && (signedIn || !!tech.value) && folderOk && !uploading;
    camBtn.disabled = galBtn.disabled = !ok;
  }

  // ------------------------------------------------------------ repair number
  function syncUrl() {
    const path = REPAIR_RE.test(current) ? `/mobile/${encodeURIComponent(current)}` : "/mobile";
    if (location.pathname + location.search !== path) history.replaceState(null, "", path);
  }

  function setRepair(v) {
    current = (v || "").trim().toUpperCase();
    if (/^\d{4,7}$/.test(current)) { current = "R" + current; if (repair.value.trim().toUpperCase() !== current) repair.value = current; }
    const ok = REPAIR_RE.test(current);
    folderOk = false;
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
      const fres = await fetch(`/api/repairs/${encodeURIComponent(rn)}/folder`);
      const folder = fres.ok ? await fres.json() : { ok: false, reason: "folder check failed" };
      if (rn !== current) return;
      folderOk = !!folder.ok;
      updateButtons();
      if (!folder.ok) {
        status.innerHTML = `<b>${esc(rn)}</b><br><span class="err">⚠ ${esc(folder.reason)}</span>`;
        grid.innerHTML = ""; empty.hidden = true;
        return;
      }
      const res = await fetch(`/api/repairs/${encodeURIComponent(rn)}/photos`);
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const items = await res.json();
      if (rn !== current) return;
      status.innerHTML = `<b>${esc(rn)}</b> · ${items.length} photo${items.length === 1 ? "" : "s"} in the folder` +
        `<br><span class="muted">${esc(folder.location)}</span>`;
      grid.innerHTML = "";
      empty.hidden = items.length > 0;
      for (const it of items) {
        const fig = document.createElement("figure");
        const url = `/repairs/${encodeURIComponent(rn)}/photos/${encodeURIComponent(it.name)}`;
        fig.innerHTML = `<img src="${url}?thumb=1" alt="" loading="lazy">` +
          (it.in_latest ? `<span class="used">on report</span>` : "") +
          `<button class="rm" title="Remove from folder">✕</button>` +
          `<figcaption>${esc(it.name)} · ${kb(it.size)}</figcaption>`;
        fig.querySelector("img").addEventListener("click", () => window.open(url, "_blank"));
        fig.querySelector(".rm").addEventListener("click", async () => {
          if (!confirm(`Remove ${it.name} from the Photos folder? It is moved to .removed, not deleted.` + (it.in_latest ? " The saved report keeps its own copy." : ""))) return;
          const r = await fetch(`/api/repairs/${encodeURIComponent(rn)}/photos/${encodeURIComponent(it.name)}`, { method: "DELETE" });
          if (!r.ok) toast("Remove failed", true); else loadLibrary();
        });
        grid.appendChild(fig);
      }
    } catch (err) {
      status.textContent = `Unable to load photos: ${err.message}`;
    }
  }

  // ------------------------------------------------------------ shrink on the phone
  async function shrink(file) {
    // Draw onto a canvas at <= MAX_EDGE and re-encode as JPEG. Safari decodes
    // HEIC natively so this also converts iPhone photos. Falls back to the
    // original bytes if the browser cannot decode it; the server handles those.
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
      const scale = Math.min(1, MAX_EDGE / Math.max(bmp.width, bmp.height));
      if (scale === 1 && file.size < 1.5 * 1048576 && /jpe?g$/i.test(file.type)) { bmp.close(); return file; }
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(bmp.width * scale); canvas.height = Math.round(bmp.height * scale);
      canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
      bmp.close();
      const blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.85));
      if (!blob) return file;
      return new File([blob], (file.name || "photo").replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
    } catch (_) {
      return file;
    }
  }

  // ------------------------------------------------------------ upload queue with retry
  const queue = [];       // {file, repair, tries, state: 'pending'|'uploading'|'failed', error}
  let uploading = false;

  function renderQueue() {
    const pending = queue.filter((q) => q.state === "pending" || q.state === "uploading").length;
    const failed = queue.filter((q) => q.state === "failed");
    if (!pending && !failed.length) { queueBox.hidden = true; queueBox.innerHTML = ""; return; }
    queueBox.hidden = false;
    queueBox.innerHTML = (pending ? `<div>Uploading… ${pending} left</div>` : "") +
      (failed.length ? `<div class="err">${failed.length} failed after retries · <button type="button" class="link-btn" id="retry-all">Retry</button></div>` : "");
    const rb = $("#retry-all");
    if (rb) rb.addEventListener("click", () => { for (const q of failed) { q.state = "pending"; q.tries = 0; } pump(); });
  }

  function enqueue(files) {
    if (!files.length || !REPAIR_RE.test(current)) return;
    if (!signedIn && !tech.value) { toast("Pick your name first", true); tech.focus(); return; }
    for (const f of files) queue.push({ file: f, repair: current, who: signedIn ? "" : tech.value, tries: 0, state: "pending" });
    renderQueue();
    pump();
  }

  async function pump() {
    if (uploading) return;
    const next = queue.find((q) => q.state === "pending");
    if (!next) { renderQueue(); return; }
    uploading = true; updateButtons();
    next.state = "uploading"; renderQueue();
    try {
      const small = await shrink(next.file);
      await uploadOne(next, small);
      queue.splice(queue.indexOf(next), 1);
      if (navigator.vibrate) navigator.vibrate(30);
      if (next.repair === current) loadLibrary();
    } catch (err) {
      next.tries += 1;
      next.error = err.message;
      if (err.permanent || next.tries >= 3) {
        next.state = "failed";
        toast(`${next.file.name}: ${err.message}`, true);
      } else {
        next.state = "pending";
        await new Promise((r) => setTimeout(r, [2000, 5000, 10000][next.tries - 1] || 10000));
      }
    } finally {
      uploading = false; updateButtons(); renderQueue();
      pump();
    }
  }

  function uploadOne(item, file) {
    return new Promise((resolve, reject) => {
      const fd = new FormData();
      fd.append("repair_no", item.repair);
      fd.append("uploaded_by", item.who);
      fd.append("files", file, file.name || "photo.jpg");
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/mobile/photos");
      xhr.timeout = 120000;
      progress.hidden = false; bar.style.width = "0%";
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.style.width = `${Math.round(e.loaded / e.total * 100)}%`; };
      xhr.onload = () => {
        progress.hidden = true;
        if (xhr.status >= 200 && xhr.status < 300) { resolve(); return; }
        let msg = xhr.statusText;
        try { const d = JSON.parse(xhr.responseText).detail; msg = typeof d === "string" ? d : JSON.stringify(d); } catch (_) { /* ignore */ }
        const err = new Error(msg);
        err.permanent = xhr.status >= 400 && xhr.status < 500 && xhr.status !== 408 && xhr.status !== 429;  // bad request: retrying won't help
        reject(err);
      };
      xhr.onerror = () => { progress.hidden = true; reject(new Error("network error")); };
      xhr.ontimeout = () => { progress.hidden = true; reject(new Error("timed out")); };
      xhr.send(fd);
    });
  }

  camBtn.addEventListener("click", () => cam.click());
  galBtn.addEventListener("click", () => gal.click());
  cam.addEventListener("change", (e) => { enqueue(Array.from(e.target.files)); e.target.value = ""; });
  gal.addEventListener("change", (e) => { enqueue(Array.from(e.target.files)); e.target.value = ""; });
  window.addEventListener("beforeunload", (e) => {
    if (queue.some((q) => q.state !== "failed")) { e.preventDefault(); e.returnValue = ""; }
  });

  repair.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => setRepair(repair.value), 350); });
  repair.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); repair.blur(); setRepair(repair.value); } });

  async function loadRecent() {
    try {
      const list = await (await fetch("/api/repairs/recent?limit=12")).json();
      const box = $("#recent-list"); box.innerHTML = "";
      for (const r of list) {
        const b = document.createElement("button");
        b.innerHTML = `<b>${esc(r.repair_no)}</b>`;
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
    if (tech.value || signedIn) repair.focus();
  }
  loadRecent();
  setInterval(() => { if (REPAIR_RE.test(current) && !uploading) loadLibrary(); }, 30000);
})();

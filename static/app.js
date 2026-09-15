/* IFP Repair Evaluation - web front end.
 * Talks to the FastAPI backend in app/main.py. No build step, no framework.
 */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const FIELDS = [
    "date", "repair_no", "customer", "customer_contact", "customer_email",
    "customer_po", "material", "model", "serial", "technician",
    "customer_request", "findings",
  ];

  const state = {
    // Evaluation loaded from Forge (null = brand-new, unsaved)
    repairNo: null,
    revisionNo: null,
    currentRevisionNo: null,
    savedAt: null,
    savedBy: null,
    photos: [],
    dirty: false,
    cards: [],
    pdfUrl: null,
    pdfName: "RepairEvaluation.pdf",
    // Prophet 21 link state
    p21Available: false,
    customerId: null,
    contactId: null,
    contacts: [],
    emailOverride: false,
  };

  let cfg = {
    technicians: [],
    symbols: [
      { label: "Arrow ↑", value: "arrow_up" },
      { label: "Arrow →", value: "arrow_right" },
      { label: "Arrow ↓", value: "arrow_down" },
      { label: "Arrow ←", value: "arrow_left" },
      { label: "Circle", value: "circle" },
      { label: "Square", value: "square" },
      { label: "Rectangle", value: "rectangle" },
      { label: "X", value: "x" },
      { label: "Check Mark", value: "check" },
    ],
  };

  // ------------------------------------------------------------------ utils
  function todayIso() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  function setStatus(msg) {
    $("#status").textContent = msg || "";
  }

  let toastTimer = null;
  function toast(msg, isError = false) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.toggle("error", isError);
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 3000);
  }

  function markDirty() {
    state.dirty = true;
    $("#dirty").hidden = false;
  }

  function clearDirty() {
    state.dirty = false;
    $("#dirty").hidden = true;
  }

  async function api(url, opts = {}) {
    const res = await fetch(url, opts);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) { /* ignore */ }
      throw new Error(detail);
    }
    return res;
  }

  function fillSymbolSelect(select) {
    select.innerHTML = "";
    for (const s of cfg.symbols) {
      const o = document.createElement("option");
      o.value = s.value;
      o.textContent = s.label;
      select.appendChild(o);
    }
  }

  const DEFAULT_COLOR = "#ff0000";
  function fillColorSelect(select, value = DEFAULT_COLOR) {
    select.innerHTML = "";
    for (const c of cfg.colors) {
      const o = document.createElement("option");
      o.value = c.value;
      o.textContent = "■ " + c.label;
      o.style.color = c.value;
      select.appendChild(o);
    }
    select.value = value;
    paintColorSelect(select);
    select.addEventListener("change", () => paintColorSelect(select));
  }
  function paintColorSelect(select) {
    select.style.color = select.value;
    select.style.background = (select.value === "#000000") ? "#555" : "";
  }

  // ---------------------------------------------------------- symbol drawing
  // Must stay in step with _draw_pdf_annotations() in app/pdf_builder.py so the
  // on-screen preview and the PDF agree on geometry.
  function drawSymbol(ctx, symbol, x, y, base, symbolSize = 100, selected = false, color = DEFAULT_COLOR) {
    const size = Math.max(18, Math.min(70, base * 0.10)) * Math.max(0.25, symbolSize / 100);
    const lineWidth = Math.max(2, size * 0.065);
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    tracePath(ctx, symbol, x, y, size);
    if (selected) {
      // Selection halo: a wide translucent stroke under the symbol, in a
      // contrasting tone so it reads on any colour.
      ctx.strokeStyle = (color === "#ffffff" || color === "#ffd400") ? "rgba(0,0,0,0.6)" : "rgba(255,255,255,0.8)";
      ctx.lineWidth = lineWidth + 6;
      ctx.stroke();
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.stroke();
    ctx.restore();
  }

  function tracePath(ctx, symbol, x, y, size) {

    if (symbol === "circle") {
      ctx.arc(x, y, size / 2, 0, Math.PI * 2);
    } else if (symbol === "square") {
      ctx.rect(x - size / 2, y - size / 2, size, size);
    } else if (symbol === "rectangle") {
      const w = size * 1.55, h = size * 0.85;
      ctx.rect(x - w / 2, y - h / 2, w, h);
    } else if (symbol === "x") {
      const s = size * 0.55;
      ctx.moveTo(x - s, y - s); ctx.lineTo(x + s, y + s);
      ctx.moveTo(x + s, y - s); ctx.lineTo(x - s, y + s);
    } else if (symbol === "check") {
      const s = size * 0.55;
      ctx.moveTo(x - s, y);
      ctx.lineTo(x - s * 0.2, y + s * 0.7);
      ctx.lineTo(x + s, y - s * 0.75);
    } else {
      const length = size * 1.35, head = size * 0.32;
      let sx, sy, ex, ey;
      if (symbol === "arrow_up") { sx = x; sy = y + length / 2; ex = x; ey = y - length / 2; }
      else if (symbol === "arrow_right") { sx = x - length / 2; sy = y; ex = x + length / 2; ey = y; }
      else if (symbol === "arrow_down") { sx = x; sy = y - length / 2; ex = x; ey = y + length / 2; }
      else { sx = x + length / 2; sy = y; ex = x - length / 2; ey = y; }
      ctx.moveTo(sx, sy); ctx.lineTo(ex, ey);
      const angle = Math.atan2(ey - sy, ex - sx);
      ctx.moveTo(ex, ey);
      ctx.lineTo(ex - head * Math.cos(angle - Math.PI / 6), ey - head * Math.sin(angle - Math.PI / 6));
      ctx.moveTo(ex, ey);
      ctx.lineTo(ex - head * Math.cos(angle + Math.PI / 6), ey - head * Math.sin(angle + Math.PI / 6));
    }
  }

  // ------------------------------------------------------------ photo URLs
  // A photo ref is "live:<file name>" (a file in the repair's Photos folder) or
  // "archive:<sha256>" (a frozen snapshot behind a saved revision).
  function photoRepairNo() {
    return normalizeRepairNo($("#f-repair_no").value) || state.repairNo || "";
  }
  function photoUrl(ref, thumb = false, repairNo = photoRepairNo()) {
    const i = ref.indexOf(":");
    const kind = ref.slice(0, i), val = ref.slice(i + 1);
    const base = kind === "archive"
      ? `/repairs/${encodeURIComponent(repairNo)}/archive/${val}`
      : `/repairs/${encodeURIComponent(repairNo)}/photos/${encodeURIComponent(val)}`;
    return thumb ? `${base}?thumb=1` : base;
  }

  // ------------------------------------------------------------ PhotoCanvas
  const imageCache = new Map();
  function loadImage(url) {
    if (imageCache.has(url)) return imageCache.get(url);
    const p = new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => { imageCache.delete(url); reject(new Error("Unable to load image")); };
      img.src = url;
    });
    imageCache.set(url, p);
    return p;
  }

  class PhotoCanvas {
    constructor(canvas, photo, onChange) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.photo = photo;
      this.onChange = onChange;
      this.symbol = "arrow_up";
      this.symbolSize = 250;
      this.color = DEFAULT_COLOR;
      this.selected = null;
      this.dragging = false;
      this.img = null;
      this.failed = false;
      this.rect = null;

      photo.annotations = photo.annotations || [];

      loadImage(photoUrl(photo.ref))
        .then((img) => { this.img = img; this.draw(); })
        .catch(() => { this.failed = true; this.draw(); });

      canvas.addEventListener("pointerdown", (e) => this.onDown(e));
      canvas.addEventListener("pointermove", (e) => this.onMove(e));
      canvas.addEventListener("pointerup", (e) => this.onUp(e));
      canvas.addEventListener("pointercancel", (e) => this.onUp(e));
      canvas.addEventListener("keydown", (e) => this.onKey(e));

      this.ro = new ResizeObserver(() => this.draw());
      this.ro.observe(canvas);
    }

    destroy() {
      this.ro.disconnect();
    }

    pos(e) {
      const r = this.canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }

    inRect(p) {
      const r = this.rect;
      return r && p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h;
    }

    onDown(e) {
      if (e.button !== 0 || !this.img || !this.rect) return;
      this.canvas.focus();
      const p = this.pos(e);
      if (!this.inRect(p)) return;
      const r = this.rect;
      const base = Math.min(r.w, r.h);

      // Select an existing symbol near the click first.
      let nearest = null, nearestDist = Infinity;
      this.photo.annotations.forEach((a, i) => {
        const ax = r.x + (a.x ?? 0.5) * r.w;
        const ay = r.y + (a.y ?? 0.5) * r.h;
        const scale = Math.max(0.35, (a.size ?? 100) / 100);
        const hit = Math.max(16, base * 0.065 * scale);
        const d = Math.hypot(p.x - ax, p.y - ay);
        if (d <= hit && d < nearestDist) { nearest = i; nearestDist = d; }
      });

      if (nearest !== null) {
        this.selected = nearest;
        this.dragging = true;
        this.canvas.setPointerCapture(e.pointerId);
        this.onChange();
        this.draw();
        return;
      }

      // Otherwise place a new symbol at the click location.
      this.photo.annotations.push({
        symbol: this.symbol,
        x: Math.max(0, Math.min(1, (p.x - r.x) / Math.max(1, r.w))),
        y: Math.max(0, Math.min(1, (p.y - r.y) / Math.max(1, r.h))),
        size: this.symbolSize,
        color: this.color,
      });
      this.selected = this.photo.annotations.length - 1;
      this.onChange();
      this.draw();
    }

    onMove(e) {
      if (!this.dragging || this.selected === null || !this.rect) return;
      const a = this.photo.annotations[this.selected];
      if (!a) return;
      const p = this.pos(e);
      const r = this.rect;
      a.x = Math.max(0, Math.min(1, (p.x - r.x) / Math.max(1, r.w)));
      a.y = Math.max(0, Math.min(1, (p.y - r.y) / Math.max(1, r.h)));
      this.onChange();
      this.draw();
    }

    onUp(e) {
      if (this.dragging) {
        this.dragging = false;
        try { this.canvas.releasePointerCapture(e.pointerId); } catch (_) { /* ignore */ }
      }
    }

    onKey(e) {
      if (e.key === "Delete" || e.key === "Backspace") {
        if (this.selected !== null && this.photo.annotations[this.selected]) {
          this.photo.annotations.splice(this.selected, 1);
        }
        this.selected = null;
        this.onChange();
        this.draw();
        e.preventDefault();
      } else if (e.key === "Escape") {
        this.selected = null;
        this.draw();
        e.preventDefault();
        e.stopPropagation();
      }
    }

    draw() {
      const canvas = this.canvas, ctx = this.ctx;
      const cw = canvas.clientWidth, ch = canvas.clientHeight;
      if (!cw || !ch) return;
      const dpr = window.devicePixelRatio || 1;
      if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) {
        canvas.width = Math.round(cw * dpr);
        canvas.height = Math.round(ch * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#111";
      ctx.fillRect(0, 0, cw, ch);

      if (!this.img) {
        ctx.fillStyle = "#fff";
        ctx.font = "14px Segoe UI, Arial";
        ctx.textAlign = "center";
        ctx.fillText(this.failed ? "Unable to load image" : "Loading image…", cw / 2, ch / 2);
        this.rect = null;
        return;
      }

      const rot = ((this.photo.rotation || 0) % 360 + 360) % 360;
      const swap = rot === 90 || rot === 270;
      const iw = swap ? this.img.naturalHeight : this.img.naturalWidth;
      const ih = swap ? this.img.naturalWidth : this.img.naturalHeight;
      const scale = Math.min(cw / iw, ch / ih);
      const sw = iw * scale, sh = ih * scale;
      const x = (cw - sw) / 2, y = (ch - sh) / 2;
      this.rect = { x, y, w: sw, h: sh };

      ctx.save();
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.translate(x + sw / 2, y + sh / 2);
      ctx.rotate(rot * Math.PI / 180);
      if (swap) ctx.drawImage(this.img, -sh / 2, -sw / 2, sh, sw);
      else ctx.drawImage(this.img, -sw / 2, -sh / 2, sw, sh);
      ctx.restore();

      const base = Math.min(sw, sh);
      this.photo.annotations.forEach((a, i) => {
        drawSymbol(ctx, a.symbol, x + (a.x ?? 0.5) * sw, y + (a.y ?? 0.5) * sh, base, a.size ?? 100, i === this.selected, a.color || DEFAULT_COLOR);
      });
    }
  }

  // -------------------------------------------------------------- PhotoCard
  class PhotoCard {
    constructor(index, photo) {
      this.index = index;
      this.photo = photo;
      const tpl = $("#photo-card-tpl").content.cloneNode(true);
      this.el = tpl.firstElementChild;

      this.titleEl = $(".photo-title", this.el);
      this.titleEl.textContent = `PHOTO ${index + 1}`;
      $(".file-name", this.el).textContent = photo.name || photo.ref;

      this.symbolSelect = $(".symbol-select", this.el);
      fillSymbolSelect(this.symbolSelect);
      this.sizeInput = $(".size-input", this.el);
      this.colorSelect = $(".color-select", this.el);
      fillColorSelect(this.colorSelect);

      this.canvas = new PhotoCanvas($(".photo-canvas", this.el), photo, () => this.markupChanged());

      this.symbolSelect.addEventListener("change", () => { this.canvas.symbol = this.symbolSelect.value; });
      this.sizeInput.addEventListener("input", () => this.sizeChanged());
      this.colorSelect.addEventListener("change", () => this.colorChanged());

      const desc = $(".description", this.el);
      desc.value = photo.description || "";
      desc.addEventListener("input", () => { photo.description = desc.value; markDirty(); });

      $(".clear-markups", this.el).addEventListener("click", () => {
        photo.annotations = [];
        this.canvas.photo.annotations = photo.annotations;
        this.canvas.selected = null;
        this.markupChanged();
      });
      $(".move-up", this.el).addEventListener("click", () => movePhoto(index, -1));
      $(".move-down", this.el).addEventListener("click", () => movePhoto(index, 1));
      $(".remove", this.el).addEventListener("click", () => removePhoto(index));
      $(".rotate-left", this.el).addEventListener("click", () => this.rotate(-90));
      $(".rotate-right", this.el).addEventListener("click", () => this.rotate(90));
      $(".reset-rotation", this.el).addEventListener("click", () => { photo.rotation = 0; this.refresh(); markDirty(); });
      $(".open-zoom", this.el).addEventListener("click", () => openZoom(this));
    }

    rotate(delta) {
      this.photo.rotation = (((this.photo.rotation || 0) + delta) % 360 + 360) % 360;
      this.refresh();
      markDirty();
    }

    sizeChanged() {
      const v = clampSize(this.sizeInput.value);
      this.canvas.symbolSize = v;
      const a = this.photo.annotations[this.canvas.selected];
      if (a) a.size = v;
      this.markupChanged();
    }

    colorChanged() {
      const v = this.colorSelect.value;
      this.canvas.color = v;
      const a = this.photo.annotations[this.canvas.selected];
      if (a) a.color = v;
      this.markupChanged();
    }

    markupChanged() {
      const a = this.photo.annotations[this.canvas.selected];
      if (a && Number(this.sizeInput.value) !== a.size) this.sizeInput.value = a.size;
      if (a && this.colorSelect.value !== (a.color || DEFAULT_COLOR)) { this.colorSelect.value = a.color || DEFAULT_COLOR; paintColorSelect(this.colorSelect); }
      markDirty();
      this.canvas.draw();
    }

    refresh() {
      this.canvas.draw();
    }

    destroy() {
      this.canvas.destroy();
    }
  }

  function clampSize(v) {
    v = Math.round(Number(v) || 100);
    return Math.max(25, Math.min(300, v));
  }

  // ------------------------------------------------------------- photo list
  function renderPhotos() {
    for (const c of state.cards) c.destroy();
    state.cards = [];
    const area = $("#photo-area");
    area.innerHTML = "";
    state.photos.forEach((photo, i) => {
      const card = new PhotoCard(i, photo);
      state.cards.push(card);
      area.appendChild(card.el);
    });
    const n = state.photos.length;
    $("#photo-count").textContent = `${n} photo${n === 1 ? "" : "s"}`;
  }

  function movePhoto(index, dir) {
    const j = index + dir;
    if (j < 0 || j >= state.photos.length) return;
    [state.photos[index], state.photos[j]] = [state.photos[j], state.photos[index]];
    renderPhotos();
    markDirty();
  }

  function removePhoto(index) {
    if (!confirm(`Remove PHOTO ${index + 1} from this evaluation?`)) return;
    state.photos.splice(index, 1);
    renderPhotos();
    markDirty();
  }

  async function uploadPhotos(files) {
    if (!files.length) return;
    if (!$("#f-repair_no").value.trim()) {
      toast("Enter the Repair # first — photos are filed in its drawing folder", true);
      $("#f-repair_no").focus();
      return;
    }
    const fd = new FormData();
    const rn = $("#f-repair_no").value.trim();
    if (rn) fd.append("repair_no", rn);   // also files the photos in this repair's library
    for (const f of files) fd.append("files", f, f.name);
    setStatus(`Uploading ${files.length} photo${files.length === 1 ? "" : "s"}…`);
    try {
      const res = await api("/api/photos", { method: "POST", body: fd });
      const uploaded = await res.json();
      for (const u of uploaded) {
        state.photos.push({ ref: u.ref, name: u.name, description: "", rotation: 0, annotations: [] });
      }
      renderPhotos();
      markDirty();
      setStatus(`Added ${uploaded.length} photo${uploaded.length === 1 ? "" : "s"}`);
      refreshLibraryCount();
    } catch (err) {
      toast(`Upload failed: ${err.message}`, true);
      setStatus("");
    }
  }

  // ------------------------------------------------------------ form <-> data
  function collectData() {
    const data = {};
    for (const f of FIELDS) data[f] = $(`#f-${f}`).value;
    for (const k of ["repair_no", "technician", "customer", "customer_contact", "customer_email", "model", "serial", "customer_po", "material"]) {
      data[k] = (data[k] || "").trim();
    }
    data.repair_no = normalizeRepairNo(data.repair_no);
    data.customer_id = state.customerId;
    data.contact_id = state.contactId;
    data.email_override = state.emailOverride;
    data.base_revision_no = state.currentRevisionNo || 0;
    data.force = false;
    data.photos = state.photos.map((p) => ({
      ref: p.ref,
      name: p.name || "",
      description: p.description || "",
      rotation: p.rotation || 0,
      annotations: (p.annotations || []).map((a) => ({
        symbol: a.symbol || "arrow_up",
        x: a.x ?? 0.5,
        y: a.y ?? 0.5,
        size: a.size ?? 100,
        color: a.color || DEFAULT_COLOR,
      })),
    }));
    return data;
  }

  function loadData(data) {
    state.repairNo = data.revision_no ? (data.repair_no || null) : null;
    state.revisionNo = data.revision_no || null;
    state.currentRevisionNo = data.current_revision_no || null;
    state.savedAt = data.saved_at || null;
    state.savedBy = data.saved_by || null;
    for (const f of FIELDS) {
      const el = $(`#f-${f}`);
      if (f === "technician") {
        const name = data.technician || "";
        el.value = cfg.technicians.includes(name) ? name : (cfg.technicians[0] || "");
      } else {
        el.value = data[f] || "";
      }
    }
    if (!$("#f-date").value) $("#f-date").value = todayIso();
    restoreP21Link(data);
    state.photos = (data.photos || []).map((p) => ({
      ref: p.ref,
      name: p.name || "",
      description: p.description || "",
      rotation: p.rotation || 0,
      annotations: (p.annotations || []).map((a) => ({
        symbol: a.symbol || "arrow_up", x: a.x ?? 0.5, y: a.y ?? 0.5, size: a.size ?? 100, color: a.color || DEFAULT_COLOR,
      })),
    }));
    renderPhotos();
    clearDirty();
    updateRevisionBanner();
    refreshLibraryCount();
    syncUrl();
  }

  function newReport(force = false) {
    if (!force && state.dirty && !confirm("This repair evaluation has unsaved changes. Start a new one anyway?")) return;
    loadData({ date: todayIso(), technician: cfg.technicians[0] || "" });
    setStatus("New evaluation");
  }

  async function saveReport() {
    const data = collectData();
    if (!data.repair_no) {
      toast("Enter a Repair # before saving", true);
      $("#f-repair_no").focus();
      return;
    }
    if (state.repairNo && state.repairNo !== data.repair_no) {
      const ok = await confirmDialog(
        "Save under a different repair number?",
        `This was opened as ${state.repairNo}. Saving will store it as ${data.repair_no} instead ` +
        `(a new revision of ${data.repair_no} if it already exists). ${state.repairNo} is left unchanged.`,
      );
      if (!ok) return;
    }
    setStatus("Saving…");
    try {
      let res = await fetch("/api/evaluations", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
      });
      if (res.status === 409) {
        const detail = (await res.json()).detail;
        if (detail && detail.stale) {
          const ok = await confirmDialog(
            "Someone else saved this evaluation",
            `${detail.message} Saving now creates revision ${detail.current_revision_no + 1} from what is on your screen; their revision ${detail.current_revision_no} stays in the history. Save anyway?`,
          );
          if (!ok) { setStatus("Save cancelled — use History to see the newer revision"); return; }
          data.force = true;
          res = await fetch("/api/evaluations", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
          });
        } else {
          throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
        }
      }
      if (!res.ok) {
        let detail = res.statusText;
        try { const j = await res.json(); detail = typeof j.detail === "string" ? j.detail : (j.detail && j.detail.message) || JSON.stringify(j.detail); } catch (_) { /* ignore */ }
        throw new Error(detail);
      }
      const saved = await res.json();
      loadData(saved);   // photos now reference frozen snapshots; banner and URL follow
      setStatus(`Saved ${saved.repair_no} revision ${saved.revision_no} at ${new Date().toLocaleTimeString()}`);
      toast(`Saved ${saved.repair_no} as revision ${saved.revision_no}`);
    } catch (err) {
      toast(`Save failed: ${err.message}`, true);
      setStatus("");
    }
  }

  // ------------------------------------------------------------------ modals
  function openModal(id) {
    const m = $(id);
    m.hidden = false;
    return m;
  }
  function closeModal(m) {
    m.hidden = true;
    if (m.id === "modal-zoom") closeZoom();
    if (m.id === "modal-pdf") revokePdf();
  }
  function topModal() {
    return $$(".modal").filter((m) => !m.hidden).pop();
  }
  $$(".modal").forEach((m) => {
    m.addEventListener("click", (e) => { if (e.target === m) closeModal(m); });
    $$("[data-close]", m).forEach((b) => b.addEventListener("click", () => closeModal(m)));
  });

  // -------------------------------------------------------------- open list
  function fmtWhen(iso) {
    return iso ? new Date(iso).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "";
  }

  async function openReportDialog() {
    const m = openModal("#modal-open");
    const tbody = $("#report-list");
    tbody.innerHTML = "<tr><td colspan='8' class='muted'>Loading…</td></tr>";
    try {
      const showDeleted = $("#show-deleted").checked;
      const list = (await (await api(`/api/evaluations?include_deleted=${showDeleted ? 1 : 0}`)).json())
        .filter((r) => showDeleted || !r.deleted_at);
      tbody.innerHTML = "";
      $("#report-empty").hidden = list.length > 0;
      for (const r of list) {
        const tr = document.createElement("tr");
        const deleted = !!r.deleted_at;
        if (deleted) tr.classList.add("deleted");
        tr.innerHTML = `
          <td><b>${esc(r.repair_no)}</b>${deleted ? " <span class='pill'>deleted</span>" : ""}</td>
          <td>${esc(r.customer)}</td>
          <td>${esc(r.date)}</td>
          <td>${esc(r.technician)}</td>
          <td class="num">${r.photo_count}</td>
          <td class="num">${r.revision_count}</td>
          <td class="muted">${deleted ? "deleted " + esc(fmtWhen(r.deleted_at)) + (r.deleted_by ? " · " + esc(r.deleted_by) : "")
                                        : esc(fmtWhen(r.updated_at)) + (r.saved_by ? " · " + esc(r.saved_by) : "")}</td>
          <td>${deleted ? `<button class="btn small" title="Bring it back">Restore</button>`
                        : `<button class="btn small danger" title="Hide this evaluation (all revisions are kept and it can be restored)">Delete</button>`}</td>`;
        tr.addEventListener("click", () => loadReport(r.repair_no, null, m));
        $("button", tr).addEventListener("click", async (e) => {
          e.stopPropagation();
          try {
            if (deleted) {
              await api(`/api/evaluations/${encodeURIComponent(r.repair_no)}/restore`, { method: "POST" });
              toast(`${r.repair_no} restored`);
            } else {
              const ok = await confirmDialog(
                `Delete ${r.repair_no}?`,
                `${r.repair_no} disappears from the list and lookups. All ${r.revision_count} revision${r.revision_count === 1 ? "" : "s"} are kept and it can be restored from "Show deleted".`,
              );
              if (!ok) return;
              await api(`/api/evaluations/${encodeURIComponent(r.repair_no)}`, { method: "DELETE" });
              if (state.repairNo === r.repair_no) { state.repairNo = null; state.revisionNo = null; state.currentRevisionNo = null; updateRevisionBanner(); }
            }
            openReportDialog();
          } catch (err) { toast(`${deleted ? "Restore" : "Delete"} failed: ${err.message}`, true); }
        });
        tbody.appendChild(tr);
      }
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan='8' class='muted'>Unable to load: ${esc(err.message)}</td></tr>`;
    }
  }

  /** Load an evaluation (latest revision, or a specific one) into the form. */
  /** True when nothing has been entered beyond the Repair # lookup itself. */
  function formIsBlank() {
    if (state.repairNo || state.photos.length) return false;
    return ["customer", "customer_contact", "customer_email", "customer_po", "material", "model", "serial", "customer_request", "findings"]
      .every((f) => !$(`#f-${f}`).value.trim());
  }

  // ------------------------------------------------------------ URL sync
  // /r/R123456      -> latest revision      /r/R123456/v2 -> revision 2
  // The address bar follows whatever is loaded, so a link can be copied at any time.
  function syncUrl() {
    let path = "/";
    if (state.repairNo) {
      path = `/r/${encodeURIComponent(state.repairNo)}`;
      if (state.revisionNo && state.currentRevisionNo && state.revisionNo < state.currentRevisionNo) path += `/v${state.revisionNo}`;
    }
    if (location.pathname !== path) history.replaceState(null, "", path);
  }

  function parseUrl() {
    const m = location.pathname.match(/^\/r\/([^/]+)(?:\/(latest|v(\d+)))?\/?$/i);
    if (!m) return null;
    return { repairNo: decodeURIComponent(m[1]), revision: m[3] ? Number(m[3]) : null };
  }

  /** Load an evaluation (latest revision, or a specific one) into the form. */
  async function loadReport(repairNo, revision, modal) {
    if (state.dirty && !formIsBlank() &&
        !(await confirmDialog("Discard unsaved changes?", "This repair evaluation has unsaved changes. Open another anyway?"))) return;
    try {
      const url = `/api/evaluations/${encodeURIComponent(repairNo)}/` + (revision ? `v${revision}` : "latest");
      const data = await (await api(url)).json();
      loadData(data);
      if (modal) closeModal(modal);
      hideRepairSuggestions();
      setStatus(`Opened ${data.repair_no} revision ${data.revision_no}`);
    } catch (err) {
      toast(`Unable to open evaluation: ${err.message}`, true);
    }
  }

  // --------------------------------------------------- repair # type-ahead
  const repairInput = $("#f-repair_no");
  const repairList = $("#repair-suggestions");
  const repairHint = $("#repair-hint");
  let repairTimer = null;
  let repairItems = [];
  let repairActive = -1;
  let repairSeq = 0;

  function hideRepairSuggestions() {
    repairList.hidden = true;
    repairList.innerHTML = "";
    repairItems = [];
    repairActive = -1;
  }

  function setRepairActive(i) {
    repairActive = i;
    $$("li", repairList).forEach((li, k) => li.classList.toggle("active", k === i));
  }

  async function searchRepairs() {
    const q = repairInput.value.trim();
    if (q.length < 1) { hideRepairSuggestions(); repairHint.textContent = ""; return; }
    const seq = ++repairSeq;
    try {
      const res = await (await api(`/api/evaluations?q=${encodeURIComponent(q)}&limit=15`)).json();
      if (seq !== repairSeq || document.activeElement !== repairInput) return;
      repairItems = res;
      repairList.innerHTML = "";
      for (const r of res) {
        const li = document.createElement("li");
        li.innerHTML = `<span><b>${esc(r.repair_no)}</b>${r.customer ? " - " + esc(r.customer) : ""}</span>` +
          `<span class="sub"><span class="rev">rev ${r.revision_count}</span> · ${esc(fmtWhen(r.updated_at))}</span>`;
        li.addEventListener("mousedown", (e) => { e.preventDefault(); loadReport(r.repair_no, null, null); });
        repairList.appendChild(li);
      }
      repairActive = -1;
      repairList.hidden = res.length === 0;
      const exact = res.find((r) => r.repair_no.toLowerCase() === q.toLowerCase());
      if (exact && exact.repair_no !== state.repairNo) {
        repairHint.textContent = `· ${exact.repair_no} exists (${exact.revision_count} rev) — pick it to load`;
      } else if (!exact && q !== state.repairNo) {
        repairHint.textContent = "· new evaluation";
      } else {
        repairHint.textContent = "";
      }
    } catch (err) {
      if (seq === repairSeq) repairHint.textContent = `· lookup failed: ${err.message}`;
    }
    updateRevisionBanner();
  }

  repairInput.addEventListener("input", () => {
    clearTimeout(repairTimer);
    repairTimer = setTimeout(searchRepairs, 200);
  });
  repairInput.addEventListener("focus", () => { if (repairInput.value.trim()) searchRepairs(); });
  repairInput.addEventListener("blur", () => setTimeout(hideRepairSuggestions, 150));
  repairInput.addEventListener("keydown", (e) => {
    if (repairList.hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setRepairActive(Math.min(repairItems.length - 1, repairActive + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setRepairActive(Math.max(0, repairActive - 1)); }
    else if (e.key === "Enter") { if (repairActive >= 0) { e.preventDefault(); loadReport(repairItems[repairActive].repair_no, null, null); } }
    else if (e.key === "Escape") { e.stopPropagation(); hideRepairSuggestions(); }
  });

  // ------------------------------------------------------ revision banner
  function updateRevisionBanner() {
    const banner = $("#revision-banner");
    const text = $("#revision-text");
    const typed = repairInput.value.trim();
    banner.classList.remove("warn", "new");
    $("#btn-history").hidden = !state.repairNo;

    if (!state.repairNo) {
      if (!typed) { banner.hidden = true; return; }
      banner.hidden = false;
      banner.classList.add("new");
      text.innerHTML = `<b>${esc(typed)}</b> — new evaluation. Saving creates revision 1.`;
      return;
    }
    banner.hidden = false;
    const who = state.savedBy ? ` by ${esc(state.savedBy)}` : "";
    if (typed && typed !== state.repairNo) {
      banner.classList.add("warn");
      text.innerHTML = `Opened as <b>${esc(state.repairNo)}</b> but Repair # now reads <b>${esc(typed)}</b>. Saving stores it under ${esc(typed)}.`;
    } else if (state.revisionNo < state.currentRevisionNo) {
      banner.classList.add("warn");
      text.innerHTML = `<b>${esc(state.repairNo)}</b> — viewing revision <b>${state.revisionNo}</b> of ${state.currentRevisionNo}, saved ${esc(fmtWhen(state.savedAt))}${who}. ` +
        `Saving creates revision ${state.currentRevisionNo + 1} from this version.`;
    } else {
      text.innerHTML = `<b>${esc(state.repairNo)}</b> — revision <b>${state.revisionNo}</b> (latest), saved ${esc(fmtWhen(state.savedAt))}${who}. ` +
        `Saving creates revision ${state.currentRevisionNo + 1}.`;
    }
  }

  async function openHistory() {
    if (!state.repairNo) return;
    const m = openModal("#modal-history");
    $("#history-title").textContent = `Revision History — ${state.repairNo}`;
    const tbody = $("#history-list");
    tbody.innerHTML = "<tr><td colspan='7' class='muted'>Loading…</td></tr>";
    try {
      const revs = await (await api(`/api/evaluations/${encodeURIComponent(state.repairNo)}/revisions`)).json();
      tbody.innerHTML = "";
      for (const r of revs) {
        const tr = document.createElement("tr");
        if (r.revision_no === state.revisionNo) tr.classList.add("current");
        tr.innerHTML = `
          <td class="num"><b>${r.revision_no}</b>${r.revision_no === state.currentRevisionNo ? " <span class='muted'>(latest)</span>" : ""}</td>
          <td>${esc(fmtWhen(r.saved_at))}</td>
          <td>${esc(r.saved_by || "")}</td>
          <td>${esc(r.technician)}</td>
          <td>${esc(r.customer)}</td>
          <td class="num">${r.photo_count}</td>
          <td><button class="btn small">${r.revision_no === state.revisionNo ? "Reload" : "View"}</button></td>`;
        const open = () => loadReport(state.repairNo, r.revision_no, m);
        tr.addEventListener("click", open);
        $("button", tr).addEventListener("click", (e) => { e.stopPropagation(); open(); });
        tbody.appendChild(tr);
      }
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan='7' class='muted'>Unable to load history: ${esc(err.message)}</td></tr>`;
    }
  }
  $("#btn-history").addEventListener("click", openHistory);

  // --------------------------------------------------------- photo library
  let libraryItems = [];
  const librarySelected = new Set();

  function currentRepairNo() {
    return normalizeRepairNo($("#f-repair_no").value);
  }

  async function refreshLibraryCount() {
    const rn = currentRepairNo();
    const badge = $("#library-count");
    const hint = $("#folder-hint");
    $("#mobile-link").href = rn ? `/mobile/${encodeURIComponent(rn)}` : "/mobile";
    if (!rn) { badge.hidden = true; hint.textContent = ""; hint.className = "muted"; return; }
    api(`/api/repairs/${encodeURIComponent(rn)}/folder`).then((r) => r.json()).then((f) => {
      if (rn !== currentRepairNo()) return;
      hint.textContent = f.ok ? `Photos file to ${f.location}` : `⚠ ${f.reason}`;
      hint.className = f.ok ? "muted folder-ok" : "folder-bad";
      hint.title = hint.textContent;
    }).catch(() => { hint.textContent = ""; });
    try {
      const items = await (await api(`/api/repairs/${encodeURIComponent(rn)}/photos`)).json();
      const fresh = items.filter((i) => !onReportItem(i)).length;
      badge.textContent = fresh ? `${fresh} new` : String(items.length);
      badge.hidden = items.length === 0;
    } catch (_) {
      badge.hidden = true;
    }
  }

  /** Is this folder photo already on the report in the form? (same file, or same content as a frozen snapshot) */
  function onReportItem(it) {
    return state.photos.some((p) => p.ref === it.ref || (it.sha256 && p.ref === `archive:${it.sha256}`));
  }

  function renderLibrary() {
    const grid = $("#library-grid");
    grid.innerHTML = "";
    const rn = currentRepairNo();
    for (const it of libraryItems) {
      const used = onReportItem(it);
      const fig = document.createElement("figure");
      fig.classList.toggle("on-report", used);
      fig.classList.toggle("selected", librarySelected.has(it.ref));
      fig.innerHTML =
        `<img src="${photoUrl(it.ref, true, rn)}" alt="" loading="lazy">` +
        (used ? `<span class="flag">on report</span>` : (it.in_latest ? `<span class="flag">on saved report</span>` : "")) +
        `<span class="tick">✓</span>` +
        `<button class="rm" title="Remove from the Photos folder (moved to .removed)">✕</button>` +
        `<figcaption>${esc(it.name)} · ${esc(fmtWhen(it.modified))} · ${Math.round(it.size / 1024)} KB</figcaption>`;
      if (!used) {
        fig.addEventListener("click", (e) => {
          if (e.target.classList.contains("rm")) return;
          if (librarySelected.has(it.ref)) librarySelected.delete(it.ref); else librarySelected.add(it.ref);
          renderLibrary();
        });
      }
      $(".rm", fig).addEventListener("click", async (e) => {
        e.stopPropagation();
        const ok = await confirmDialog("Remove from the Photos folder?",
          `${it.name} is moved into the folder's .removed sub-folder, so it can be recovered. Saved revisions keep their own frozen copies.`);
        if (!ok) return;
        try {
          await api(`/api/repairs/${encodeURIComponent(rn)}/photos/${encodeURIComponent(it.name)}`, { method: "DELETE" });
          librarySelected.delete(it.ref);
          await loadLibrary();
        } catch (err) { toast(`Remove failed: ${err.message}`, true); }
      });
      grid.appendChild(fig);
    }
    $("#library-empty").hidden = libraryItems.length > 0;
    $("#library-selected").textContent = `${librarySelected.size} selected`;
    $("#library-add").disabled = librarySelected.size === 0;
  }

  async function loadLibrary() {
    const rn = currentRepairNo();
    $("#library-title").textContent = `Photo Library — ${rn}`;
    try {
      libraryItems = await (await api(`/api/repairs/${encodeURIComponent(rn)}/photos`)).json();
      $("#library-sub").textContent = `${libraryItems.length} photo${libraryItems.length === 1 ? "" : "s"} in the Photos folder · click to select, then add to the report`;
    } catch (err) {
      libraryItems = [];
      $("#library-sub").textContent = `Unable to load library: ${err.message}`;
    }
    for (const f of Array.from(librarySelected)) if (!libraryItems.some((i) => i.ref === f)) librarySelected.delete(f);
    renderLibrary();
    refreshLibraryCount();
  }

  async function openLibrary() {
    if (!currentRepairNo()) { toast("Enter a Repair # first — the library is per repair number", true); $("#f-repair_no").focus(); return; }
    librarySelected.clear();
    openModal("#modal-library");
    await loadLibrary();
  }

  function addSelectedFromLibrary() {
    let added = 0;
    for (const it of libraryItems) {
      if (!librarySelected.has(it.ref) || onReportItem(it)) continue;
      state.photos.push({ ref: it.ref, name: it.name, description: "", rotation: 0, annotations: [] });
      added++;
    }
    librarySelected.clear();
    if (added) { renderPhotos(); markDirty(); toast(`Added ${added} photo${added === 1 ? "" : "s"} to the report`); }
    closeModal($("#modal-library"));
    refreshLibraryCount();
  }

  $("#btn-library").addEventListener("click", openLibrary);
  $("#library-refresh").addEventListener("click", loadLibrary);
  $("#library-add").addEventListener("click", addSelectedFromLibrary);
  $("#library-select-new").addEventListener("click", () => {
    for (const it of libraryItems) if (!onReportItem(it)) librarySelected.add(it.ref);
    renderLibrary();
  });
  $("#show-deleted").addEventListener("change", openReportDialog);
  function normalizeRepairNo(v) {
    v = (v || "").trim().toUpperCase();
    return /^\d{4,7}$/.test(v) ? "R" + v : v;     // "36169" -> "R36169"
  }
  repairInput.addEventListener("change", () => {
    const up = normalizeRepairNo(repairInput.value);
    if (repairInput.value !== up) { repairInput.value = up; updateRevisionBanner(); }
    refreshLibraryCount();
  });

  async function showWhoAmI() {
    try {
      const me = await (await api("/api/me")).json();
      if (me.auth_enabled && me.user) {
        const el = $("#whoami");
        el.innerHTML = `Signed in as <b>${esc(me.name || me.user)}</b> · <a href="/logout">sign out</a>`;
        el.hidden = false;
      }
    } catch (_) { /* header stays quiet */ }
  }

  async function checkStorage() {
    try {
      const st = await (await api("/api/storage/status")).json();
      if (!st.available) toast(`Storage offline: ${st.reason}`, true);
    } catch (err) {
      toast(`Storage check failed: ${err.message}`, true);
    }
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ------------------------------------------------------------------- zoom
  let zoomCanvas = null;
  let zoomCard = null;

  function openZoom(card) {
    zoomCard = card;
    const m = openModal("#modal-zoom");
    const wrap = $("#zoom-wrap");
    // Replace the canvas node so listeners from the previous photo are dropped.
    const old = $("#zoom-canvas");
    const fresh = old.cloneNode(false);
    old.replaceWith(fresh);

    zoomCanvas = new PhotoCanvas(fresh, card.photo, () => {
      const a = card.photo.annotations[zoomCanvas.selected];
      if (a && Number($("#zoom-size").value) !== a.size) $("#zoom-size").value = a.size;
      if (a && $("#zoom-color").value !== (a.color || DEFAULT_COLOR)) { $("#zoom-color").value = a.color || DEFAULT_COLOR; paintColorSelect($("#zoom-color")); }
      markDirty();
    });
    zoomCanvas.symbol = card.symbolSelect.value;
    zoomCanvas.symbolSize = clampSize(card.sizeInput.value);
    zoomCanvas.color = card.colorSelect.value;
    $("#zoom-symbol").value = zoomCanvas.symbol;
    $("#zoom-size").value = zoomCanvas.symbolSize;
    $("#zoom-color").value = zoomCanvas.color; paintColorSelect($("#zoom-color"));

    $("#zoom-range").value = 100;
    applyZoom();
    requestAnimationFrame(() => { applyZoom(); fresh.focus(); });
    void m;
    void wrap;
  }

  function applyZoom() {
    const zoom = Number($("#zoom-range").value) / 100;
    $("#zoom-label").textContent = `${Math.round(zoom * 100)}%`;
    const wrap = $("#zoom-wrap");
    const c = $("#zoom-canvas");
    const w = Math.max(100, (wrap.clientWidth - 2) * zoom);
    const h = Math.max(100, (wrap.clientHeight - 2) * zoom);
    c.style.width = `${w}px`;
    c.style.height = `${h}px`;
    if (zoomCanvas) zoomCanvas.draw();
  }

  function closeZoom() {
    if (zoomCanvas) { zoomCanvas.destroy(); zoomCanvas = null; }
    if (zoomCard) {
      zoomCard.symbolSelect.value = $("#zoom-symbol").value;
      zoomCard.canvas.symbol = $("#zoom-symbol").value;
      zoomCard.colorSelect.value = $("#zoom-color").value; paintColorSelect(zoomCard.colorSelect);
      zoomCard.canvas.color = $("#zoom-color").value;
      zoomCard.sizeInput.value = clampSize($("#zoom-size").value);
      zoomCard.canvas.symbolSize = clampSize($("#zoom-size").value);
      zoomCard.canvas.selected = null;
      zoomCard.refresh();
      zoomCard = null;
    }
  }

  $("#zoom-range").addEventListener("input", applyZoom);
  $("#zoom-reset").addEventListener("click", () => { $("#zoom-range").value = 100; applyZoom(); });
  $("#zoom-symbol").addEventListener("change", () => { if (zoomCanvas) zoomCanvas.symbol = $("#zoom-symbol").value; });
  $("#zoom-color").addEventListener("change", () => {
    if (!zoomCanvas) return;
    zoomCanvas.color = $("#zoom-color").value;
    const a = zoomCanvas.photo.annotations[zoomCanvas.selected];
    if (a) { a.color = zoomCanvas.color; markDirty(); }
    zoomCanvas.draw();
  });
  $("#zoom-size").addEventListener("input", () => {
    if (!zoomCanvas) return;
    const v = clampSize($("#zoom-size").value);
    zoomCanvas.symbolSize = v;
    const a = zoomCanvas.photo.annotations[zoomCanvas.selected];
    if (a) { a.size = v; markDirty(); }
    zoomCanvas.draw();
  });
  window.addEventListener("resize", () => { if (zoomCanvas) applyZoom(); });

  // -------------------------------------------------------------------- PDF
  function pdfFileName() {
    return (($("#f-repair_no").value || "").trim() || "RepairEvaluation") + ".pdf";
  }

  async function fetchPdfBlob() {
    const res = await api("/api/pdf", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collectData()),
    });
    return await res.blob();
  }

  function revokePdf() {
    if (state.pdfUrl) { URL.revokeObjectURL(state.pdfUrl); state.pdfUrl = null; }
    $("#pdf-frame").src = "about:blank";
  }

  async function previewPdf() {
    setStatus("Building PDF preview…");
    try {
      const blob = await fetchPdfBlob();
      revokePdf();
      state.pdfUrl = URL.createObjectURL(blob);
      state.pdfName = pdfFileName();
      openModal("#modal-pdf");
      $("#pdf-frame").src = state.pdfUrl;
      setStatus("PDF preview ready");
    } catch (err) {
      toast(`Unable to preview PDF: ${err.message}`, true);
      setStatus("");
    }
  }

  function triggerDownload(url, name) {
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function exportPdf() {
    setStatus("Building PDF…");
    try {
      const blob = await fetchPdfBlob();
      const url = URL.createObjectURL(blob);
      triggerDownload(url, pdfFileName());
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      setStatus(`PDF created: ${pdfFileName()}`);
      toast(`PDF downloaded: ${pdfFileName()}`);
    } catch (err) {
      toast(`Unable to create PDF: ${err.message}`, true);
      setStatus("");
    }
  }

  $("#pdf-download").addEventListener("click", () => {
    if (state.pdfUrl) triggerDownload(state.pdfUrl, state.pdfName);
  });
  $("#pdf-open-tab").addEventListener("click", () => {
    if (state.pdfUrl) window.open(state.pdfUrl, "_blank");
  });

  // ------------------------------------------------------------------- help
  function showHelp(tab = "how") {
    openModal("#modal-help");
    $$("#help-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    $$(".help-body section").forEach((s) => { s.hidden = s.dataset.panel !== tab; });
  }
  $$("#help-tabs button").forEach((b) => b.addEventListener("click", () => showHelp(b.dataset.tab)));

  const helpMenu = $("#help-menu");
  $("#btn-help-menu").addEventListener("click", (e) => { e.stopPropagation(); helpMenu.hidden = !helpMenu.hidden; });
  document.addEventListener("click", () => { helpMenu.hidden = true; });
  $$("#help-menu button").forEach((b) => b.addEventListener("click", () => { helpMenu.hidden = true; showHelp(b.dataset.help); }));

  // ------------------------------------------------------- Prophet 21 link
  const custInput = $("#f-customer");
  const custList = $("#customer-suggestions");
  const custTag = $("#customer-id-tag");
  const custClear = $("#customer-clear");
  const contactInput = $("#f-customer_contact");
  const contactSelect = $("#f-contact_select");
  const emailInput = $("#f-customer_email");
  const overrideBox = $("#email-override");
  const overrideWrap = $("#email-override-wrap");
  let suggestTimer = null;
  let suggestions = [];
  let activeSuggestion = -1;
  let suggestSeq = 0;

  async function checkP21() {
    const badge = $("#p21-badge");
    try {
      const st = await (await api("/api/p21/status")).json();
      state.p21Available = !!st.available;
      if (st.available) {
        badge.textContent = `· linked to P21 (${st.server})`;
        badge.classList.remove("off");
        badge.title = `Connected as ${st.user}`;
      } else {
        badge.textContent = "· P21 offline, free text";
        badge.classList.add("off");
        badge.title = st.reason || "";
        custInput.placeholder = "";
      }
    } catch (err) {
      state.p21Available = false;
      badge.textContent = "· P21 offline, free text";
      badge.classList.add("off");
      badge.title = err.message;
      custInput.placeholder = "";
    }
  }

  function hideSuggestions() {
    custList.hidden = true;
    custList.innerHTML = "";
    suggestions = [];
    activeSuggestion = -1;
  }

  function renderSuggestions(items, note) {
    custList.innerHTML = "";
    suggestions = items;
    activeSuggestion = -1;
    if (note) {
      const li = document.createElement("li");
      li.className = "info";
      li.textContent = note;
      custList.appendChild(li);
    }
    items.forEach((c, i) => {
      const li = document.createElement("li");
      const loc = [c.city, c.state].filter(Boolean).join(", ");
      li.innerHTML = `<span>${esc(customerLabel(c))}</span><span class="sub">${esc(loc)}</span>`;
      li.addEventListener("mousedown", (e) => { e.preventDefault(); selectCustomer(c); });
      li.addEventListener("mousemove", () => setActiveSuggestion(i));
      custList.appendChild(li);
    });
    custList.hidden = !(items.length || note);
  }

  function setActiveSuggestion(i) {
    activeSuggestion = i;
    $$("li", custList).filter((li) => !li.classList.contains("info")).forEach((li, k) => li.classList.toggle("active", k === i));
  }

  async function searchCustomers() {
    const q = custInput.value.trim();
    if (!state.p21Available || q.length < 2) { hideSuggestions(); return; }
    const seq = ++suggestSeq;
    try {
      const res = await (await api(`/api/p21/customers?q=${encodeURIComponent(q)}&limit=25`)).json();
      if (seq !== suggestSeq) return;               // a newer search finished first
      if (document.activeElement !== custInput) return;
      renderSuggestions(res, res.length ? null : "No P21 customers match");
    } catch (err) {
      if (seq === suggestSeq) renderSuggestions([], `P21 search failed: ${err.message}`);
    }
  }

  // Customers and contacts are always shown as "# - name".
  function customerLabel(c) { return `${c.customer_id} - ${c.customer_name}`; }
  function contactLabel(c) { return `${c.contact_id} - ${c.contact_name}`; }

  function setCustomerLink(id) {
    state.customerId = id;
    custTag.textContent = id ? `P21 #${id}` : "";
    custTag.hidden = !id;
    custClear.hidden = !id;
  }

  function showContactMode(useSelect) {
    contactSelect.hidden = !useSelect;
    contactInput.hidden = useSelect;
  }

  function lockEmail(locked) {
    emailInput.readOnly = locked;
    emailInput.classList.toggle("locked", locked);
  }

  function updateOverrideUi() {
    const linked = !!state.contactId;
    overrideWrap.hidden = !linked;
    if (!linked) { overrideBox.checked = false; lockEmail(false); return; }
    overrideBox.checked = state.emailOverride;
    lockEmail(!state.emailOverride);
  }

  function contactEmail(id) {
    const c = state.contacts.find((x) => String(x.contact_id) === String(id));
    return c ? (c.email_address || "") : "";
  }

  function fillContactSelect(selectedId) {
    contactSelect.innerHTML = "";
    const first = document.createElement("option");
    first.value = "";
    first.textContent = state.contacts.length ? "— select a contact —" : "— no contacts in P21 —";
    contactSelect.appendChild(first);
    for (const c of state.contacts) {
      const o = document.createElement("option");
      o.value = String(c.contact_id);
      o.textContent = contactLabel(c);
      contactSelect.appendChild(o);
    }
    contactSelect.value = selectedId && state.contacts.some((c) => String(c.contact_id) === String(selectedId)) ? String(selectedId) : "";
  }

  async function loadContacts(customerId, keepContactId) {
    try {
      state.contacts = await (await api(`/api/p21/customers/${encodeURIComponent(customerId)}/contacts`)).json();
    } catch (err) {
      state.contacts = [];
      toast(`Unable to load P21 contacts: ${err.message}`, true);
    }
    if (state.contacts.length) {
      showContactMode(true);
      fillContactSelect(keepContactId);
      if (!contactSelect.value) {
        state.contactId = null;
        if (!keepContactId) contactInput.value = "";
      }
    } else {
      showContactMode(false);
      state.contactId = null;
    }
    updateOverrideUi();
  }

  async function selectCustomer(c) {
    hideSuggestions();
    custInput.value = customerLabel(c);
    setCustomerLink(c.customer_id);
    state.contactId = null;
    state.emailOverride = false;
    contactInput.value = "";
    emailInput.value = "";
    markDirty();
    await loadContacts(c.customer_id, null);
  }

  function clearCustomerLink({ keepText = true } = {}) {
    setCustomerLink(null);
    state.contacts = [];
    state.contactId = null;
    state.emailOverride = false;
    showContactMode(false);
    updateOverrideUi();
    if (!keepText) custInput.value = "";
  }

  function onContactChosen() {
    const id = contactSelect.value;
    const c = state.contacts.find((x) => String(x.contact_id) === id);
    state.contactId = c ? String(c.contact_id) : null;
    contactInput.value = c ? contactLabel(c) : "";
    if (c && !state.emailOverride) emailInput.value = c.email_address || "";
    if (!c) { state.emailOverride = false; emailInput.value = ""; }
    updateOverrideUi();
    markDirty();
  }

  overrideBox.addEventListener("change", async () => {
    if (!state.contactId) return;
    if (overrideBox.checked) {
      state.emailOverride = true;
      updateOverrideUi();
      emailInput.focus();
      emailInput.select();
      markDirty();
      return;
    }
    // Unchecking discards the manual address - ask first.
    const ok = await confirmDialog(
      "Turn off email override?",
      `The address you entered will be replaced with the P21 email for this contact` +
      (contactEmail(state.contactId) ? ` (${contactEmail(state.contactId)}).` : ". P21 has no email on file for this contact."),
    );
    if (!ok) { overrideBox.checked = true; return; }
    state.emailOverride = false;
    emailInput.value = contactEmail(state.contactId);
    updateOverrideUi();
    markDirty();
  });

  /** Promise-based Yes/No dialog styled like the rest of the app. */
  function confirmDialog(title, text) {
    return new Promise((resolve) => {
      const m = $("#modal-confirm");
      $("#confirm-title").textContent = title;
      $("#confirm-text").textContent = text;
      const yes = $("#confirm-yes"), no = $("#confirm-no");
      const done = (v) => {
        m.hidden = true;
        yes.removeEventListener("click", onYes);
        no.removeEventListener("click", onNo);
        m.removeEventListener("click", onBackdrop);
        resolve(v);
      };
      const onYes = () => done(true);
      const onNo = () => done(false);
      const onBackdrop = (e) => { if (e.target === m) done(false); };
      yes.addEventListener("click", onYes);
      no.addEventListener("click", onNo);
      m.addEventListener("click", onBackdrop);
      m.hidden = false;
      no.focus();
    });
  }

  contactSelect.addEventListener("change", onContactChosen);
  custClear.addEventListener("click", () => { clearCustomerLink({ keepText: false }); markDirty(); custInput.focus(); });

  custInput.addEventListener("input", () => {
    // Typing after a pick breaks the P21 link; the text stays as free text.
    if (state.customerId) clearCustomerLink({ keepText: true });
    clearTimeout(suggestTimer);
    suggestTimer = setTimeout(searchCustomers, 250);
  });
  custInput.addEventListener("focus", () => { if (custInput.value.trim().length >= 2 && !state.customerId) searchCustomers(); });
  custInput.addEventListener("blur", () => setTimeout(hideSuggestions, 150));
  custInput.addEventListener("keydown", (e) => {
    if (custList.hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActiveSuggestion(Math.min(suggestions.length - 1, activeSuggestion + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActiveSuggestion(Math.max(0, activeSuggestion - 1)); }
    else if (e.key === "Enter") { if (activeSuggestion >= 0) { e.preventDefault(); selectCustomer(suggestions[activeSuggestion]); } }
    else if (e.key === "Escape") { e.stopPropagation(); hideSuggestions(); }
  });

  /** Re-establish the P21 link when a saved report is opened or a new one started. */
  function restoreP21Link(data) {
    hideSuggestions();
    state.emailOverride = !!data.email_override;
    if (data.customer_id && state.p21Available) {
      setCustomerLink(String(data.customer_id));
      state.contactId = data.contact_id ? String(data.contact_id) : null;
      showContactMode(false);
      updateOverrideUi();
      loadContacts(String(data.customer_id), state.contactId).then(() => {
        // Saved text wins over live P21 data so the report reopens as it was saved.
        if (state.contactId) {
          contactInput.value = data.customer_contact || contactInput.value;
          emailInput.value = data.customer_email || emailInput.value;
        }
        updateOverrideUi();
        clearDirty();
      });
    } else {
      setCustomerLink(data.customer_id ? String(data.customer_id) : null);
      state.contacts = [];
      state.contactId = null;
      showContactMode(false);
      updateOverrideUi();
    }
  }

  // ---------------------------------------------------------------- wiring
  $("#btn-new").addEventListener("click", () => newReport());
  $("#btn-open").addEventListener("click", openReportDialog);
  $("#btn-save").addEventListener("click", saveReport);
  $("#btn-preview").addEventListener("click", previewPdf);
  $("#btn-export").addEventListener("click", exportPdf);
  $("#btn-add-photo").addEventListener("click", () => $("#file-input").click());
  $("#file-input").addEventListener("change", (e) => {
    uploadPhotos(Array.from(e.target.files));
    e.target.value = "";
  });

  for (const f of FIELDS) {
    $(`#f-${f}`).addEventListener("input", markDirty);
    $(`#f-${f}`).addEventListener("change", markDirty);
  }

  document.addEventListener("keydown", (e) => {
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && !e.shiftKey && !e.altKey) {
      const k = e.key.toLowerCase();
      if (k === "s") { e.preventDefault(); saveReport(); }
      else if (k === "o") { e.preventDefault(); openReportDialog(); }
      else if (k === "p") { e.preventDefault(); previewPdf(); }
      else if (k === "n") { e.preventDefault(); newReport(); }
    } else if (e.key === "F1") {
      e.preventDefault(); showHelp("how");
    } else if (e.key === "Escape") {
      const m = topModal();
      if (m && !(e.target instanceof HTMLCanvasElement)) closeModal(m);
    }
  });

  window.addEventListener("beforeunload", (e) => {
    if (state.dirty) { e.preventDefault(); e.returnValue = ""; }
  });

  // Drag & drop photos anywhere on the page.
  document.addEventListener("dragover", (e) => { e.preventDefault(); });
  document.addEventListener("drop", (e) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer?.files || []).filter((f) => /\.(jpe?g|png|bmp|webp)$/i.test(f.name));
    if (files.length) uploadPhotos(files);
  });

  // ------------------------------------------------------------------- init
  async function init() {
    try {
      cfg = { ...cfg, ...(await (await api("/api/config")).json()) };
    } catch (err) {
      toast(`Unable to load configuration: ${err.message}`, true);
    }
    const tech = $("#f-technician");
    tech.innerHTML = "";
    for (const t of cfg.technicians) {
      const o = document.createElement("option");
      o.value = t; o.textContent = t;
      tech.appendChild(o);
    }
    fillSymbolSelect($("#zoom-symbol"));
    fillColorSelect($("#zoom-color"));
    if (cfg.version) $("#about-version").textContent = `Version ${cfg.version}`;
    const link = parseUrl();          // read before the blank form resets the address bar
    await Promise.all([checkP21(), checkStorage(), showWhoAmI()]);
    newReport(true);
    if (link) await loadReport(link.repairNo, link.revision, null);
  }

  init();
})();

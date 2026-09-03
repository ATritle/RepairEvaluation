/* IFP Repair Evaluation - web front end
 * Ports the PyQt6 desktop app (main.py) to the browser. Talks to the FastAPI
 * backend in app/main.py. No build step, no framework.
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
    id: null,
    photos: [],
    dirty: false,
    cards: [],
    pdfUrl: null,
    pdfName: "RepairEvaluation.pdf",
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

  // ---------------------------------------------------------- symbol drawing
  // Mirrors PhotoCanvas.draw_symbol() in the desktop app so the browser
  // preview and the PDF (app/pdf_builder.py) agree on geometry.
  function drawSymbol(ctx, symbol, x, y, base, symbolSize = 100, selected = false) {
    const size = Math.max(18, Math.min(70, base * 0.10)) * Math.max(0.25, symbolSize / 100);
    const lineWidth = Math.max(2, size * 0.065) + (selected ? 1.5 : 0);
    ctx.save();
    ctx.strokeStyle = selected ? "#ffff00" : "#ff0000";
    ctx.lineWidth = lineWidth;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();

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
    ctx.stroke();
    ctx.restore();
  }

  // ------------------------------------------------------------ PhotoCanvas
  const imageCache = new Map();
  function loadImage(file) {
    if (imageCache.has(file)) return imageCache.get(file);
    const p = new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("Unable to load image"));
      img.src = `/photos/${encodeURIComponent(file)}`;
    });
    imageCache.set(file, p);
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
      this.selected = null;
      this.dragging = false;
      this.img = null;
      this.failed = false;
      this.rect = null;

      photo.annotations = photo.annotations || [];

      loadImage(photo.file)
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
        drawSymbol(ctx, a.symbol, x + (a.x ?? 0.5) * sw, y + (a.y ?? 0.5) * sh, base, a.size ?? 100, i === this.selected);
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
      $(".file-name", this.el).textContent = photo.name || photo.file;

      this.symbolSelect = $(".symbol-select", this.el);
      fillSymbolSelect(this.symbolSelect);
      this.sizeInput = $(".size-input", this.el);

      this.canvas = new PhotoCanvas($(".photo-canvas", this.el), photo, () => this.markupChanged());

      this.symbolSelect.addEventListener("change", () => { this.canvas.symbol = this.symbolSelect.value; });
      this.sizeInput.addEventListener("input", () => this.sizeChanged());

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

    markupChanged() {
      const a = this.photo.annotations[this.canvas.selected];
      if (a && Number(this.sizeInput.value) !== a.size) this.sizeInput.value = a.size;
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
    const fd = new FormData();
    for (const f of files) fd.append("files", f, f.name);
    setStatus(`Uploading ${files.length} photo${files.length === 1 ? "" : "s"}…`);
    try {
      const res = await api("/api/photos", { method: "POST", body: fd });
      const uploaded = await res.json();
      for (const u of uploaded) {
        state.photos.push({ file: u.file, name: u.name, description: "", rotation: 0, annotations: [] });
      }
      renderPhotos();
      markDirty();
      setStatus(`Added ${uploaded.length} photo${uploaded.length === 1 ? "" : "s"}`);
    } catch (err) {
      toast(`Upload failed: ${err.message}`, true);
      setStatus("");
    }
  }

  // ------------------------------------------------------------ form <-> data
  function collectData() {
    const data = { id: state.id, received_condition: "" };
    for (const f of FIELDS) data[f] = $(`#f-${f}`).value;
    for (const k of ["repair_no", "technician", "customer", "customer_contact", "customer_email", "model", "serial", "customer_po", "material"]) {
      data[k] = (data[k] || "").trim();
    }
    data.photos = state.photos.map((p) => ({
      file: p.file,
      name: p.name || "",
      description: p.description || "",
      rotation: p.rotation || 0,
      annotations: (p.annotations || []).map((a) => ({
        symbol: a.symbol || "arrow_up",
        x: a.x ?? 0.5,
        y: a.y ?? 0.5,
        size: a.size ?? 100,
      })),
    }));
    return data;
  }

  function loadData(data) {
    state.id = data.id || null;
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
    state.photos = (data.photos || []).map((p) => ({
      file: p.file,
      name: p.name || "",
      description: p.description || "",
      rotation: p.rotation || 0,
      annotations: (p.annotations || []).map((a) => ({
        symbol: a.symbol || "arrow_up", x: a.x ?? 0.5, y: a.y ?? 0.5, size: a.size ?? 100,
      })),
    }));
    renderPhotos();
    clearDirty();
  }

  function newReport(force = false) {
    if (!force && state.dirty && !confirm("This repair evaluation has unsaved changes. Start a new one anyway?")) return;
    loadData({ date: todayIso(), technician: cfg.technicians[0] || "" });
    setStatus("New evaluation");
  }

  async function saveReport() {
    const data = collectData();
    setStatus("Saving…");
    try {
      const res = await api("/api/reports", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
      });
      const saved = await res.json();
      state.id = saved.id;
      clearDirty();
      const label = saved.repair_no || "evaluation";
      setStatus(`Saved ${label} at ${new Date().toLocaleTimeString()}`);
      toast("Evaluation saved");
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
  async function openReportDialog() {
    const m = openModal("#modal-open");
    const tbody = $("#report-list");
    tbody.innerHTML = "<tr><td colspan='7' class='muted'>Loading…</td></tr>";
    try {
      const list = await (await api("/api/reports")).json();
      tbody.innerHTML = "";
      $("#report-empty").hidden = list.length > 0;
      for (const r of list) {
        const tr = document.createElement("tr");
        const saved = r.updated_at ? new Date(r.updated_at).toLocaleString() : "";
        tr.innerHTML = `
          <td><b>${esc(r.repair_no || "(no repair #)")}</b></td>
          <td>${esc(r.customer)}</td>
          <td>${esc(r.date)}</td>
          <td>${esc(r.technician)}</td>
          <td>${r.photo_count}</td>
          <td class="muted">${esc(saved)}</td>
          <td><button class="btn small danger" title="Delete">Delete</button></td>`;
        tr.addEventListener("click", () => loadReport(r.id, m));
        $("button", tr).addEventListener("click", async (e) => {
          e.stopPropagation();
          if (!confirm(`Delete saved evaluation ${r.repair_no || r.id}? This cannot be undone.`)) return;
          try {
            await api(`/api/reports/${encodeURIComponent(r.id)}`, { method: "DELETE" });
            if (state.id === r.id) state.id = null;
            openReportDialog();
          } catch (err) { toast(`Delete failed: ${err.message}`, true); }
        });
        tbody.appendChild(tr);
      }
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan='7' class='muted'>Unable to load: ${esc(err.message)}</td></tr>`;
    }
  }

  async function loadReport(id, modal) {
    if (state.dirty && !confirm("This repair evaluation has unsaved changes. Open another anyway?")) return;
    try {
      const data = await (await api(`/api/reports/${encodeURIComponent(id)}`)).json();
      loadData(data);
      closeModal(modal);
      setStatus(`Opened ${data.repair_no || id}`);
    } catch (err) {
      toast(`Unable to open report: ${err.message}`, true);
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
      markDirty();
    });
    zoomCanvas.symbol = card.symbolSelect.value;
    zoomCanvas.symbolSize = clampSize(card.sizeInput.value);
    $("#zoom-symbol").value = zoomCanvas.symbol;
    $("#zoom-size").value = zoomCanvas.symbolSize;

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
    if (cfg.version) $("#about-version").textContent = `Version ${cfg.version}`;
    newReport(true);
  }

  init();
})();

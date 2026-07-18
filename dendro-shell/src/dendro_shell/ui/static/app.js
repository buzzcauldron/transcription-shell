/* dendro-shell browser UI */
(() => {
  const $ = (id) => document.getElementById(id);
  const canvas = $("canvas");
  const ctx = canvas.getContext("2d");
  const spark = $("spark");
  const sctx = spark.getContext("2d");

  let project = null;
  let img = new Image();
  let scale = 1; // display scale vs natural
  let dragTick = null;
  let modePath = true;
  let cursor = { x: 0, y: 0 };
  let trainTimer = null;
  let paintStroke = null;

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || res.statusText);
    }
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res;
  }

  function setStatus(msg) {
    $("status").textContent = msg;
  }

  function primaryPath() {
    if (!project) return null;
    if (!project.paths.length) {
      project.paths.push({ id: "path0", points: [], rings: [] });
    }
    return project.paths[0];
  }

  function imgToCanvas(ix, iy) {
    return { x: ix * scale, y: iy * scale };
  }
  function canvasToImg(cx, cy) {
    return { x: cx / scale, y: cy / scale };
  }

  function redraw() {
    if (!img.naturalWidth) return;
    const maxW = canvas.parentElement.clientWidth - 2;
    scale = Math.min(1, maxW / img.naturalWidth);
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    const path = primaryPath();
    if (!path) return;

    // path
    if (path.points.length) {
      ctx.strokeStyle = "rgba(111, 191, 163, 0.95)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      path.points.forEach((p, i) => {
        const c = imgToCanvas(p.x, p.y);
        if (i === 0) ctx.moveTo(c.x, c.y);
        else ctx.lineTo(c.x, c.y);
      });
      ctx.stroke();
      path.points.forEach((p) => {
        const c = imgToCanvas(p.x, p.y);
        ctx.fillStyle = "#6fbfa3";
        ctx.beginPath();
        ctx.arc(c.x, c.y, 3.5, 0, Math.PI * 2);
        ctx.fill();
      });
    }

    // pith
    if (project.pith) {
      const c = imgToCanvas(project.pith.x, project.pith.y);
      ctx.strokeStyle = "#d4a35c";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(c.x - 8, c.y);
      ctx.lineTo(c.x + 8, c.y);
      ctx.moveTo(c.x, c.y - 8);
      ctx.lineTo(c.x, c.y + 8);
      ctx.stroke();
    }

    // rings
    const ordered = [...(path.rings || [])].sort((a, b) => b.distance_px - a.distance_px);
    ordered.forEach((r, i) => {
      const pt = pointAtDistance(path.points, r.distance_px);
      if (!pt) return;
      const c = imgToCanvas(pt.x, pt.y);
      let color = "#e07a5f";
      if (r.flag === "missing") color = "#9aada3";
      if (r.flag === "false") color = "#666";
      if (r.flag === "uncertain") color = "#d4a35c";
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(c.x, c.y, 4.5, 0, Math.PI * 2);
      ctx.fill();
      if (r.year != null) {
        ctx.fillStyle = "rgba(232,239,233,0.85)";
        ctx.font = "11px IBM Plex Sans, sans-serif";
        ctx.fillText(String(r.year), c.x + 6, c.y - 6);
      }
    });

    renderRingList();
  }

  function pointAtDistance(points, dist) {
    if (!points || points.length < 2) return points?.[0] || null;
    let acc = 0;
    for (let i = 0; i < points.length - 1; i++) {
      const a = points[i], b = points[i + 1];
      const seg = Math.hypot(b.x - a.x, b.y - a.y);
      if (acc + seg >= dist) {
        const t = seg > 0 ? (dist - acc) / seg : 0;
        return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
      }
      acc += seg;
    }
    return points[points.length - 1];
  }

  function distanceAlongPath(points, x, y) {
    if (!points || points.length < 2) return 0;
    let best = 0, bestD = Infinity, acc = 0;
    for (let i = 0; i < points.length - 1; i++) {
      const a = points[i], b = points[i + 1];
      const vx = b.x - a.x, vy = b.y - a.y;
      const len2 = vx * vx + vy * vy || 1;
      let t = ((x - a.x) * vx + (y - a.y) * vy) / len2;
      t = Math.max(0, Math.min(1, t));
      const px = a.x + vx * t, py = a.y + vy * t;
      const d = Math.hypot(x - px, y - py);
      if (d < bestD) {
        bestD = d;
        best = acc + Math.hypot(vx, vy) * t;
      }
      acc += Math.hypot(vx, vy);
    }
    return best;
  }

  function nearestTick(imgPt, maxDist = 12) {
    const path = primaryPath();
    if (!path) return null;
    let best = null, bestD = maxDist / scale;
    path.rings.forEach((r, idx) => {
      const pt = pointAtDistance(path.points, r.distance_px);
      if (!pt) return;
      const d = Math.hypot(pt.x - imgPt.x, pt.y - imgPt.y);
      if (d < bestD) {
        bestD = d;
        best = { ring: r, index: idx };
      }
    });
    return best;
  }

  function renderRingList() {
    const path = primaryPath();
    const ul = $("ringList");
    ul.innerHTML = "";
    if (!path) return;
    const rings = [...path.rings].sort((a, b) => b.distance_px - a.distance_px);
    rings.forEach((r) => {
      const li = document.createElement("li");
      li.className = `flag-${r.flag}`;
      li.innerHTML = `<span>${r.year ?? "—"} · ${r.distance_px.toFixed(1)}px · ${r.flag}</span><span>${(r.confidence ?? 1).toFixed(2)}</span>`;
      ul.appendChild(li);
    });
  }

  async function loadProjectImage() {
    if (!project) return;
    const preset = $("preset").value || "none";
    const url = `/api/image?preset=${encodeURIComponent(preset)}&_=${Date.now()}`;
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = reject;
      img.src = url;
    });
    // image endpoint may resize; use natural from project file via scale from canvas parent —
    // fetch full dims from project by measuring: use unscaled when preset applied server-side with max_side.
    // For accurate coords, open raw without max shrink when possible — API max_side=1600.
    // Store natural dims from image.
    redraw();
    await refreshSeries();
  }

  async function refreshSeries() {
    const s = await api("/api/series");
    drawSpark(s);
  }

  function drawSpark(s) {
    const w = spark.parentElement.clientWidth;
    const H = 96;
    spark.width = w * devicePixelRatio;
    spark.height = H * devicePixelRatio;
    sctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    sctx.clearRect(0, 0, w, H);
    const vals = s.widths_um || [];
    const years = s.years || [];
    const flags = s.flags || [];
    if (!vals.length) {
      sctx.fillStyle = "#9aada3";
      sctx.font = "12px IBM Plex Sans";
      sctx.fillText("Ring-width timeline appears after detect / edit", 8, 48);
      return;
    }
    const max = Math.max(...vals, 1);
    const bw = w / vals.length;
    const base = 72;
    vals.forEach((v, i) => {
      const x = i * bw;
      const flag = flags[i] || "ok";
      if (flag === "missing" || v <= 0) {
        sctx.fillStyle = "rgba(154,173,163,0.45)";
        sctx.fillRect(x + 1, base - 8, Math.max(1, bw - 2), 8);
        sctx.strokeStyle = "#9aada3";
        sctx.beginPath();
        sctx.moveTo(x + bw / 2 - 3, base - 14);
        sctx.lineTo(x + bw / 2 + 3, base - 8);
        sctx.stroke();
        return;
      }
      const h = (v / max) * 52;
      const pointer = s.skeleton && s.skeleton[i];
      sctx.fillStyle = pointer ? "#d4a35c" : "#6fbfa3";
      sctx.fillRect(x + 1, base - h, Math.max(1, bw - 2), h);
      if (pointer) {
        sctx.strokeStyle = "#d4a35c";
        sctx.beginPath();
        sctx.moveTo(x + bw / 2, base + 2);
        sctx.lineTo(x + bw / 2, base + 12);
        sctx.stroke();
      }
      const y = years[i];
      if (y != null && y % 10 === 0) {
        sctx.fillStyle = "#e8efe9";
        sctx.font = "9px IBM Plex Sans";
        sctx.fillText(String(y), x + 1, H - 4);
      }
    });
  }

  async function refreshTiles() {
    const rail = $("tileRail");
    if (!project?.paths?.[0]?.rings?.length) {
      rail.innerHTML = "<span class='mono'>Detect rings to populate zoom tiles</span>";
      return;
    }
    try {
      const res = await fetch(`/api/viz/tiles?_=${Date.now()}`);
      if (!res.ok) throw new Error("tiles failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      // Also build individual cards from series for interaction feel
      const s = await api("/api/series");
      rail.innerHTML = "";
      const sheet = document.createElement("img");
      sheet.src = url;
      sheet.alt = "Ring tile contact sheet";
      sheet.style.height = "88px";
      sheet.style.width = "auto";
      sheet.style.borderRadius = "4px";
      sheet.style.border = "1px solid rgba(232,239,233,0.12)";
      rail.appendChild(sheet);
      // Year chips under strip
      const chips = document.createElement("div");
      chips.className = "tile-rail";
      chips.style.marginTop = "0.35rem";
      (s.years || []).forEach((y, i) => {
        const card = document.createElement("div");
        card.className = "tile-card" + ((s.flags || [])[i] === "missing" ? " missing" : "");
        card.innerHTML = `<div class="cap">${y ?? "—"} · ${(s.flags || [])[i] || "ok"}</div>`;
        chips.appendChild(card);
      });
      rail.appendChild(chips);
    } catch (err) {
      rail.innerHTML = `<span class="mono">${err.message || err}</span>`;
    }
  }

  async function refreshVizFigures() {
    const bust = Date.now();
    $("growthImg").src = `/api/viz/growth?_=${bust}`;
    $("skeletonImg").src = `/api/viz/skeleton?_=${bust}`;
    const preset = $("preset")?.value || "dark_disc";
    if ($("breaksImg")) {
      $("breaksImg").src = `/api/viz/breaks?preset=${encodeURIComponent(preset)}&_=${bust}`;
    }
  }

  async function syncProjectToServer() {
    if (!project) return;
    // Fix display scale: canvas coords assume image natural = API image size.
    // Re-map path if needed — we store image-space coords from canvasToImg using displayed image.
    const res = await api("/api/project", {
      method: "POST",
      body: JSON.stringify({ project }),
    });
    project = res.project;
  }

  async function showProject(p, statusMsg) {
    project = p;
    fillMeta();
    await loadProjectImage();
    redraw();
    await refreshSeries();
    await refreshTiles();
    const n = project.paths?.[0]?.rings?.length || 0;
    setStatus(statusMsg || `${project.sample_code || "sample"} · ${n} rings · ${project.sample_type}`);
  }

  async function bootstrap() {
    const presets = await api("/api/presets");
    const sel = $("preset");
    sel.innerHTML = "";
    const autoOpt = document.createElement("option");
    autoOpt.value = "auto";
    autoOpt.textContent = "auto";
    sel.appendChild(autoOpt);
    (presets.presets || []).forEach((p) => {
      const o = document.createElement("option");
      o.value = p;
      o.textContent = p;
      sel.appendChild(o);
    });

    const proj = await api("/api/project");
    if (proj.project) {
      await showProject(proj.project);
    } else {
      setStatus("Open an image to begin");
    }
    await refreshModels();
    await refreshLibrary();
  }

  function fillMeta() {
    if (!project) return;
    $("sampleCode").value = project.sample_code || "";
    $("species").value = project.species || "";
    $("outerYear").value = project.outer_year ?? "";
    $("mpp").value = project.scale?.micrometers_per_pixel ?? "";
    $("sampleType").value = project.sample_type || "core";
    $("preset").value = project.preprocess_preset || "sanded_core";
    $("method").value = project.detect_method || "classical";
  }

  function readMetaIntoProject() {
    if (!project) return;
    project.sample_code = $("sampleCode").value;
    project.species = $("species").value;
    const oy = $("outerYear").value;
    project.outer_year = oy === "" ? null : parseInt(oy, 10);
    const mpp = $("mpp").value;
    project.scale = project.scale || {};
    project.scale.micrometers_per_pixel = mpp === "" ? null : parseFloat(mpp);
    project.sample_type = $("sampleType").value;
    project.preprocess_preset = $("preset").value;
    project.detect_method = $("method").value;
  }

  $("fileInput").addEventListener("change", async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setStatus(`Opening ${f.name}…`);
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch("/api/open", { method: "POST", body: fd });
    if (!res.ok) {
      setStatus("Failed to open image");
      return;
    }
    const data = await res.json();
    await showProject(data.project, `Opened ${f.name}`);
    await refreshVizFigures();
  });

  $("preset").addEventListener("change", async () => {
    if (!project) return;
    project.preprocess_preset = $("preset").value;
    await loadProjectImage();
    redraw();
  });

  $("btnDetect").addEventListener("click", async () => {
    if (!project) return;
    readMetaIntoProject();
    await syncProjectToServer();
    setStatus("Detecting…");
    try {
      const keep = primaryPath().points.length >= 2 && !$("sampleType").value.includes("auto");
      const res = await api("/api/detect", {
        method: "POST",
        body: JSON.stringify({
          method: $("method").value,
          preset: $("preset").value,
          sample_type: $("sampleType").value,
          outer_year: project.outer_year,
          keep_path: keep,
          path: keep ? primaryPath().points : null,
          pith: project.pith,
        }),
      });
      await showProject(res.project, null);
      await refreshVizFigures();
    } catch (err) {
      setStatus(String(err.message || err));
    }
  });

  $("btnPith").addEventListener("click", async () => {
    if (!project) return;
    const res = await api("/api/pith/estimate", {
      method: "POST",
      body: JSON.stringify({ preset: $("preset").value }),
    });
    project = res.project;
    $("sampleType").value = "disc";
    redraw();
    setStatus("Pith estimated — click stage to refine, then Detect");
  });

  $("btnClearPath").addEventListener("click", () => {
    const path = primaryPath();
    if (!path) return;
    path.points = [];
    path.rings = [];
    redraw();
  });

  $("btnIncline").addEventListener("click", async () => {
    if (!project) return;
    readMetaIntoProject();
    await syncProjectToServer();
    const res = await api("/api/path/incline-pair", {
      method: "POST",
      body: JSON.stringify({ offset_y: 12 }),
    });
    project = res.project;
    redraw();
    await refreshSeries();
    setStatus("Incline partner path added (mean widths on export)");
  });

  $("btnLibrary").addEventListener("click", async () => {
    if (!project) return;
    readMetaIntoProject();
    await syncProjectToServer();
    const res = await api("/api/library/add", { method: "POST", body: "{}" });
    setStatus(`Added to library (${res.entries.length} entries)`);
    await refreshLibrary();
  });

  $("btnExport").addEventListener("click", async () => {
    if (!project) return;
    readMetaIntoProject();
    await syncProjectToServer();
    const res = await api("/api/export", { method: "POST", body: "{}" });
    setStatus(`Exported → ${res.project}`);
  });

  $("btnCrossdate").addEventListener("click", async () => {
    if (!project) return;
    readMetaIntoProject();
    await syncProjectToServer();
    try {
      const res = await api("/api/crossdate", {
        method: "POST",
        body: JSON.stringify({ reference: $("refRwl").value }),
      });
      $("crossOut").textContent = (res.hits || [])
        .map((h) => `lag=${h.lag} r=${h.correlation.toFixed(3)} n=${h.overlap} (${h.reference_id})`)
        .join("\n") || "No hits (need overlap / reference)";
    } catch (err) {
      $("crossOut").textContent = String(err.message || err);
    }
  });

  canvas.addEventListener("pointerdown", (e) => {
    if (!project) return;
    const rect = canvas.getBoundingClientRect();
    const c = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    const pt = canvasToImg(c.x, c.y);

    const brush = $("brushMode")?.value || "off";
    if (brush !== "off") {
      paintStroke = { mode: brush, points: [pt] };
      canvas.setPointerCapture(e.pointerId);
      return;
    }

    if (e.shiftKey || ($("sampleType").value === "disc" && e.altKey)) {
      project.pith = pt;
      redraw();
      return;
    }

    const hit = nearestTick(pt);
    if (hit) {
      dragTick = hit;
      canvas.setPointerCapture(e.pointerId);
      return;
    }
    const path = primaryPath();
    path.points.push(pt);
    redraw();
  });

  canvas.addEventListener("pointermove", (e) => {
    const rect = canvas.getBoundingClientRect();
    cursor = canvasToImg(e.clientX - rect.left, e.clientY - rect.top);
    if (paintStroke) {
      paintStroke.points.push(cursor);
      // live preview
      ctx.fillStyle = paintStroke.mode === "erase" ? "rgba(0,0,0,0.35)" : "rgba(212,163,92,0.55)";
      const c = imgToCanvas(cursor.x, cursor.y);
      ctx.beginPath();
      ctx.arc(c.x, c.y, (parseInt($("brushRadius").value, 10) || 3) * scale, 0, Math.PI * 2);
      ctx.fill();
      return;
    }
    if (!dragTick) return;
    const path = primaryPath();
    dragTick.ring.distance_px = distanceAlongPath(path.points, cursor.x, cursor.y);
    redraw();
  });

  canvas.addEventListener("pointerup", async () => {
    if (paintStroke) {
      const stroke = paintStroke;
      paintStroke = null;
      try {
        const res = await api("/api/paint", {
          method: "POST",
          body: JSON.stringify({
            mode: stroke.mode,
            radius: parseInt($("brushRadius").value, 10) || 3,
            strokes: [{ points: stroke.points }],
          }),
        });
        project = res.project;
        setStatus(stroke.mode === "erase" ? "Erased paint stroke" : "Painted boundary stroke");
        redraw();
      } catch (err) {
        setStatus(String(err.message || err));
      }
      return;
    }
    if (dragTick) {
      dragTick = null;
      readMetaIntoProject();
      await syncProjectToServer();
      await refreshSeries();
    }
  });

  window.addEventListener("keydown", async (e) => {
    if (!project || e.target.matches("input,textarea,select")) return;
    const path = primaryPath();
    if (e.key === "a" || e.key === "A") {
      const d = distanceAlongPath(path.points, cursor.x, cursor.y);
      path.rings.push({ distance_px: d, confidence: 1, flag: "ok", year: null, note: "" });
      redraw();
    } else if (e.key === "d" || e.key === "D") {
      const hit = nearestTick(cursor, 20);
      if (hit) {
        path.rings.splice(hit.index, 1);
        redraw();
      }
    } else if (e.key === "m" || e.key === "M") {
      const hit = nearestTick(cursor, 20);
      if (hit) {
        hit.ring.flag = hit.ring.flag === "missing" ? "ok" : "missing";
        redraw();
      }
    } else if (e.key === "f" || e.key === "F") {
      const hit = nearestTick(cursor, 20);
      if (hit) {
        hit.ring.flag = hit.ring.flag === "false" ? "ok" : "false";
        redraw();
      }
    }
  });

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      $(`panel-${tab.dataset.tab}`).classList.add("active");
    });
  });

  $("btnRefreshPolar").addEventListener("click", async () => {
    if (!project?.pith) {
      setStatus("Set pith first (Estimate pith or Alt+click)");
      return;
    }
    $("polarImg").src = `/api/polar?preset=${encodeURIComponent($("preset").value)}&_=${Date.now()}`;
  });

  $("btnTiles").addEventListener("click", () => refreshTiles());
  $("btnRefreshViz").addEventListener("click", () => refreshVizFigures());
  $("btnBreaks")?.addEventListener("click", () => {
    const bust = Date.now();
    const preset = $("preset")?.value || "dark_disc";
    $("breaksImg").src = `/api/viz/breaks?preset=${encodeURIComponent(preset)}&_=${bust}`;
    document.querySelector('.tab[data-tab="viz"]').click();
  });
  $("btnCompare").addEventListener("click", async () => {
    if (!project) return;
    readMetaIntoProject();
    await syncProjectToServer();
    setStatus("Comparing classical vs U-Net…");
    try {
      const res = await fetch("/api/viz/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          preset: $("preset").value,
          min_distance_px: 12,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || res.statusText);
      }
      const unetErr = res.headers.get("X-UNet-Error");
      const blob = await res.blob();
      $("compareImg").src = URL.createObjectURL(blob);
      setStatus(unetErr ? `Compare drawn (U-Net: ${unetErr})` : "Compare overlay ready");
      document.querySelector('.tab[data-tab="viz"]').click();
    } catch (err) {
      setStatus(String(err.message || err));
    }
  });

  async function refreshLibrary() {
    const lib = await api("/api/library");
    $("libraryInfo").textContent = `${lib.library_dir}\n${lib.entries.length} sample(s)`;
  }

  async function refreshModels() {
    const m = await api("/api/models");
    const ul = $("modelList");
    ul.innerHTML = "";
    (m.models || []).forEach((entry) => {
      const li = document.createElement("li");
      const active = m.active === entry.name;
      li.innerHTML = `<span>${entry.name}${active ? " ●" : ""} <small>${JSON.stringify(entry.metrics || {})}</small></span>`;
      const btn = document.createElement("button");
      btn.className = "btn small";
      btn.textContent = "Activate";
      btn.onclick = async () => {
        await api("/api/models/activate", {
          method: "POST",
          body: JSON.stringify({ name: entry.name }),
        });
        await refreshModels();
      };
      li.appendChild(btn);
      ul.appendChild(li);
    });
  }

  async function pollTrain() {
    const st = await api("/api/train/status");
    $("trainStatus").textContent =
      `${st.state}  epoch ${st.epoch}/${st.epochs}\n` +
      `loss=${(st.loss || 0).toFixed(4)}  dice=${(st.val_dice || 0).toFixed(3)}  f1=${(st.val_f1 || 0).toFixed(3)}\n` +
      (st.message || "");
    if (st.state === "running" || st.state === "stopping") {
      trainTimer = setTimeout(pollTrain, 800);
    } else {
      trainTimer = null;
      await refreshModels();
      if (st.state === "finished" && project) {
        setStatus("Training finished — running compare overlay");
        $("btnCompare").click();
      }
    }
  }

  $("btnTrain").addEventListener("click", async () => {
    const name = $("trainName").value;
    const overwrite = $("trainOverwrite").checked;
    const models = await api("/api/models");
    const exists = (models.models || []).some((m) => m.name === name);
    if (exists && !overwrite) {
      const ok = window.confirm(
        `Model "${name}" already exists. Continue without overwrite (saves a timestamped copy)?\n` +
          `Cancel and enable "Overwrite same name" to replace it.`
      );
      if (!ok) return;
    }
    try {
      await api("/api/train/start", {
        method: "POST",
        body: JSON.stringify({
          name,
          epochs: parseInt($("trainEpochs").value, 10),
          imgsz: parseInt($("trainImgsz").value, 10),
          batch_size: parseInt($("trainBatch").value, 10),
          lr: parseFloat($("trainLr").value),
          device: $("trainDevice").value,
          augment: $("trainAugment").checked,
          fine_tune: $("trainFinetune").checked,
          overwrite,
          species: $("trainSpecies").value || null,
          tag: $("trainTag").value || null,
        }),
      });
      setStatus("Training started");
      if (!trainTimer) pollTrain();
    } catch (err) {
      setStatus(String(err.message || err));
    }
  });

  $("btnTrainStop").addEventListener("click", async () => {
    await api("/api/train/stop", { method: "POST", body: "{}" });
  });

  window.addEventListener("resize", () => redraw());
  bootstrap().catch((err) => setStatus(String(err)));
})();

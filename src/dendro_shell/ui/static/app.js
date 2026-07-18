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
    spark.width = w * devicePixelRatio;
    spark.height = 64 * devicePixelRatio;
    sctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    sctx.clearRect(0, 0, w, 64);
    const vals = s.widths_um || [];
    if (!vals.length) {
      sctx.fillStyle = "#9aada3";
      sctx.font = "12px IBM Plex Sans";
      sctx.fillText("Ring-width sparkline appears after detect / edit", 8, 36);
      return;
    }
    const max = Math.max(...vals, 1);
    const bw = w / vals.length;
    vals.forEach((v, i) => {
      const h = (v / max) * 48;
      sctx.fillStyle = (s.skeleton && s.skeleton[i]) ? "#d4a35c" : "#6fbfa3";
      sctx.fillRect(i * bw + 1, 56 - h, Math.max(1, bw - 2), h);
    });
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

  async function bootstrap() {
    const presets = await api("/api/presets");
    const sel = $("preset");
    sel.innerHTML = "";
    (presets.presets || []).forEach((p) => {
      const o = document.createElement("option");
      o.value = p;
      o.textContent = p;
      if (p === "sanded_core") o.selected = true;
      sel.appendChild(o);
    });

    const proj = await api("/api/project");
    if (proj.project) {
      project = proj.project;
      fillMeta();
      await loadProjectImage();
      setStatus(`${project.sample_code || "sample"} ready`);
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
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch("/api/open", { method: "POST", body: fd });
    const data = await res.json();
    project = data.project;
    fillMeta();
    await loadProjectImage();
    setStatus(`Opened ${f.name}`);
  });

  $("preset").addEventListener("change", async () => {
    if (!project) return;
    project.preprocess_preset = $("preset").value;
    await loadProjectImage();
  });

  $("btnDetect").addEventListener("click", async () => {
    if (!project) return;
    readMetaIntoProject();
    await syncProjectToServer();
    setStatus("Detecting…");
    try {
      const res = await api("/api/detect", {
        method: "POST",
        body: JSON.stringify({
          method: $("method").value,
          preset: $("preset").value,
          sample_type: $("sampleType").value,
          outer_year: project.outer_year,
          path: primaryPath().points.length >= 2 ? primaryPath().points : null,
          pith: project.pith,
        }),
      });
      project = res.project;
      fillMeta();
      redraw();
      await refreshSeries();
      const n = project.paths[0]?.rings?.length || 0;
      setStatus(`Detected ${n} rings`);
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
    if (!dragTick) return;
    const path = primaryPath();
    dragTick.ring.distance_px = distanceAlongPath(path.points, cursor.x, cursor.y);
    redraw();
  });

  canvas.addEventListener("pointerup", async () => {
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
    }
  }

  $("btnTrain").addEventListener("click", async () => {
    try {
      await api("/api/train/start", {
        method: "POST",
        body: JSON.stringify({
          name: $("trainName").value,
          epochs: parseInt($("trainEpochs").value, 10),
          imgsz: parseInt($("trainImgsz").value, 10),
          batch_size: parseInt($("trainBatch").value, 10),
          lr: parseFloat($("trainLr").value),
          device: $("trainDevice").value,
          augment: $("trainAugment").checked,
          fine_tune: $("trainFinetune").checked,
          overwrite: true,
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

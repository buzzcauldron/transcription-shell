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
  let seriesCache = null;
  let hoverFold = null; // { index, ring, widthPx, widthUm }

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

  function tangentAtDistance(points, dist) {
    if (!points || points.length < 2) return { x: 1, y: 0 };
    let acc = 0;
    for (let i = 0; i < points.length - 1; i++) {
      const a = points[i], b = points[i + 1];
      const seg = Math.hypot(b.x - a.x, b.y - a.y) || 1e-6;
      if (acc + seg >= dist) {
        const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
        return { x: (b.x - a.x) / len, y: (b.y - a.y) / len };
      }
      acc += seg;
    }
    const a = points[points.length - 2], b = points[points.length - 1];
    const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
    return { x: (b.x - a.x) / len, y: (b.y - a.y) / len };
  }

  function orderedFolds(path) {
    return [...(path.rings || [])]
      .map((r, index) => ({ r, index }))
      .filter(({ r }) => r.flag !== "false")
      .sort((a, b) => a.r.distance_px - b.r.distance_px);
  }

  function widthBetween(outer, inner) {
    const px = Math.max(0, outer.distance_px - inner.distance_px);
    const mpp = project?.scale?.micrometers_per_pixel;
    const um = mpp != null && mpp > 0 ? px * mpp : px;
    return { px, um, unit: mpp != null && mpp > 0 ? "µm" : "px" };
  }

  function redraw() {
    if (!img.naturalWidth) return;
    const wrap = $("canvasWrap") || canvas.parentElement;
    const maxW = wrap.clientWidth - 2;
    scale = Math.min(1, maxW / img.naturalWidth);
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    const path = primaryPath();
    if (!path) return;

    const folds = orderedFolds(path);
    wrap.classList.toggle("has-rings", folds.length > 0);

    // Width ribbons: thick path segments between consecutive folds
    if (folds.length >= 2 && path.points.length >= 2) {
      const total = (() => {
        let L = 0;
        for (let i = 0; i < path.points.length - 1; i++) {
          L += Math.hypot(path.points[i + 1].x - path.points[i].x, path.points[i + 1].y - path.points[i].y);
        }
        return L || 1;
      })();
      for (let i = 0; i < folds.length - 1; i++) {
        const a = folds[i].r.distance_px;
        const b = folds[i + 1].r.distance_px;
        if (b - a < 0.5) continue;
        const steps = Math.max(2, Math.ceil((b - a) / 3));
        ctx.strokeStyle = i % 2 === 0 ? "rgba(111, 191, 163, 0.42)" : "rgba(111, 191, 163, 0.2)";
        ctx.lineWidth = Math.min(16, Math.max(5, 8 * scale));
        ctx.lineCap = "butt";
        ctx.lineJoin = "round";
        ctx.beginPath();
        for (let s = 0; s <= steps; s++) {
          const d = a + ((b - a) * s) / steps;
          const pt = pointAtDistance(path.points, Math.min(d, total));
          if (!pt) continue;
          const c = imgToCanvas(pt.x, pt.y);
          if (s === 0) ctx.moveTo(c.x, c.y);
          else ctx.lineTo(c.x, c.y);
        }
        ctx.stroke();
      }
    }

    // Path hairline
    if (path.points.length) {
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "rgba(232, 239, 233, 0.92)";
      ctx.lineWidth = Math.max(1.25, 1.5 * Math.min(scale, 1.2));
      ctx.beginPath();
      path.points.forEach((p, i) => {
        const c = imgToCanvas(p.x, p.y);
        if (i === 0) ctx.moveTo(c.x, c.y);
        else ctx.lineTo(c.x, c.y);
      });
      ctx.stroke();
      path.points.forEach((p, i) => {
        const c = imgToCanvas(p.x, p.y);
        const end = i === 0 || i === path.points.length - 1;
        ctx.fillStyle = end ? "#e8efe9" : "rgba(232,239,233,0.7)";
        ctx.beginPath();
        ctx.arc(c.x, c.y, end ? 3.2 : 2.2, 0, Math.PI * 2);
        ctx.fill();
      });
    }

    // Disc fold arcs
    if (project.pith && folds.length && project.sample_type === "disc") {
      const pc = imgToCanvas(project.pith.x, project.pith.y);
      folds.forEach(({ r }, i) => {
        if (r.flag === "missing") return;
        const pt = pointAtDistance(path.points, r.distance_px);
        if (!pt) return;
        const rad = Math.hypot(pt.x - project.pith.x, pt.y - project.pith.y) * scale;
        if (rad < 4) return;
        ctx.strokeStyle = i % 5 === 0 ? "rgba(232,239,233,0.22)" : "rgba(232,239,233,0.1)";
        ctx.lineWidth = i % 5 === 0 ? 1.1 : 0.7;
        ctx.beginPath();
        ctx.arc(pc.x, pc.y, rad, 0, Math.PI * 2);
        ctx.stroke();
      });
    }

    // Pith
    if (project.pith) {
      const c = imgToCanvas(project.pith.x, project.pith.y);
      ctx.strokeStyle = "#e8efe9";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(c.x - 7, c.y);
      ctx.lineTo(c.x + 7, c.y);
      ctx.moveTo(c.x, c.y - 7);
      ctx.lineTo(c.x, c.y + 7);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(c.x, c.y, 3, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Fold ticks — perpendicular marks
    const n = folds.length;
    folds.forEach(({ r, index }, i) => {
      const pt = pointAtDistance(path.points, r.distance_px);
      if (!pt) return;
      const tan = tangentAtDistance(path.points, r.distance_px);
      const c = imgToCanvas(pt.x, pt.y);
      const nx = -tan.y, ny = tan.x;
      const conf = Math.max(0.35, Math.min(1, r.confidence ?? 1));
      const half = (5.5 + 4 * conf) * Math.max(scale, 0.65);
      let color = "rgba(224, 82, 68, 0.95)";
      if (r.flag === "missing") color = "rgba(154, 173, 163, 0.85)";
      if (r.flag === "uncertain") color = "rgba(212, 163, 92, 0.95)";
      const active = hoverFold && hoverFold.index === index;
      ctx.strokeStyle = color;
      ctx.lineWidth = active ? 2.4 : 1.65;
      ctx.beginPath();
      ctx.moveTo(c.x - nx * half, c.y - ny * half);
      ctx.lineTo(c.x + nx * half, c.y + ny * half);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(c.x, c.y, active ? 2.4 : 1.4, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();

      const showYear =
        r.year != null &&
        (i === 0 || i === n - 1 || r.year % 10 === 0 || active || r.flag === "uncertain");
      if (showYear) {
        ctx.font = `600 ${Math.max(10, 11 * Math.min(scale * 1.2, 1.15))}px "IBM Plex Mono", monospace`;
        ctx.fillStyle = "rgba(247,249,251,0.92)";
        ctx.fillText(String(r.year), c.x + nx * (half + 4) + 2, c.y + ny * (half + 4) - 2);
      }
    });

    if (hoverFold && hoverFold.width) {
      const pt = pointAtDistance(path.points, hoverFold.ring.distance_px);
      if (pt) {
        const c = imgToCanvas(pt.x, pt.y);
        const label = `${hoverFold.width.um.toFixed(hoverFold.width.unit === "µm" ? 0 : 1)} ${hoverFold.width.unit}`;
        ctx.font = '600 11px "IBM Plex Mono", monospace';
        const tw = ctx.measureText(label).width;
        ctx.fillStyle = "rgba(15, 20, 18, 0.82)";
        ctx.fillRect(c.x + 10, c.y - 22, tw + 10, 18);
        ctx.fillStyle = "#e8efe9";
        ctx.fillText(label, c.x + 15, c.y - 9);
      }
    }

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
    if (!ul) return;
    ul.innerHTML = "";
    if (!path) return;
    const folds = orderedFolds(path).reverse(); // outer → pith
    folds.forEach(({ r, index }, i) => {
      const next = folds[i + 1];
      const w = next ? widthBetween(r, next.r) : null;
      const li = document.createElement("li");
      li.className = `flag-${r.flag || "ok"}`;
      if (hoverFold && hoverFold.index === index) li.classList.add("active");
      const wTxt = w
        ? `${w.um.toFixed(w.unit === "µm" ? 0 : 1)} ${w.unit}`
        : "pith";
      li.innerHTML =
        `<span class="yr">${r.year ?? "—"}</span>` +
        `<span class="meta">${r.flag || "ok"}${r.note ? " · " + r.note : ""}</span>` +
        `<span class="w">${wTxt}</span>`;
      li.onmouseenter = () => {
        hoverFold = { index, ring: r, width: w };
        redraw();
      };
      li.onmouseleave = () => {
        if (hoverFold && hoverFold.index === index) {
          hoverFold = null;
          redraw();
        }
      };
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
    seriesCache = s;
    drawSpark(s);
    const summary = $("widthSummary");
    if (summary) {
      const vals = (s.widths_um || []).filter((v, i) => (s.flags || [])[i] !== "missing" && v > 0);
      if (!vals.length) summary.textContent = "—";
      else {
        const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
        const unit = project?.scale?.micrometers_per_pixel ? "µm" : "px";
        summary.textContent = `${vals.length} rings · mean ${mean.toFixed(0)} ${unit}`;
      }
    }
  }

  function drawSpark(s) {
    const host = spark.parentElement;
    const w = host.clientWidth - 24;
    const H = 110;
    spark.width = Math.max(320, w) * devicePixelRatio;
    spark.height = H * devicePixelRatio;
    spark.style.width = Math.max(320, w) + "px";
    sctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    sctx.clearRect(0, 0, spark.width, H);
    const vals = s.widths_um || [];
    const years = s.years || [];
    const flags = s.flags || [];
    if (!vals.length) {
      sctx.fillStyle = "#6a7a72";
      sctx.font = '500 12px "Source Sans 3", sans-serif';
      sctx.fillText("Widths appear after detect", 4, 52);
      return;
    }
    const max = Math.max(...vals.map((v, i) => ((flags[i] === "missing" || v <= 0) ? 0 : v)), 1);
    const padL = 2, padR = 2, top = 14, base = 78;
    const innerW = Math.max(320, w) - padL - padR;
    const bw = innerW / vals.length;

    // baseline
    sctx.strokeStyle = "rgba(21,32,25,0.18)";
    sctx.lineWidth = 1;
    sctx.beginPath();
    sctx.moveTo(padL, base + 0.5);
    sctx.lineTo(padL + innerW, base + 0.5);
    sctx.stroke();

    vals.forEach((v, i) => {
      const x = padL + i * bw;
      const flag = flags[i] || "ok";
      const pointer = s.skeleton && s.skeleton[i];
      if (flag === "missing" || v <= 0) {
        sctx.strokeStyle = "#6a7a72";
        sctx.beginPath();
        sctx.moveTo(x + bw * 0.25, base - 6);
        sctx.lineTo(x + bw * 0.75, base - 2);
        sctx.stroke();
        return;
      }
      const h = (v / max) * 56;
      sctx.fillStyle = pointer ? "rgba(180, 35, 24, 0.82)" : "rgba(31, 92, 69, 0.78)";
      sctx.fillRect(x + 0.8, base - h, Math.max(1.5, bw - 1.6), h);
      if (pointer) {
        sctx.strokeStyle = "#b42318";
        sctx.beginPath();
        sctx.moveTo(x + bw / 2, base + 3);
        sctx.lineTo(x + bw / 2, base + 11);
        sctx.stroke();
      }
      const y = years[i];
      if (y != null && (y % 10 === 0 || i === 0 || i === vals.length - 1)) {
        sctx.fillStyle = "#152019";
        sctx.font = '550 9px "IBM Plex Mono", monospace';
        sctx.fillText(String(y), x + 1, H - 8);
      }
    });
  }

  async function refreshTiles() {
    const rail = $("tileRail");
    if (!rail) return;
    if (!project?.paths?.[0]?.rings?.length) {
      rail.innerHTML = '<span class="mono">Detect to populate fold zooms</span>';
      return;
    }
    try {
      const res = await fetch(`/api/viz/tiles?_=${Date.now()}`);
      if (!res.ok) throw new Error("tiles failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      rail.innerHTML = "";
      const sheet = document.createElement("img");
      sheet.src = url;
      sheet.alt = "Fold zoom strip";
      rail.appendChild(sheet);
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
    setStatus(statusMsg || `${project.sample_code || "sample"} · ${n} folds · ${project.sample_type || ""}`);
  }

  async function populateMethodSelect() {
    const sel = $("method");
    if (!sel) return;
    const current = sel.value;
    let stack = null;
    try {
      const m = await api("/api/methods");
      stack = m.stack || [];
      window.__dendroDefaults = m.defaults || { core: "classical", disc: "boolean" };
    } catch (_) {
      stack = [
        { id: "classical", label: "Classical" },
        { id: "boolean", label: "Boolean bridge" },
        { id: "unet", label: "Active U-Net" },
      ];
      window.__dendroDefaults = { core: "classical", disc: "boolean" };
    }
    sel.innerHTML = "";
    const autoOpt = document.createElement("option");
    autoOpt.value = "auto";
    autoOpt.textContent = "Auto (stack default)";
    sel.appendChild(autoOpt);
    stack.forEach((entry) => {
      const o = document.createElement("option");
      o.value = entry.id;
      o.textContent = entry.label || entry.id;
      if (entry.summary) o.title = entry.summary;
      sel.appendChild(o);
    });
    if ([...sel.options].some((o) => o.value === current)) sel.value = current;
  }

  function stackDefaultForType(sampleType) {
    const defaults = window.__dendroDefaults || { core: "classical", disc: "boolean" };
    if (sampleType === "disc") return defaults.disc || "boolean";
    if (sampleType === "core") return defaults.core || "classical";
    return "auto";
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

    await populateMethodSelect();

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
    $("method").value = project.detect_method || stackDefaultForType(project.sample_type);
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

  $("sampleType").addEventListener("change", () => {
    const t = $("sampleType").value;
    // Keep Auto; otherwise snap Method to the stack default for this type
    // when the user hasn't locked in U-Net.
    if ($("method").value !== "unet" && $("method").value !== "auto") {
      $("method").value = stackDefaultForType(t === "auto" ? (project?.sample_type || "core") : t);
    }
    if (project) project.sample_type = t === "auto" ? project.sample_type : t;
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
      ctx.fillStyle = paintStroke.mode === "erase" ? "rgba(0,0,0,0.35)" : "rgba(180,35,24,0.45)";
      const c = imgToCanvas(cursor.x, cursor.y);
      ctx.beginPath();
      ctx.arc(c.x, c.y, (parseInt($("brushRadius").value, 10) || 3) * scale, 0, Math.PI * 2);
      ctx.fill();
      return;
    }
    if (dragTick) {
      const path = primaryPath();
      dragTick.ring.distance_px = distanceAlongPath(path.points, cursor.x, cursor.y);
      redraw();
      return;
    }
    // Hover fold → width callout
    const path = primaryPath();
    if (path && path.rings?.length) {
      const hit = nearestTick(cursor, 16);
      if (hit) {
        const folds = orderedFolds(path);
        const fi = folds.findIndex((f) => f.index === hit.index);
        const w = fi >= 0 && fi < folds.length - 1
          ? widthBetween(folds[fi].r, folds[fi + 1].r)
          : null;
        const same = hoverFold && hoverFold.index === hit.index;
        hoverFold = { index: hit.index, ring: hit.ring, width: w };
        if (!same) redraw();
      } else if (hoverFold) {
        hoverFold = null;
        redraw();
      }
    }
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
    setStatus("Comparing detection stack…");
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
      const stackNote = res.headers.get("X-Stack-Note");
      const blob = await res.blob();
      $("compareImg").src = URL.createObjectURL(blob);
      setStatus(stackNote ? `Stack compare (${stackNote})` : "Stack compare ready");
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

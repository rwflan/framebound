/* Standalone design preview. All review writes stay in this preview's local storage. */
(() => {
  "use strict";
  const fixture = window.FRAMEBOUND_REVIEW_FIXTURE;
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const escape = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (char) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[char],
    );
  const records = fixture.records;
  const key = "framebound.posthog-preview.v1";
  let saved = { issues: [], decisions: [] };
  try {
    const value = JSON.parse(localStorage.getItem(key));
    if (Array.isArray(value?.issues) && Array.isArray(value?.decisions))
      saved = value;
  } catch {
    /* Empty or unavailable storage. */
  }
  const state = {
    id: fixture.default_revision,
    frame: 3,
    view: "interventions",
    compare: "reference",
    zoom: 1,
    playing: false,
    speed: 1,
    tick: 12,
    openIds: [fixture.default_revision],
    evidenceScope: null,
  };
  const scroll = $("[data-film-scroll]");
  const area = $(".film-area");
  const dialog = $("[data-dialog]");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let playback = 0,
    momentum = 0,
    lastTime = 0,
    suppressClick = 0,
    toastTimer = 0;
  const record = () => records.find((item) => item.id === state.id);
  const revisionName = (item) => item.id.match(/r\d+$/)?.[0] || item.id;
  const phaseName = (phase) => phase.replaceAll("_", " ");
  const asset = (url) => `../review-desk/${url}`;
  const frameTicks = (item, index) => {
    const start = item.contract.timing.holds
      .slice(0, index)
      .reduce((a, b) => a + b, 0);
    return [start, start + item.contract.timing.holds[index] - 1];
  };
  const totalTicks = (item) =>
    item.contract.timing.holds.reduce((a, b) => a + b, 0);
  const frameChecks = (item, index) =>
    item.evaluation.results.filter((check) => check.scope === `slot ${index}`);
  const checkName = (id) =>
    ({
      "silhouette-area": "Silhouette area",
      "silhouette-width": "Silhouette width",
      "visible-torso-span": "Visible torso span",
      registration: "Registration",
      cadence: "Cadence",
    })[id] || id;
  const valueText = (check) =>
    check.observed_value == null
      ? check.outcome.replaceAll("_", " ")
      : check.units === "fraction"
        ? `${(check.observed_value * 100).toFixed(1)}%`
        : `${check.observed_value} ${check.units}`;
  const boundText = (check) =>
    check.expected_interval
      ? `${check.expected_interval.map((value) => (check.units === "fraction" ? `${Math.round(value * 100)}%` : value)).join("–")}${check.units !== "fraction" ? ` ${check.units}` : ""}`
      : check.outcome.replaceAll("_", " ");
  const acceptance = (item) =>
    [...saved.decisions]
      .reverse()
      .find(
        (decision) =>
          decision.revision_id === item.id &&
          decision.evaluation_id === item.evaluation.id &&
          decision.digest === item.evaluation.evidence_manifest_sha256,
      );
  const issues = (item, index) => {
    const [start, end] = frameTicks(item, index);
    return saved.issues.filter(
      (issue) =>
        issue.revision_id === item.id &&
        issue.evaluation_id === item.evaluation.id &&
        issue.digest === item.evaluation.evidence_manifest_sha256 &&
        issue.from <= end &&
        issue.to >= start,
    );
  };
  const verdict = (item) =>
    item.evaluation.technical_status === "fail"
      ? "Technical fail"
      : item.evaluation.technical_status === "incomplete"
        ? "Incomplete"
        : "Technical pass";
  const queueItems = () => {
    const latest = new Map();
    records.forEach((item) => latest.set(item.contract.id, item));
    return records.filter(
      (item) =>
        item.evaluation.technical_status !== "pass" ||
        saved.issues.some(
          (issue) =>
            issue.revision_id === item.id &&
            issue.evaluation_id === item.evaluation.id &&
            issue.status === "open",
        ) ||
        (latest.get(item.contract.id) === item &&
          acceptance(item)?.decision !== "approved"),
    );
  };
  function toast(message) {
    clearTimeout(toastTimer);
    $("[data-toast]").textContent = message;
    $("[data-toast]").hidden = false;
    toastTimer = setTimeout(() => {
      $("[data-toast]").hidden = true;
    }, 2800);
  }
  function persist() {
    try {
      localStorage.setItem(key, JSON.stringify(saved));
      return true;
    } catch {
      toast("Browser storage is unavailable. This review was not saved.");
      return false;
    }
  }
  function renderQueue() {
    const pending = queueItems();
    $("[data-count]").textContent = pending.length;
    $$("[data-view]").forEach((button) =>
      button.toggleAttribute("aria-current", false),
    );
    $(`[data-view="${state.view}"]`).setAttribute("aria-current", "page");
    $("[data-queue-title]").textContent = "Character animation";
    if (state.view === "timeline") {
      const events = records
        .flatMap((item) => [
          {
            item,
            date: item.revision.created_at,
            title: `${item.label} · ${revisionName(item)} created`,
            detail: "Revision",
          },
          {
            item,
            date: item.evaluation.created_at,
            title: `${item.label} · ${verdict(item).toLowerCase()}`,
            detail: "Evaluation",
          },
          {
            item,
            date: item.packet.created_at,
            title: `${item.label} · ready for review`,
            detail: "Review packet",
          },
        ])
        .concat(
          saved.decisions.map((decision) => ({
            item: records.find((item) => item.id === decision.revision_id),
            date: decision.created_at,
            title: decision.decision.replaceAll("_", " "),
            detail: "Human review",
          })),
          saved.issues.map((issue) => ({
            item: records.find((item) => item.id === issue.revision_id),
            date: issue.created_at,
            title: "Correction requested",
            detail: issue.note,
          })),
        )
        .filter((event) => event.item)
        .sort((a, b) => a.date.localeCompare(b.date));
      $("[data-queue-count]").textContent = events.length;
      let date = "";
      $("[data-queue]").innerHTML = events
        .map((event) => {
          const day = new Date(event.date).toLocaleDateString("en-GB", {
            day: "numeric",
            month: "short",
          });
          const heading =
            day !== date ? `<div class="timeline-date">${day}</div>` : "";
          date = day;
          return `${heading}<button class="queue-item event" data-revision="${escape(event.item.id)}" aria-current="${event.item.id === state.id}"><span class="dot ${event.item.evaluation.technical_status}"></span><span><strong>${escape(event.title)}</strong><small>${new Date(event.date).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })} · ${escape(event.detail)}</small></span></button>`;
        })
        .join("");
    } else {
      $("[data-queue-count]").textContent = pending.length;
      $("[data-queue]").innerHTML =
        pending
          .map((item) => {
            const count = item.evaluation.results.filter((check) =>
              ["fail", "unmeasured", "error"].includes(check.outcome),
            ).length;
            const detail =
              item.evaluation.technical_status === "fail"
                ? `${count} failed check`
                : item.evaluation.technical_status === "incomplete"
                  ? `${count} unmeasured check`
                  : item.baseline
                    ? "Replacement"
                    : "Visual review";
            const problem = item.evaluation.results.find((check) =>
              ["fail", "unmeasured", "error"].includes(check.outcome),
            );
            const slot = Number(problem?.scope.match(/\d+/)?.[0] || 0);
            return `<button class="queue-item" data-revision="${escape(item.id)}" aria-current="${item.id === state.id}"><span class="queue-thumb ${item.evaluation.technical_status}"><img src="${asset(item.frames[slot].url)}" alt="" draggable="false"></span><span><strong>${escape(item.label)}</strong><small>${detail}</small></span><span class="revision">${revisionName(item)}</span></button>`;
          })
          .join("") || '<p class="correction-empty">No pending reviews.</p>';
    }
  }
  function renderDocument() {
    const item = record();
    $("[data-tabs]").hidden = state.openIds.length < 2;
    $("[data-tabs]").innerHTML = state.openIds
      .map((id) => {
        const opened = records.find((candidate) => candidate.id === id);
        return `<button class="document-tab" data-revision="${escape(id)}" aria-current="${id === state.id}">${escape(opened.label)} · ${revisionName(opened)}</button>`;
      })
      .join("");
    $("[data-heading]").innerHTML =
      `${escape(item.label)} <span>${revisionName(item)}</span>`;
    $("[data-states]").innerHTML =
      `<span class="badge ${item.evaluation.technical_status}">${verdict(item)}</span><span class="badge coverage ${item.evaluation.coverage_status === "complete" ? "" : "incomplete"}">${item.evaluation.coverage_status === "complete" ? "Complete coverage" : "Partial coverage"}</span>`;
    $("[data-compare] option[value=baseline]").disabled = !item.baseline;
    $("[data-compare]").value = state.compare;
  }
  function metric(item, index, id, label) {
    const check = frameChecks(item, index).find(
      (check) => check.constraint_id === id,
    );
    if (!check) return "";
    return `<button class="film-metric ${check.outcome}" data-check="${index}" aria-label="${label}, frame ${index + 1}: ${escape(valueText(check))}"><span>${label}</span><strong>${escape(valueText(check))}</strong></button>`;
  }
  function renderFilm() {
    const item = record();
    const baseline = records.find(
      (candidate) => candidate.id === item.baseline,
    );
    const other =
      state.compare === "baseline" && baseline
        ? baseline.frames
        : item.references;
    $(".reference-label").textContent =
      state.compare === "baseline" ? "Previous" : "Reference";
    const cells = (candidate) =>
      item.frames
        .map((frame, index) => {
          const source = candidate ? frame : other[index];
          const frameIssues = candidate ? issues(item, index) : [];
          const missing =
            candidate &&
            frameChecks(item, index).some(
              (check) => check.outcome === "unmeasured",
            );
          return `<div class="film-unit"><button class="film-frame" data-frame="${index}" aria-label="${candidate ? "Candidate" : "Reference"} frame ${index + 1}" aria-pressed="${index === state.frame}"><img src="${asset(source.url)}" alt="${escape(phaseName(frame.phase))}" draggable="false"></button>${candidate ? `<div class="film-metrics">${metric(item, index, "silhouette-area", "Area")}${metric(item, index, "silhouette-width", "Width")}</div><div class="film-issue ${frameIssues.length || missing ? "marked" : ""}">${frameIssues.length ? `↳ ${escape(frameIssues[0].note)}` : missing ? "◌ Torso span unmeasured" : ""}</div>` : ""}</div>`;
        })
        .join("");
    $("[data-film-content]").innerHTML =
      `<div class="frame-ruler">${item.frames.map((_, index) => `<button data-frame="${index}" aria-label="Go to frame ${index + 1}" aria-pressed="${index === state.frame}">${String(index + 1).padStart(2, "0")}<small>${frameTicks(item, index).join("–")}</small></button>`).join("")}</div><div class="strip reference-strip">${cells(false)}</div><div class="strip candidate-strip">${cells(true)}</div>`;
    positionLabels();
  }
  function positionLabels() {
    const rect = area.getBoundingClientRect();
    for (const [stripName, labelName] of [
      [".reference-strip", ".reference-label"],
      [".candidate-strip", ".candidate-label"],
    ]) {
      const strip = $(stripName);
      if (!strip) continue;
      const bounds = strip.getBoundingClientRect();
      const top = bounds.top + bounds.height / 2 - rect.top;
      $(labelName).style.top =
        `${Math.max(8, Math.min(rect.height - 20, top - 7))}px`;
      $(labelName).style.visibility =
        bounds.bottom < rect.top || bounds.top > rect.bottom
          ? "hidden"
          : "visible";
    }
  }
  function renderSelection() {
    const item = record(),
      frame = item.frames[state.frame];
    const range = frameTicks(item, state.frame);
    const phase = phaseName(frame.phase);
    $$("[data-frame]").forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        Number(button.dataset.frame) === state.frame,
      ),
    );
    $("[data-frame-heading]").textContent =
      `Frame ${String(state.frame + 1).padStart(2, "0")}`;
    $("[data-native]").textContent =
      `${item.contract.canvas.width} × ${item.contract.canvas.height}`;
    $("[data-selected]").src = asset(frame.url);
    $("[data-position]").textContent =
      `${String(state.frame + 1).padStart(2, "0")} / ${String(item.frames.length).padStart(2, "0")}`;
    $("[data-phase]").textContent = phase;
    $("[data-ticks]").textContent = `${range.join("–")} ticks`;
    $("[data-status]").textContent =
      `Frame ${String(state.frame + 1).padStart(2, "0")} · ${phase} · tick ${Math.floor(state.tick)}`;
    $('[data-step="-1"]').disabled = state.frame === 0;
    $('[data-step="1"]').disabled = state.frame === item.frames.length - 1;
    const checks = frameChecks(item, state.frame).filter(
      (check) => check.constraint_id !== "registration",
    );
    $("[data-measurements]").innerHTML = checks
      .map((check) => {
        const shortName =
          {
            "silhouette-area": "Area drift",
            "silhouette-width": "Width drift",
            "visible-torso-span": "Torso span",
          }[check.constraint_id] || checkName(check.constraint_id);
        const limit = check.expected_interval?.[1];
        const ratio =
          check.units === "fraction" && check.observed_value != null;
        return `<div class="measure ${check.outcome}"><div class="measure-title"><span title="${escape(checkName(check.constraint_id))}">${escape(shortName)}</span><strong>${escape(valueText(check))}${limit != null ? `<small title="Maximum allowed">/ ${Math.round(limit * 100)}%</small>` : ""}</strong></div>${ratio ? `<div class="measure-bar" style="--value:${Math.min(100, check.observed_value * 100)}%;--limit:${limit * 100}%" aria-label="${escape(shortName)}: ${escape(valueText(check))}; maximum ${Math.round(limit * 100)}%"><i></i></div>` : `<p title="${escape(check.reason)}">${check.outcome === "unmeasured" ? "Needs annotation" : check.outcome === "not_applicable" ? "Occluded in contract" : escape(check.reason)}</p>`}</div>`;
      })
      .join("");
    $("[data-evidence]").textContent =
      `${item.evaluation.results.length} checks ↗`;
    const selectedIssues = issues(item, state.frame);
    $("[data-issue-count]").textContent = selectedIssues.length;
    $("[data-corrections]").innerHTML = selectedIssues.length
      ? selectedIssues
          .map(
            (issue) =>
              `<div class="correction-entry">${escape(issue.note)}<small>${escape(issue.category)} · ticks ${issue.from}–${issue.to}${issue.roi ? ` · region ${issue.roi.width} × ${issue.roi.height}px` : ""}</small></div>`,
          )
          .join("")
      : "";
    $("[data-regions]").innerHTML = selectedIssues
      .filter((issue) => issue.roi)
      .map((issue) => {
        const region = issue.roi,
          width = item.contract.canvas.width,
          height = item.contract.canvas.height;
        return `<span class="region-box" style="left:${(region.x / width) * 100}%;top:${(region.y / height) * 100}%;width:${(region.width / width) * 100}%;height:${(region.height / height) * 100}%"></span>`;
      })
      .join("");
    if (state.evidenceScope) renderEvidence();
    $("[data-acceptance]").textContent =
      acceptance(item)
        ?.decision.replaceAll("_", " ")
        .replace(/^./, (letter) => letter.toUpperCase()) || "Unreviewed";
  }
  function ensureVisible(smooth = true) {
    const cell = $(".candidate-strip .film-unit");
    if (!cell) return;
    const width = cell.getBoundingClientRect().width;
    const left =
      state.frame * width +
      $("[data-film-content]").offsetLeft -
      scroll.offsetLeft;
    const target = Math.max(0, left - (scroll.clientWidth - width) / 2);
    scroll.scrollTo({
      left: target,
      behavior: smooth && !reduced ? "smooth" : "instant",
    });
  }
  function selectFrame(index, center = false) {
    state.frame = Math.max(0, Math.min(record().frames.length - 1, index));
    state.tick = frameTicks(record(), state.frame)[0];
    renderSelection();
    if (center) ensureVisible();
  }
  function load(id) {
    stop();
    cancelAnimationFrame(momentum);
    state.id = id;
    if (!state.openIds.includes(id)) state.openIds.push(id);
    const item = record();
    const problem = item.evaluation.results.find((check) =>
      ["fail", "unmeasured", "error"].includes(check.outcome),
    );
    state.frame = problem ? Number(problem.scope.match(/\d+/)?.[0] || 0) : 0;
    state.tick = frameTicks(item, state.frame)[0];
    state.compare = "reference";
    renderQueue();
    renderDocument();
    renderFilm();
    renderSelection();
    ensureVisible(false);
  }
  function zoom(value, anchor = scroll.clientWidth / 2) {
    const next = Math.max(0.08, Math.min(2, Math.round(value * 100) / 100));
    const offset = (scroll.scrollLeft + anchor) / state.zoom;
    state.zoom = next;
    area.style.setProperty("--zoom", next);
    area.classList.toggle("overview", next < 0.38);
    $("[data-reset-zoom]").textContent = `${Math.round(next * 100)}%`;
    scroll.scrollLeft = offset * next - anchor;
    requestAnimationFrame(positionLabels);
  }
  function stop() {
    state.playing = false;
    cancelAnimationFrame(playback);
    lastTime = 0;
    $("[data-play]").textContent = "▶";
    $("[data-play]").setAttribute("aria-label", "Play animation");
  }
  function play() {
    if (state.playing) return stop();
    if (
      !record().contract.action.loop &&
      state.tick >= totalTicks(record()) - 1
    )
      selectFrame(0);
    state.playing = true;
    lastTime = 0;
    $("[data-play]").textContent = "Ⅱ";
    $("[data-play]").setAttribute("aria-label", "Pause animation");
    playback = requestAnimationFrame(advance);
  }
  function advance(time) {
    if (!state.playing) return;
    const item = record();
    if (lastTime)
      state.tick +=
        (Math.min(time - lastTime, 100) / 1000) *
        item.contract.timing.ticks_per_second *
        state.speed;
    lastTime = time;
    if (state.tick >= totalTicks(item)) {
      if (item.contract.action.loop) state.tick %= totalTicks(item);
      else {
        state.tick = totalTicks(item) - 1;
        stop();
      }
    }
    let sum = 0;
    const index = item.contract.timing.holds.findIndex((hold) => {
      sum += hold;
      return state.tick < sum;
    });
    if (index !== state.frame) {
      state.frame = Math.max(0, index);
      renderSelection();
      ensureVisible(false);
    }
    $("[data-status]").textContent =
      `Frame ${String(state.frame + 1).padStart(2, "0")} · ${phaseName(item.frames[state.frame].phase)} · tick ${Math.floor(state.tick)}`;
    if (state.playing) playback = requestAnimationFrame(advance);
  }
  function open(title, html) {
    stop();
    $("[data-dialog-title]").textContent = title;
    $("[data-dialog-body]").innerHTML = html;
    dialog.showModal();
  }
  function evidence(index = null) {
    stop();
    if (index != null) selectFrame(index);
    state.evidenceScope = index == null ? "all" : "frame";
    $(".inspector").hidden = true;
    $("[data-evidence-drawer]").hidden = false;
    renderEvidence();
    if (innerWidth <= 760)
      $("[data-evidence-drawer]").scrollIntoView({
        behavior: reduced ? "instant" : "smooth",
        block: "nearest",
      });
  }
  function renderEvidence() {
    const item = record();
    const checks =
      state.evidenceScope === "all"
        ? item.evaluation.results
        : frameChecks(item, state.frame);
    const rank = {
      fail: 0,
      error: 1,
      unmeasured: 2,
      not_applicable: 3,
      pass: 4,
    };
    $("[data-evidence-title]").textContent =
      state.evidenceScope === "all"
        ? `${checks.length} checks`
        : `Frame ${state.frame + 1} · checks`;
    $("[data-evidence-body]").innerHTML = `<div class="dialog-evidence">${[
      ...checks,
    ]
      .sort((a, b) => rank[a.outcome] - rank[b.outcome])
      .map(
        (check) =>
          `<div class="check ${check.outcome}"><div><strong>${escape(checkName(check.constraint_id))}</strong><br><small>${escape(check.scope.replace(/slot (\d+)/, (_, n) => `Frame ${Number(n) + 1}`))}</small></div><div class="check-value">${escape(valueText(check))}<small>${check.expected_interval ? `Limit ${escape(boundText(check))}` : escape(check.outcome.replaceAll("_", " "))}</small></div><p>${escape(check.reason)}</p></div>`,
      )
      .join(
        "",
      )}</div><details class="source-identifiers"><summary>Evaluation identifiers</summary><p>${escape(item.evaluation.id)}<br>${escape(item.evaluation.analyzer_version)}<br>Evidence SHA-256: ${escape(item.evaluation.evidence_manifest_sha256)}</p></details>`;
  }
  function closeEvidence() {
    state.evidenceScope = null;
    $("[data-evidence-drawer]").hidden = true;
    $(".inspector").hidden = false;
  }
  function nextReview(offset = 1) {
    const pending = queueItems();
    if (!pending.length) return;
    const index = pending.findIndex((item) => item.id === state.id);
    load(pending[(index + offset + pending.length) % pending.length].id);
  }
  function search() {
    open(
      "Find sequence",
      '<input class="command-search" data-command-search type="search" placeholder="Sequence or revision…" aria-label="Search sequences" autocomplete="off"><div class="search-results" data-search-results role="listbox" aria-label="Sequences"></div>',
    );
    const input = $("[data-command-search]");
    let index = 0,
      matches = [];
    const render = () => {
      const query = input.value.toLowerCase().trim();
      matches = records.filter((item) =>
        `${item.label} ${revisionName(item)} ${item.id}`
          .toLowerCase()
          .includes(query),
      );
      index = Math.max(0, Math.min(index, matches.length - 1));
      $("[data-search-results]").innerHTML =
        matches
          .map(
            (item, i) =>
              `<button class="search-result ${i === index ? "active" : ""}" data-search-revision="${escape(item.id)}" role="option" aria-selected="${i === index}"><strong>${escape(item.label)} · ${revisionName(item)}</strong><small>${verdict(item)}</small></button>`,
          )
          .join("") || '<p class="search-empty">No matching sequences.</p>';
    };
    input.oninput = () => {
      index = 0;
      render();
    };
    input.onkeydown = (event) => {
      if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        index =
          (index + (event.key === "ArrowDown" ? 1 : -1) + matches.length) %
          Math.max(1, matches.length);
        render();
        $(".search-result.active")?.scrollIntoView({ block: "nearest" });
      } else if (event.key === "Enter" && matches[index]) {
        event.preventDefault();
        dialog.close();
        load(matches[index].id);
      }
    };
    render();
    input.focus();
  }
  function decision() {
    const item = record();
    open(
      "Review decision",
      `<dl class="review-facts"><dt>Revision</dt><dd>${escape(item.label)} · ${revisionName(item)}</dd><dt>Technical</dt><dd>${verdict(item)}</dd><dt>Coverage</dt><dd>${item.evaluation.coverage_status}</dd><dt>Human review</dt><dd>${acceptance(item)?.decision.replaceAll("_", " ") || "Unreviewed"}</dd><dt>Release</dt><dd>Not eligible · ${escape(item.eligibility.reasons.join("; "))}</dd></dl><label class="decision-note">Review note<textarea data-decision-note rows="3" placeholder="Optional"></textarea></label><div class="decision-buttons"><button data-verdict="rejected">Reject</button><button data-verdict="needs_changes">Needs changes</button><button class="primary" data-verdict="approved">Approve</button></div><p class="decision-notice">Saved in this browser only.</p>`,
    );
  }
  function correction() {
    const item = record(),
      frame = item.frames[state.frame],
      [from, to] = frameTicks(item, state.frame);
    open(
      `Request correction · frame ${String(state.frame + 1).padStart(2, "0")}`,
      `<div class="correction-layout"><div><canvas class="correction-canvas" width="${item.contract.canvas.width}" height="${item.contract.canvas.height}" aria-label="Draw an optional correction region on the frame"></canvas><div class="region-info"><span data-region>Whole frame</span><button data-clear-region>Clear region</button></div></div><form class="correction-form"><label>Correction<textarea name="note" rows="4" required placeholder="What needs to change?"></textarea></label><label>Category<select name="category"><option>Shape</option><option>Timing</option><option>Motion</option><option>Identity</option><option>Style</option><option>Other</option></select></label><div class="form-grid"><label>From tick<input name="from" type="number" min="0" max="${totalTicks(item) - 1}" value="${from}" required></label><label>Through tick<input name="to" type="number" min="0" max="${totalTicks(item) - 1}" value="${to}" required></label></div><div data-form-error hidden class="dialog-error"></div><button class="primary" type="submit">Request correction</button></form></div>`,
    );
    const canvas = $(".correction-canvas"),
      ctx = canvas.getContext("2d"),
      image = new Image();
    let roi = null,
      origin = null;
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (image.complete) ctx.drawImage(image, 0, 0);
      if (roi) {
        ctx.fillStyle = "#e9572522";
        ctx.fillRect(roi.x, roi.y, roi.width, roi.height);
        ctx.strokeStyle = "#d44a12";
        ctx.lineWidth = 1;
        ctx.strokeRect(roi.x + 0.5, roi.y + 0.5, roi.width, roi.height);
      }
    };
    image.onload = draw;
    image.src = asset(frame.url);
    const point = (event) => {
      const bounds = canvas.getBoundingClientRect();
      return {
        x: Math.max(
          0,
          Math.min(
            canvas.width - 1,
            Math.floor(
              ((event.clientX - bounds.left) / bounds.width) * canvas.width,
            ),
          ),
        ),
        y: Math.max(
          0,
          Math.min(
            canvas.height - 1,
            Math.floor(
              ((event.clientY - bounds.top) / bounds.height) * canvas.height,
            ),
          ),
        ),
      };
    };
    canvas.onpointerdown = (event) => {
      origin = point(event);
      canvas.setPointerCapture(event.pointerId);
    };
    canvas.onpointermove = (event) => {
      if (!origin) return;
      const p = point(event);
      roi = {
        x: Math.min(origin.x, p.x),
        y: Math.min(origin.y, p.y),
        width: Math.abs(p.x - origin.x) + 1,
        height: Math.abs(p.y - origin.y) + 1,
      };
      draw();
      $("[data-region]").textContent =
        `${roi.width} × ${roi.height}px at ${roi.x}, ${roi.y}`;
    };
    canvas.onpointerup = () => {
      origin = null;
    };
    canvas.onpointercancel = () => {
      origin = null;
    };
    $("[data-clear-region]").onclick = () => {
      roi = null;
      draw();
      $("[data-region]").textContent = "Whole frame";
    };
    $(".correction-form").onsubmit = (event) => {
      event.preventDefault();
      const form = new FormData(event.target);
      const start = Number(form.get("from")),
        end = Number(form.get("to")),
        note = String(form.get("note")).trim();
      if (!note || start > end || start < 0 || end >= totalTicks(item)) {
        const error = $("[data-form-error]");
        error.hidden = false;
        error.textContent = "Enter a correction and a valid tick range.";
        return;
      }
      const issue = {
        id: crypto.randomUUID(),
        revision_id: item.id,
        evaluation_id: item.evaluation.id,
        digest: item.evaluation.evidence_manifest_sha256,
        packet_id: item.packet.id,
        frame_instance_id: frame.id,
        from: start,
        to: end,
        roi,
        category: String(form.get("category")),
        note,
        created_at: new Date().toISOString(),
        status: "open",
      };
      saved.issues.push(issue);
      if (!persist()) {
        saved.issues.pop();
        return;
      }
      dialog.close();
      renderQueue();
      renderFilm();
      renderSelection();
      toast("Correction requested");
    };
  }
  document.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.searchRevision) {
      dialog.close();
      load(button.dataset.searchRevision);
    } else if (button.dataset.reference) {
      const name = button.dataset.reference;
      open(
        name === "identity" ? "Identity reference" : "Style reference",
        `<div class="reference-enlarged"><img src="${asset(fixture[name])}" alt="Frozen ${name} reference"></div>`,
      );
    } else if (button.hasAttribute("data-search")) search();
    else if (button.hasAttribute("data-expand")) {
      const expanded = $(".window").classList.toggle("focus-film");
      button.setAttribute("aria-pressed", expanded);
      button.setAttribute(
        "aria-label",
        expanded ? "Restore workspace" : "Expand film workspace",
      );
      requestAnimationFrame(() => ensureVisible(false));
    } else if (button.hasAttribute("data-close-evidence")) closeEvidence();
    else if (button.hasAttribute("data-next-review")) nextReview();
    else if (button.dataset.revision) load(button.dataset.revision);
    else if (button.dataset.view) {
      state.view = button.dataset.view;
      renderQueue();
    } else if (button.hasAttribute("data-frame")) {
      stop();
      selectFrame(Number(button.dataset.frame));
    } else if (button.hasAttribute("data-check"))
      evidence(Number(button.dataset.check));
    else if (button.hasAttribute("data-step")) {
      stop();
      selectFrame(state.frame + Number(button.dataset.step), true);
    } else if (button.hasAttribute("data-play")) play();
    else if (button.hasAttribute("data-zoom"))
      zoom(state.zoom + Number(button.dataset.zoom) * 0.15);
    else if (button.hasAttribute("data-reset-zoom")) zoom(1);
    else if (button.hasAttribute("data-fit")) {
      const width = parseFloat(
        getComputedStyle(area).getPropertyValue("--cell"),
      );
      zoom((scroll.clientWidth - 36) / (width * record().frames.length));
      scroll.scrollLeft = 0;
    } else if (button.hasAttribute("data-evidence")) evidence();
    else if (button.hasAttribute("data-correction")) correction();
    else if (button.hasAttribute("data-decision")) decision();
    else if (button.hasAttribute("data-close")) dialog.close();
    else if (button.hasAttribute("data-verdict")) {
      const item = record();
      const entry = {
        id: crypto.randomUUID(),
        revision_id: item.id,
        evaluation_id: item.evaluation.id,
        digest: item.evaluation.evidence_manifest_sha256,
        packet_id: item.packet.id,
        decision: button.dataset.verdict,
        note: $("[data-decision-note]").value.trim(),
        created_at: new Date().toISOString(),
      };
      saved.decisions.push(entry);
      if (!persist()) {
        saved.decisions.pop();
        return;
      }
      dialog.close();
      renderQueue();
      renderSelection();
      toast("Review decision saved");
    } else if (button.hasAttribute("data-about"))
      open(
        "About this preview",
        '<div class="about-copy">A separate design preview inspired by <a href="https://posthog.com/" target="_blank" rel="noreferrer">PostHog</a>: desktop windows, compact controls, warm neutral surfaces and orange emphasis.<br><br>Frames and check results come from the existing procedural design fixture. Correction requests and decisions are saved only in this browser, separately from the live review desk.</div>',
      );
  });
  $("[data-compare]").onchange = (event) => {
    state.compare = event.target.value;
    renderFilm();
  };
  $("[data-speed]").onchange = (event) => {
    state.speed = Number(event.target.value);
  };
  scroll.addEventListener("scroll", positionLabels, { passive: true });
  scroll.addEventListener("keydown", (event) => {
    if (event.target !== scroll) return;
    const keys = {
      ArrowLeft: state.frame - 1,
      ArrowRight: state.frame + 1,
      Home: 0,
      End: record().frames.length - 1,
    };
    if (event.code === "Space") {
      event.preventDefault();
      play();
    } else if (event.key in keys) {
      event.preventDefault();
      stop();
      selectFrame(keys[event.key], true);
    }
  });
  let drag = null;
  scroll.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    cancelAnimationFrame(momentum);
    drag = {
      x: event.clientX,
      y: event.clientY,
      left: scroll.scrollLeft,
      lastX: event.clientX,
      time: performance.now(),
      velocity: 0,
      active: false,
    };
  });
  scroll.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.x,
      dy = event.clientY - drag.y;
    if (!drag.active && Math.abs(dx) > 6 && Math.abs(dx) > Math.abs(dy)) {
      drag.active = true;
      scroll.setPointerCapture(event.pointerId);
      scroll.classList.add("dragging");
    }
    if (!drag.active) return;
    event.preventDefault();
    scroll.scrollLeft = drag.left - dx;
    const now = performance.now();
    drag.velocity =
      ((drag.lastX - event.clientX) / Math.max(1, now - drag.time)) * 16;
    drag.lastX = event.clientX;
    drag.time = now;
  });
  function endDrag(event) {
    if (!drag) return;
    if (drag.active) {
      suppressClick = performance.now() + 350;
      scroll.classList.remove("dragging");
      let velocity = performance.now() - drag.time < 90 ? drag.velocity : 0;
      const coast = () => {
        const before = scroll.scrollLeft;
        scroll.scrollLeft += velocity;
        velocity *= 0.91;
        if (Math.abs(velocity) > 0.3 && scroll.scrollLeft !== before)
          momentum = requestAnimationFrame(coast);
      };
      if (!reduced && event.type !== "pointercancel") coast();
    }
    drag = null;
  }
  scroll.addEventListener("pointerup", endDrag);
  scroll.addEventListener("pointercancel", endDrag);
  scroll.addEventListener(
    "click",
    (event) => {
      if (performance.now() < suppressClick) {
        event.stopImmediatePropagation();
        event.preventDefault();
      }
    },
    true,
  );
  scroll.addEventListener(
    "wheel",
    (event) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        zoom(
          state.zoom + (event.deltaY < 0 ? 0.08 : -0.08),
          event.clientX - scroll.getBoundingClientRect().left,
        );
      }
    },
    { passive: false },
  );
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (dialog.open) dialog.close();
      search();
      return;
    }
    if (
      dialog.open ||
      event.target.closest("input,textarea,select") ||
      event.metaKey ||
      event.ctrlKey ||
      event.altKey
    )
      return;
    if (
      !event.defaultPrevented &&
      ["ArrowLeft", "ArrowRight"].includes(event.key)
    ) {
      event.preventDefault();
      stop();
      selectFrame(state.frame + (event.key === "ArrowRight" ? 1 : -1), true);
    }
    if (
      !event.defaultPrevented &&
      event.code === "Space" &&
      event.target === document.body
    ) {
      event.preventDefault();
      play();
    }
    if (event.key.toLowerCase() === "j") {
      event.preventDefault();
      nextReview();
    }
    if (event.key.toLowerCase() === "k") {
      event.preventDefault();
      nextReview(-1);
    }
    if (event.key === "Escape" && state.evidenceScope) {
      event.preventDefault();
      closeEvidence();
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
  });
  new ResizeObserver(positionLabels).observe(area);
  load(state.id);
})();

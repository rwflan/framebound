// Presentation-only camera shared by film lanes; authored timing is immutable.
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
export class ReelCamera {
  constructor(viewport, track, onPosition) {
    this.viewport = viewport;
    this.track = track;
    this.onPosition = onPosition;
    this.x = 0;
    this.y = 0;
    this.zoom = 1;
    this.targetZoom = 1;
    this.target = 0;
    this.targetY = 0;
    this.velocity = 0;
    this.velocityY = 0;
    this.raf = 0;
    this.zoomRaf = 0;
    this.drag = null;
    this.pinch = null;
    this.wheelPan = null;
    this.wheelTimer = 0;
    this.pointers = new Map();
    this.suppressUntil = 0;
    this.abort = new AbortController();
    const options = { signal: this.abort.signal };
    viewport.addEventListener("pointerdown", (e) => this.down(e), options);
    viewport.addEventListener("pointermove", (e) => this.move(e), options);
    viewport.addEventListener("pointerup", (e) => this.up(e), options);
    viewport.addEventListener(
      "pointercancel",
      (e) => this.up(e, true),
      options,
    );
    viewport.addEventListener("wheel", (e) => this.wheel(e), {
      ...options,
      passive: false,
    });
    viewport.addEventListener(
      "click",
      (e) => {
        if (performance.now() < this.suppressUntil) {
          e.preventDefault();
          e.stopImmediatePropagation();
        }
      },
      { ...options, capture: true },
    );
    viewport.addEventListener("dragstart", (e) => e.preventDefault(), options);
    this.resize = new ResizeObserver(() => {
      const width = this.width,
        height = this.height,
        trackWidth = this.trackWidth,
        trackHeight = this.trackHeight;
      this.measure();
      if (
        width !== this.width ||
        height !== this.height ||
        trackWidth !== this.trackWidth
      ) {
        this.jump(this.x, this.y);
        this.onResize?.();
      } else if (trackHeight !== this.trackHeight) {
        // New correction notes may grow the paper track without moving the viewed frame.
        this.y = this.clampY(this.y);
        this.paint();
      }
    });
    this.resize.observe(viewport);
    this.resize.observe(track);
    this.measure();
  }
  measure() {
    this.width = this.viewport.clientWidth;
    this.height = this.viewport.clientHeight;
    this.trackWidth = this.track.offsetWidth;
    this.trackHeight = this.track.offsetHeight;
    this.lanes = [
      ...this.track.querySelectorAll(".reel-lane, .measurement-track"),
    ].map((row) => ({
      top:
        row.offsetTop + (row.querySelector(".reel-shot-row")?.offsetTop || 0),
      height:
        row.querySelector(".frame-aperture")?.offsetHeight || row.offsetHeight,
    }));
    this.labels = [...this.viewport.querySelectorAll(".reel-lane-label")];
    this.bounds();
  }
  bounds() {
    const width = this.trackWidth * this.zoom,
      height = this.trackHeight * this.zoom;
    if (this.centerEdges) {
      const cell =
        this.track.querySelector(".reel-frame-unit")?.offsetWidth ||
        this.trackWidth;
      this.max = this.width / 2 - (cell * this.zoom) / 2;
      this.min = this.width / 2 - width + (cell * this.zoom) / 2;
    } else if (width <= this.width - 48)
      this.min = this.max = (this.width - width) / 2;
    else {
      this.max = 24;
      this.min = this.width - width - 24;
    }
    if (height <= this.height - 24) this.minY = this.maxY = 0;
    else {
      this.maxY = (height - this.height) / 2 + 12;
      this.minY = -this.maxY;
    }
  }
  clamp(x) {
    return Math.max(this.min, Math.min(this.max, x));
  }
  clampY(y) {
    return Math.max(this.minY, Math.min(this.maxY, y));
  }
  panBounds() {
    const width = this.trackWidth * this.zoom;
    const center = (this.width - width) / 2;
    return {
      min: width <= this.width - 48 ? center : this.width - width - 24,
      max: width <= this.width - 48 ? center : 24,
      minY: this.minY,
      maxY: this.maxY,
    };
  }
  panOrigin() {
    const limits = this.panBounds();
    // A selected end frame may initially be centred. Beginning a gesture must not jump.
    return {
      min: Math.min(limits.min, this.x),
      max: Math.max(limits.max, this.x),
      minY: Math.min(limits.minY, this.y),
      maxY: Math.max(limits.maxY, this.y),
    };
  }
  rubber(
    x,
    min = this.min,
    max = this.max,
    reach = Math.max(240, this.width * 0.85),
  ) {
    return x > max
      ? max + reach * (1 - Math.exp(-(x - max) / reach))
      : x < min
        ? min - reach * (1 - Math.exp(-(min - x) / reach))
        : x;
  }
  paint() {
    this.viewport.style?.setProperty("--film-scale", this.zoom);
    this.track.style.transform = `translate3d(${this.x.toFixed(3)}px,${this.y.toFixed(3)}px,0) scale(${this.zoom.toFixed(5)})`;
    const centers = this.lanes.map(
      (row, index) =>
        this.height / 2 +
        this.y +
        (row.top - this.trackHeight / 2) * this.zoom +
        (index === 2 ? -10 : row.height * this.zoom >= 80 ? 14 : 0),
    );
    if (centers.some((center, i) => i > 0 && center - centers[i - 1] < 28)) {
      const middle = (centers[0] + centers[centers.length - 1]) / 2;
      centers.forEach((_, i) => {
        centers[i] = middle + (i - (centers.length - 1) / 2) * 28;
      });
    }
    this.labels.forEach((node, i) => {
      const row = this.lanes[i];
      if (!row) return;
      const top =
          this.height / 2 +
          this.y +
          (row.top - this.trackHeight / 2) * this.zoom,
        height = row.height * this.zoom;
      node.style.visibility =
        top + height < 12 || top > this.height - 12 ? "hidden" : "visible";
      // Row names belong to the viewport, independently of the film's pan and zoom.
      node.style.left = "0px";
      node.style.top = top + "px";
      node.style.height = height + "px";
      node.style.setProperty(
        "--label-y",
        Math.max(18, Math.min(this.height - 18, centers[i])) - top + "px",
      );
    });
    this.onPosition(
      this.max === this.min ? 0 : (this.max - this.x) / (this.max - this.min),
      this.zoom,
    );
  }
  stopMotion() {
    cancelAnimationFrame(this.raf);
    cancelAnimationFrame(this.zoomRaf);
    this.raf = this.zoomRaf = 0;
    this.velocity = this.velocityY = 0;
  }
  stop() {
    this.stopMotion();
    clearTimeout(this.wheelTimer);
    this.wheelTimer = 0;
    this.wheelPan = null;
  }
  jump(x, y = this.y) {
    this.stop();
    this.x = this.target = this.clamp(x);
    this.y = this.targetY = this.clampY(y);
    this.paint();
  }
  go(x, velocity = this.velocity, y = this.y, velocityY = this.velocityY) {
    this.stop();
    this.springTo(this.clamp(x), velocity, this.clampY(y), velocityY);
  }
  springTo(x, velocity, y, velocityY) {
    this.stopMotion();
    this.target = x;
    this.targetY = y;
    if (reduced.matches) {
      this.x = x;
      this.y = y;
      this.paint();
      return;
    }
    this.velocity = velocity;
    this.velocityY = velocityY;
    let previous = performance.now();
    const tick = (now) => {
      const dt = Math.min(0.032, Math.max(0.001, (now - previous) / 1000));
      previous = now;
      this.velocity += ((this.target - this.x) * 190 - this.velocity * 28) * dt;
      this.velocityY +=
        ((this.targetY - this.y) * 190 - this.velocityY * 28) * dt;
      this.x += this.velocity * dt;
      this.y += this.velocityY * dt;
      if (
        Math.abs(this.target - this.x) < 0.12 &&
        Math.abs(this.targetY - this.y) < 0.12 &&
        Math.abs(this.velocity) < 0.6 &&
        Math.abs(this.velocityY) < 0.6
      ) {
        this.x = this.target;
        this.y = this.targetY;
        this.paint();
        this.raf = 0;
        return;
      }
      this.paint();
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }
  settlePan(x = this.x, velocity = 0, y = this.y, velocityY = 0) {
    const limits = this.panBounds();
    const outsideX = this.x < limits.min || this.x > limits.max;
    const outsideY = this.y < limits.minY || this.y > limits.maxY;
    this.springTo(
      Math.max(limits.min, Math.min(limits.max, x)),
      outsideX ? 0 : velocity,
      Math.max(limits.minY, Math.min(limits.maxY, y)),
      outsideY ? 0 : velocityY,
    );
  }
  zoomTo(
    value,
    px = this.width / 2,
    py = this.height / 2,
    direct = false,
    centered = false,
  ) {
    const target = Math.max(0.05, Math.min(2, value)),
      start = this.zoom,
      worldX = (px - this.x) / start,
      worldY = (py - this.height / 2 - this.y) / start;
    this.stop();
    this.targetZoom = target;
    const began = performance.now();
    const apply = (z) => {
      this.zoom = z;
      this.bounds();
      this.x = this.clamp(
        centered ? (this.width - this.trackWidth * z) / 2 : px - worldX * z,
      );
      this.y = centered ? 0 : this.clampY(py - this.height / 2 - worldY * z);
      this.paint();
    };
    if (direct || reduced.matches) {
      apply(target);
      return;
    }
    const tick = (now) => {
      const t = Math.min(1, (now - began) / 240),
        ease = 1 - Math.pow(1 - t, 3);
      apply(start + (target - start) * ease);
      if (t < 1) this.zoomRaf = requestAnimationFrame(tick);
      else this.zoomRaf = 0;
    };
    this.zoomRaf = requestAnimationFrame(tick);
  }
  fit() {
    this.zoomTo(
      Math.min(
        (this.width - 48) / this.trackWidth,
        (this.height - 24) / this.trackHeight,
        1,
      ),
      this.width / 2,
      this.height / 2,
      false,
      true,
    );
  }
  local(e) {
    const box = this.viewport.getBoundingClientRect();
    return { x: e.clientX - box.left, y: e.clientY - box.top };
  }
  down(e) {
    // Drawing is owned by the native-coordinate annotation surface, never the camera.
    if (e.target?.closest?.('[data-annotation-active="true"]')) {
      this.stop();this.suppressUntil=0;return;
    }
    if (e.button !== 0 || e.target.closest("input,select,textarea")) return;
    this.stop();
    this.suppressUntil = 0;
    if (e.pointerType === "touch") {
      this.pointers.set(e.pointerId, this.local(e));
      if (this.pointers.size > 2) return;
      if (this.pointers.size === 2) {
        const [a, b] = [...this.pointers.values()],
          x = (a.x + b.x) / 2,
          y = (a.y + b.y) / 2;
        this.pinch = {
          distance: Math.max(1, Math.hypot(b.x - a.x, b.y - a.y)),
          zoom: this.zoom,
          worldX: (x - this.x) / this.zoom,
          worldY: (y - this.height / 2 - this.y) / this.zoom,
        };
        this.drag = null;
        for (const id of this.pointers.keys())
          this.viewport.setPointerCapture(id);
        return;
      }
    }
    this.drag = {
      id: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      x: this.x,
      y: this.y,
      lastX: e.clientX,
      lastY: e.clientY,
      lastTime: performance.now(),
      speed: 0,
      speedY: 0,
      moved: false,
      limits: this.panOrigin(),
    };
  }
  move(e) {
    if (this.pointers.has(e.pointerId))
      this.pointers.set(e.pointerId, this.local(e));
    if (this.pinch && this.pointers.size === 2) {
      e.preventDefault();
      const [a, b] = [...this.pointers.values()],
        p = this.pinch,
        x = (a.x + b.x) / 2,
        y = (a.y + b.y) / 2;
      this.zoom = Math.max(
        0.05,
        Math.min(2, (p.zoom * Math.hypot(b.x - a.x, b.y - a.y)) / p.distance),
      );
      this.targetZoom = this.zoom;
      this.bounds();
      this.x = this.clamp(x - p.worldX * this.zoom);
      this.y = this.clampY(y - this.height / 2 - p.worldY * this.zoom);
      this.paint();
      return;
    }
    const d = this.drag;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.startX,
      dy = e.clientY - d.startY,
      vertical = this.minY !== this.maxY;
    if (!d.moved) {
      if (
        Math.hypot(dx, vertical ? dy : 0) < 7 ||
        (!vertical && Math.abs(dx) < Math.abs(dy) * 0.8)
      )
        return;
      d.moved = true;
      this.viewport.setPointerCapture(e.pointerId);
      this.viewport.classList.add("is-dragging");
    }
    e.preventDefault();
    const now = performance.now(),
      dt = Math.max(1, now - d.lastTime);
    d.speed = d.speed * 0.6 + ((e.clientX - d.lastX) / dt) * 0.4;
    d.speedY = d.speedY * 0.6 + ((e.clientY - d.lastY) / dt) * 0.4;
    d.lastX = e.clientX;
    d.lastY = e.clientY;
    d.lastTime = now;
    this.x = this.rubber(d.x + dx, d.limits.min, d.limits.max);
    this.y = vertical
      ? this.rubber(
          d.y + dy,
          d.limits.minY,
          d.limits.maxY,
          Math.max(160, this.height * 0.75),
        )
      : 0;
    this.paint();
  }
  up(e, cancelled = false) {
    this.pointers.delete(e.pointerId);
    if (this.viewport.hasPointerCapture(e.pointerId))
      this.viewport.releasePointerCapture(e.pointerId);
    if (this.pinch) {
      if (this.pointers.size < 2) {
        this.pinch = null;
        this.viewport.classList.remove("is-dragging");
        this.suppressUntil = performance.now() + 320;
        this.go(this.x, 0, this.y, 0);
      }
      if (this.viewport.hasPointerCapture(e.pointerId))
        this.viewport.releasePointerCapture(e.pointerId);
      return;
    }
    const d = this.drag;
    if (!d || d.id !== e.pointerId) return;
    this.drag = null;
    this.viewport.classList.remove("is-dragging");
    if (this.viewport.hasPointerCapture(e.pointerId))
      this.viewport.releasePointerCapture(e.pointerId);
    if (d.moved) {
      const stale = cancelled || performance.now() - d.lastTime > 90,
        sx = stale ? 0 : Math.max(-3.2, Math.min(3.2, d.speed)),
        sy = stale ? 0 : Math.max(-3.2, Math.min(3.2, d.speedY));
      this.suppressUntil = performance.now() + 320;
      this.settlePan(
        this.x + (reduced.matches ? 0 : sx * 170),
        sx * 180,
        this.y + (reduced.matches ? 0 : sy * 170),
        sy * 180,
      );
    } else if (this.x !== this.clamp(this.x) || this.y !== this.clampY(this.y))
      this.go(this.x, 0, this.y, 0);
  }
  wheel(e) {
    if (e.target?.closest?.('[data-annotation-drawing="true"]')) {e.preventDefault();return;}
    e.preventDefault();
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? this.width : 1;
    if (e.ctrlKey || e.metaKey) {
      const p = this.local(e);
      this.zoomTo(this.zoom * Math.exp(-e.deltaY * 0.008), p.x, p.y, true);
      return;
    }
    if (this.drag || this.pinch) return;
    if (!this.wheelPan) {
      this.stop();
      this.wheelPan = { x: this.x, y: this.y, limits: this.panOrigin() };
    }
    const pan = this.wheelPan;
    if (this.minY !== this.maxY && !e.shiftKey) {
      pan.x -= e.deltaX * unit;
      pan.y -= e.deltaY * unit;
    } else {
      pan.x -=
        (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) * unit;
    }
    this.springTo(
      this.rubber(pan.x, pan.limits.min, pan.limits.max),
      this.velocity,
      this.rubber(
        pan.y,
        pan.limits.minY,
        pan.limits.maxY,
        Math.max(160, this.height * 0.75),
      ),
      this.velocityY,
    );
    clearTimeout(this.wheelTimer);
    this.wheelTimer = setTimeout(() => {
      this.wheelTimer = 0;
      this.wheelPan = null;
      this.settlePan(this.target, this.velocity, this.targetY, this.velocityY);
    }, 140);
  }
  reveal(index, width, force = false) {
    const size = width * this.zoom,
      left = this.x + index * size,
      right = left + size;
    if (force || left < 36 || right > this.width - 36)
      this.go(this.width / 2 - (index + 0.5) * size);
  }
  destroy() {
    this.stop();
    this.abort.abort();
    this.resize.disconnect();
  }
}

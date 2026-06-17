// Chugh Vibes — interactions: form (double opt-in), reveal, cursor-lens field,
// glow, magnetic buttons, count-up, selection funnel. Vanilla, no libs.

const API = "https://fn-ai-scout-fb.azurewebsites.net/api/subscribe";
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const REDUCE = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const css = getComputedStyle(document.documentElement);
const ACCENT = (css.getPropertyValue("--accent") || "#2438e0").trim();
const INK = (css.getPropertyValue("--ink") || "#1a1712").trim();

/* ---------------- subscribe form ---------------- */
function wireForm(form) {
  const note = form.querySelector(".form-note");
  const btn = form.querySelector("button");
  const defaultNote = note.textContent;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = form.email.value.trim();
    const name = (form.name?.value || "").trim();
    const trap = form.company?.value || "";

    note.className = "form-note";
    if (!EMAIL_RE.test(email)) {
      note.textContent = "That email doesn't look right — mind checking it?";
      note.classList.add("err");
      form.email.focus();
      return;
    }

    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = "Sending…";
    try {
      const res = await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, name, company: trap }),
      });
      if (res.ok) {
        form.reset();
        note.textContent = "Almost there — check your inbox and confirm to start.";
        note.classList.add("ok");
      } else {
        const data = await res.json().catch(() => ({}));
        note.textContent = data.message || "Something hiccuped. Try again in a moment.";
        note.classList.add("err");
      }
    } catch {
      note.textContent = "Couldn't reach the server. Try again in a moment.";
      note.classList.add("err");
    } finally {
      btn.disabled = false;
      btn.textContent = label;
      if (!note.classList.contains("ok")) {
        setTimeout(() => {
          if (note.classList.contains("err")) { note.className = "form-note"; note.textContent = defaultNote; }
        }, 6000);
      }
    }
  });
}
document.querySelectorAll("form.join").forEach(wireForm);

/* ---------------- scroll reveal ---------------- */
const revealIO = new IntersectionObserver(
  (es) => es.forEach((en) => { if (en.isIntersecting) { en.target.classList.add("in"); revealIO.unobserve(en.target); } }),
  { threshold: 0.15 }
);
document.querySelectorAll(".reveal").forEach((el) => revealIO.observe(el));

/* ---------------- cursor glow ---------------- */
const glow = document.getElementById("glow");
if (glow && !REDUCE) {
  let gx = innerWidth / 2, gy = innerHeight / 2, tx = gx, ty = gy, shown = false;
  addEventListener("pointermove", (e) => {
    tx = e.clientX; ty = e.clientY;
    if (!shown) { glow.style.opacity = "1"; shown = true; }
  }, { passive: true });
  (function loop() {
    gx += (tx - gx) * 0.16; gy += (ty - gy) * 0.16;
    glow.style.transform = `translate(${gx}px, ${gy}px)`;
    requestAnimationFrame(loop);
  })();
}

/* ---------------- magnetic buttons ---------------- */
if (!REDUCE) {
  document.querySelectorAll("[data-magnetic]").forEach((btn) => {
    btn.addEventListener("pointermove", (e) => {
      const r = btn.getBoundingClientRect();
      const mx = e.clientX - (r.left + r.width / 2);
      const my = e.clientY - (r.top + r.height / 2);
      btn.style.transform = `translate(${mx * 0.22}px, ${my * 0.32}px)`;
    });
    btn.addEventListener("pointerleave", () => { btn.style.transform = ""; });
  });
}

/* ---------------- hero: signal-in-the-noise field ---------------- */
(function field() {
  const c = document.getElementById("field");
  if (!c) return;
  const ctx = c.getContext("2d");
  let w = 0, h = 0, dpr = 1, parts = [];
  const mouse = { x: -9999, y: -9999 };
  const R = 165;       // lens radius
  const LINK = 78;     // link distance among lit particles

  function resize() {
    dpr = Math.min(devicePixelRatio || 1, 2);
    const r = c.getBoundingClientRect();
    w = r.width; h = r.height;
    c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = Math.max(40, Math.min(170, Math.floor((w * h) / 8200)));
    parts = Array.from({ length: n }, () => ({
      x: Math.random() * w, y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.22, vy: (Math.random() - 0.5) * 0.22,
    }));
  }
  addEventListener("pointermove", (e) => {
    const r = c.getBoundingClientRect();
    mouse.x = e.clientX - r.left; mouse.y = e.clientY - r.top;
  }, { passive: true });
  addEventListener("pointerleave", () => { mouse.x = mouse.y = -9999; });
  addEventListener("resize", resize);
  resize();

  function frame() {
    ctx.clearRect(0, 0, w, h);
    const lit = [];
    for (const p of parts) {
      p.x += p.vx; p.y += p.vy;
      if (p.x < -10) p.x = w + 10; else if (p.x > w + 10) p.x = -10;
      if (p.y < -10) p.y = h + 10; else if (p.y > h + 10) p.y = -10;
      const d = Math.hypot(p.x - mouse.x, p.y - mouse.y);
      if (d < R) {
        const t = 1 - d / R;
        lit.push(p);
        ctx.globalAlpha = 0.25 + 0.65 * t;
        ctx.fillStyle = ACCENT;
        ctx.beginPath(); ctx.arc(p.x, p.y, 1.3 + 2.1 * t, 0, 6.2832); ctx.fill();
      } else {
        ctx.globalAlpha = 0.1;
        ctx.fillStyle = INK;
        ctx.beginPath(); ctx.arc(p.x, p.y, 1.1, 0, 6.2832); ctx.fill();
      }
    }
    ctx.strokeStyle = ACCENT; ctx.lineWidth = 1;
    for (let i = 0; i < lit.length; i++) {
      for (let j = i + 1; j < lit.length; j++) {
        const dd = Math.hypot(lit[i].x - lit[j].x, lit[i].y - lit[j].y);
        if (dd < LINK) {
          ctx.globalAlpha = 0.2 * (1 - dd / LINK);
          ctx.beginPath(); ctx.moveTo(lit[i].x, lit[i].y); ctx.lineTo(lit[j].x, lit[j].y); ctx.stroke();
        }
      }
    }
    ctx.globalAlpha = 1;
    if (!REDUCE) requestAnimationFrame(frame);
  }
  frame();
})();

/* ---------------- count-up ---------------- */
function countUp(el) {
  const target = +el.dataset.count, suf = el.dataset.suffix || "";
  if (REDUCE) { el.textContent = target + suf; return; }
  let start = null;
  function step(ts) {
    if (!start) start = ts;
    const p = Math.min((ts - start) / 1200, 1);
    const v = Math.round(target * (1 - Math.pow(1 - p, 3)));
    el.textContent = v + (p === 1 ? suf : "");
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

/* ---------------- selection funnel ---------------- */
function funnel(canvas) {
  const ctx = canvas.getContext("2d");
  let w, h, dpr, drops = [], raf = 0, tick = 0;
  function resize() {
    dpr = Math.min(devicePixelRatio || 1, 2);
    const r = canvas.getBoundingClientRect();
    w = r.width; h = r.height;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize(); addEventListener("resize", resize);

  const neckY = () => h * 0.62, neckHalf = () => Math.max(10, w * 0.04);
  function wallX(y, side) {
    const top = 0, ny = neckY();
    if (y <= ny) {
      const f = y / ny;
      const half = (w * 0.42) * (1 - f) + neckHalf();
      return w / 2 + side * half;
    }
    return w / 2 + side * neckHalf();
  }
  function spawn() {
    const keep = Math.random() < 0.06;
    drops.push({ x: w / 2 + (Math.random() - 0.5) * w * 0.8, y: -6, v: 0.8 + Math.random() * 0.7, keep, a: 1 });
  }
  function frame() {
    ctx.clearRect(0, 0, w, h);
    // walls
    ctx.strokeStyle = "rgba(26,23,18,0.28)"; ctx.lineWidth = 1.5;
    for (const side of [-1, 1]) {
      ctx.beginPath();
      ctx.moveTo(wallX(0, side), 0);
      ctx.lineTo(wallX(neckY(), side), neckY());
      ctx.lineTo(wallX(h, side), h);
      ctx.stroke();
    }
    if (!REDUCE) { if (tick % 3 === 0) spawn(); tick++; }
    const ny = neckY();
    for (const d of drops) {
      d.y += d.v;
      const lim = wallX(d.y, 1);
      // channel toward center as it descends
      const targetHalf = lim - w / 2;
      d.x = w / 2 + Math.max(-targetHalf, Math.min(targetHalf, d.x - w / 2)) * 0.985 + (Math.random() - 0.5) * 0.3;
      // at the neck, non-keepers get filtered (fade)
      if (d.y > ny - 14 && d.y < ny + 14 && !d.keep) d.a -= 0.12;
      const passed = d.y > ny;
      ctx.globalAlpha = Math.max(0, d.a) * (passed && d.keep ? 1 : 0.5);
      ctx.fillStyle = passed && d.keep ? ACCENT : INK;
      ctx.beginPath(); ctx.arc(d.x, d.y, passed && d.keep ? 3 : 1.6, 0, 6.2832); ctx.fill();
    }
    ctx.globalAlpha = 1;
    drops = drops.filter((d) => d.y < h + 8 && d.a > 0.02);
    if (!REDUCE) raf = requestAnimationFrame(frame);
  }
  if (REDUCE) { frame(); } else { raf = requestAnimationFrame(frame); }
}

/* ---------------- trigger funnel + counts on view ---------------- */
const fSec = document.querySelector(".funnel");
if (fSec) {
  const once = new IntersectionObserver((es) => {
    es.forEach((en) => {
      if (!en.isIntersecting) return;
      once.disconnect();
      fSec.querySelectorAll("[data-count]").forEach(countUp);
      const fc = document.getElementById("funnel");
      if (fc) funnel(fc);
    });
  }, { threshold: 0.4 });
  once.observe(fSec);
}

/* ---------------- problem: noise wall ---------------- */
function noiseWall(c) {
  const ctx = c.getContext("2d");
  let w, h, dpr, cells = [], t = 0;
  const mouse = { x: -9999, y: -9999 };
  function resize() {
    dpr = Math.min(devicePixelRatio || 1, 2);
    const r = c.getBoundingClientRect();
    w = r.width; h = r.height;
    c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    build();
  }
  function build() {
    const gap = Math.max(16, Math.min(26, w / 36));
    const cols = Math.max(1, Math.floor(w / gap)), rows = Math.max(1, Math.floor(h / gap));
    const ox = (w - (cols - 1) * gap) / 2, oy = (h - (rows - 1) * gap) / 2;
    const total = cols * rows, sig = new Set();
    while (sig.size < Math.min(5, total)) sig.add((Math.random() * total) | 0);
    cells = [];
    let i = 0;
    for (let yy = 0; yy < rows; yy++) for (let xx = 0; xx < cols; xx++) {
      cells.push({ x: ox + xx * gap, y: oy + yy * gap, sig: sig.has(i), ph: Math.random() * 6.28 });
      i++;
    }
  }
  addEventListener("pointermove", (e) => {
    const r = c.getBoundingClientRect();
    mouse.x = e.clientX - r.left; mouse.y = e.clientY - r.top;
  }, { passive: true });
  addEventListener("resize", resize);
  resize();
  function frame() {
    ctx.clearRect(0, 0, w, h);
    t += 0.02;
    for (const cell of cells) {
      const d = Math.hypot(cell.x - mouse.x, cell.y - mouse.y);
      const near = d < 130 ? 1 - d / 130 : 0;
      if (cell.sig) {
        const pulse = 0.6 + 0.4 * Math.sin(t * 2 + cell.ph);
        ctx.globalAlpha = Math.min(1, 0.55 * pulse + near * 0.4);
        ctx.fillStyle = ACCENT;
        ctx.beginPath(); ctx.arc(cell.x, cell.y, 2.6 + 1.1 * pulse + near * 2, 0, 6.2832); ctx.fill();
      } else {
        ctx.globalAlpha = 0.1 + near * 0.5;
        ctx.fillStyle = near > 0.35 ? ACCENT : INK;
        ctx.beginPath(); ctx.arc(cell.x, cell.y, 1.3 + near * 1.6, 0, 6.2832); ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
    if (!REDUCE) requestAnimationFrame(frame);
  }
  frame();
}
const nSec = document.querySelector(".noise");
if (nSec) {
  const o = new IntersectionObserver((es) => {
    es.forEach((en) => {
      if (!en.isIntersecting) return;
      o.disconnect();
      const nc = document.getElementById("noise");
      if (nc) noiseWall(nc);
    });
  }, { threshold: 0.2 });
  o.observe(nSec);
}

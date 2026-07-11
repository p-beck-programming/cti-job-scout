/* Threat-map constellation background, shared by all pages.
 *
 * Draws a slowly drifting network of glowing nodes + proximity links on a
 * full-viewport canvas behind the content (reads as an adversary-
 * infrastructure graph). Honors prefers-reduced-motion by rendering a
 * single static frame, and pauses while the tab is hidden.
 */
(function () {
  const canvas = document.createElement('canvas');
  canvas.id = 'bg-net';
  canvas.setAttribute('aria-hidden', 'true');
  canvas.style.cssText =
    'position:fixed;inset:0;width:100%;height:100%;z-index:-1;display:block';
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d');

  const reduceMotion =
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let W, H, nodes = [], raf = null;
  const LINK_DIST = 150;        // px within which two nodes link up
  const SPEED = 0.16;           // px per frame — a slow drift
  const DENSITY = 1 / 16000;    // nodes per px^2 (≈ 60 on a laptop screen)

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    seed();
    if (reduceMotion) draw();
  }

  function seed() {
    const n = Math.max(30, Math.min(110, Math.round(W * H * DENSITY)));
    nodes = Array.from({ length: n }, () => ({
      x: Math.random() * W,
      y: Math.random() * H,
      vx: (Math.random() - 0.5) * SPEED * 2,
      vy: (Math.random() - 0.5) * SPEED * 2,
      r: 1 + Math.random() * 1.6,
      tw: Math.random() * Math.PI * 2,   // twinkle phase
    }));
  }

  function step() {
    for (const p of nodes) {
      p.x += p.vx; p.y += p.vy; p.tw += 0.01;
      if (p.x < -10) p.x = W + 10; else if (p.x > W + 10) p.x = -10;
      if (p.y < -10) p.y = H + 10; else if (p.y > H + 10) p.y = -10;
    }
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    // Links first, under the nodes.
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        const dx = a.x - b.x, dy = a.y - b.y;
        const d2 = dx * dx + dy * dy;
        if (d2 > LINK_DIST * LINK_DIST) continue;
        const t = 1 - Math.sqrt(d2) / LINK_DIST;   // fade with distance
        ctx.strokeStyle = 'rgba(90,200,250,' + (0.12 * t).toFixed(3) + ')';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      }
    }
    for (const p of nodes) {
      const glow = 0.35 + 0.25 * Math.sin(p.tw);
      ctx.fillStyle = 'rgba(122,215,247,' + glow.toFixed(3) + ')';
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill();
    }
  }

  function loop() { step(); draw(); raf = requestAnimationFrame(loop); }

  window.addEventListener('resize', resize);
  document.addEventListener('visibilitychange', () => {
    if (reduceMotion) return;
    if (document.hidden) { cancelAnimationFrame(raf); raf = null; }
    else if (!raf) loop();
  });

  resize();
  if (!reduceMotion) loop();
})();

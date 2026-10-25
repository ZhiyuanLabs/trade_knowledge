"use client";

import { useEffect, useRef } from "react";

interface OrbCanvasProps {
  isThinking?: boolean;
  size?: number;
}

/**
 * Soft gradient blob orb — faithful to the reference GIF.
 * Uses an HTML Canvas 2D (no Three.js needed for this effect).
 * Multiple circular gradient layers drift and morph organically.
 * "isThinking" accelerates the animation and shifts hue.
 */
export default function OrbCanvas({ isThinking = false, size = 160 }: OrbCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef    = useRef<number>(0);
  const tRef      = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = size;
    const h = size;
    canvas.width  = w;
    canvas.height = h;

    // ── Color palette: pink · cyan · lavender · blue (matches ref) ──
    const colors = [
      { r: 224, g:  64, b: 251 }, // #E040FB — magenta-pink
      { r: 100, g: 210, b: 255 }, // #64D2FF — cyan-blue
      { r: 180, g: 140, b: 255 }, // #B48CFF — lavender
      { r: 255, g: 100, b: 200 }, // #FF64C8 — hot pink
      { r:  64, g: 224, b: 208 }, // #40E0D0 — turquoise
    ];

    // Blob descriptors — each one drifts around the canvas independently
    const blobs = colors.map((color, i) => ({
      color,
      phase:  (i / colors.length) * Math.PI * 2,
      speed:  0.25 + i * 0.07,
      rx:     0.15 + (i % 3) * 0.08,  // orbit radius X (fraction of size)
      ry:     0.12 + (i % 2) * 0.10,  // orbit radius Y
      radius: size * (0.38 + (i % 3) * 0.06),
    }));

    function draw(t: number) {
      if (!ctx || !canvas) return;
      ctx.clearRect(0, 0, w, h);

      const speed = isThinking ? 1.8 : 0.6;
      const cx    = w / 2;
      const cy    = h / 2;

      blobs.forEach((blob, i) => {
        const angle = t * blob.speed * speed + blob.phase;
        const x = cx + Math.cos(angle) * w * blob.rx;
        const y = cy + Math.sin(angle * 0.7 + i) * h * blob.ry;
        const r = blob.radius * (isThinking ? 1.08 : 1.0);

        const grad = ctx.createRadialGradient(x, y, 0, x, y, r);
        const { r: cr, g: cg, b: cb } = blob.color;
        grad.addColorStop(0,   `rgba(${cr},${cg},${cb}, 0.80)`);
        grad.addColorStop(0.5, `rgba(${cr},${cg},${cb}, 0.35)`);
        grad.addColorStop(1,   `rgba(${cr},${cg},${cb}, 0.00)`);

        ctx.globalCompositeOperation = "screen";
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();
      });
    }

    function loop() {
      tRef.current += 0.016;
      draw(tRef.current);
      rafRef.current = requestAnimationFrame(loop);
    }

    rafRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafRef.current);
  }, [size, isThinking]);

  return (
    <div
      style={{
        width:    size,
        height:   size,
        position: "relative",
        flexShrink: 0,
      }}
    >
      {/* Soft outer glow layer */}
      <div
        style={{
          position: "absolute",
          inset: "-20%",
          borderRadius: "50%",
          background: isThinking
            ? "radial-gradient(circle, rgba(180,140,255,0.18) 0%, transparent 70%)"
            : "radial-gradient(circle, rgba(100,210,255,0.12) 0%, transparent 70%)",
          transition: "background 1s ease",
          filter: "blur(12px)",
        }}
      />
      <canvas
        ref={canvasRef}
        style={{
          display:      "block",
          borderRadius: "50%",
          filter:       `blur(${size > 80 ? 14 : 4}px) saturate(1.2)`,
          position:     "relative",
          zIndex:       1,
        }}
      />
    </div>
  );
}

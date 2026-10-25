"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { Points, PointMaterial } from "@react-three/drei";
import { useState, useRef } from "react";
import type { Group } from "three";

const ADDITIVE_BLENDING = 2;

function ParticleSwarm() {
  const ref = useRef<Group | null>(null);
  
  // Create a spherical distribution of particles
  const [sphere] = useState(() => {
    // We use a simple randomizer for browser
    const numParticles = 2000;
    const positions = new Float32Array(numParticles * 3);
    for (let i = 0; i < numParticles; i++) {
        const radius = 5 * Math.cbrt(Math.random());
        const theta = 2 * Math.PI * Math.random();
        const phi = Math.acos(2 * Math.random() - 1);
        positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
        positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
        positions[i * 3 + 2] = radius * Math.cos(phi);
    }
    return positions;
  });

  useFrame((_, delta) => {
    if (ref.current) {
      ref.current.rotation.x -= delta / 30;
      ref.current.rotation.y -= delta / 40;
    }
  });

  return (
    <group ref={ref} rotation={[0, 0, Math.PI / 4]}>
      <Points positions={sphere} stride={3} frustumCulled={false}>
        <PointMaterial
          transparent
          color="#3b82f6"
          size={0.015}
          sizeAttenuation={true}
          depthWrite={false}
          blending={ADDITIVE_BLENDING}
          opacity={0.3}
        />
      </Points>
    </group>
  );
}

export default function ThreeBackground() {
  return (
    <div className="fixed inset-0 z-0 bg-[#060608] pointer-events-none">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(59,130,246,0.1)_0%,rgba(0,0,0,1)_70%)] z-0" />
      <Canvas camera={{ position: [0, 0, 3] }}>
        <ParticleSwarm />
      </Canvas>
    </div>
  );
}

import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

interface CosmicArmillarySphereProps {
  isStandby: boolean;
  onInspectCore: () => void;
}

export const CosmicArmillarySphere: React.FC<CosmicArmillarySphereProps> = ({
  isStandby,
  onInspectCore,
}) => {
  const mountRef = useRef<HTMLDivElement>(null);
  const [latency, setLatency] = useState(1.2);
  const [power, setPower] = useState(99.8);
  const [syncRate, setSyncRate] = useState(98.7);
  const showCallout = true;

  // Dynamic telemetry fluctuation
  useEffect(() => {
    const timer = setInterval(() => {
      setLatency(+(1.2 + (Math.random() * 0.4 - 0.2)).toFixed(1));
      setPower(+(99.8 + (Math.random() * 0.2 - 0.1)).toFixed(1));
      setSyncRate(+(98.7 + (Math.random() * 0.4 - 0.2)).toFixed(1));
    }, 3000);
    return () => clearInterval(timer);
  }, []);

  // Three.js 3D Armillary Sphere & Constellation Core
  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    const width = container.clientWidth || 440;
    const height = container.clientHeight || 440;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    camera.position.z = 4.8;

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const group = new THREE.Group();
    scene.add(group);

    // 1. Polished Gold/Bronze Armillary Rings
    const goldMat = new THREE.MeshBasicMaterial({
      color: 0xd97706, // warm gold
      wireframe: true,
      transparent: true,
      opacity: 0.8,
    });

    const ring1Geo = new THREE.TorusGeometry(1.5, 0.04, 16, 100);
    const ring1 = new THREE.Mesh(ring1Geo, goldMat);
    ring1.rotation.x = Math.PI / 4;
    group.add(ring1);

    const ring2Geo = new THREE.TorusGeometry(1.6, 0.035, 16, 100);
    const ring2 = new THREE.Mesh(ring2Geo, goldMat);
    ring2.rotation.y = Math.PI / 3;
    ring2.rotation.x = -Math.PI / 6;
    group.add(ring2);

    // 2. Polished Silver/Chrome Armillary Outer Rings
    const silverMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8, // cyan chrome
      wireframe: true,
      transparent: true,
      opacity: 0.65,
    });

    const ring3Geo = new THREE.TorusGeometry(1.7, 0.03, 16, 100);
    const ring3 = new THREE.Mesh(ring3Geo, silverMat);
    ring3.rotation.z = Math.PI / 3;
    group.add(ring3);

    const ring4Geo = new THREE.TorusGeometry(1.75, 0.025, 16, 100);
    const ring4 = new THREE.Mesh(ring4Geo, silverMat);
    ring4.rotation.x = Math.PI / 2;
    group.add(ring4);

    // 3. Central Constellation Star Core (Sphere of Star Nodes)
    const starCount = 280;
    const starGeo = new THREE.BufferGeometry();
    const starPos = new Float32Array(starCount * 3);
    const starColors = new Float32Array(starCount * 3);

    for (let i = 0; i < starCount; i++) {
      const radius = 0.4 + Math.random() * 0.8;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(Math.random() * 2 - 1);

      starPos[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      starPos[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      starPos[i * 3 + 2] = radius * Math.cos(phi);

      // Cyan to Amber stars
      if (Math.random() > 0.4) {
        starColors[i * 3] = 0.0;
        starColors[i * 3 + 1] = 1.0;
        starColors[i * 3 + 2] = 1.0;
      } else {
        starColors[i * 3] = 1.0;
        starColors[i * 3 + 1] = 0.7;
        starColors[i * 3 + 2] = 0.2;
      }
    }

    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
    starGeo.setAttribute('color', new THREE.BufferAttribute(starColors, 3));

    const starMat = new THREE.PointsMaterial({
      size: 0.045,
      vertexColors: true,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
    });
    const starField = new THREE.Points(starGeo, starMat);
    group.add(starField);

    // 4. Central Glowing Amber Nucleus
    const nucleusGeo = new THREE.SphereGeometry(0.3, 16, 16);
    const nucleusMat = new THREE.MeshBasicMaterial({
      color: 0xfb923c,
      transparent: true,
      opacity: 0.7,
      wireframe: true,
    });
    const nucleus = new THREE.Mesh(nucleusGeo, nucleusMat);
    group.add(nucleus);

    // Mouse Interaction
    let targetX = 0;
    let targetY = 0;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
      targetY = x * 0.9;
      targetX = y * 0.9;
    };

    window.addEventListener('mousemove', handleMouseMove);

    // Animation Loop
    let animId: number;
    let clock = new THREE.Clock();

    const animate = () => {
      animId = requestAnimationFrame(animate);
      const elapsed = clock.getElapsedTime();
      const speed = isStandby ? 0.2 : 1.0;

      ring1.rotation.z += 0.006 * speed;
      ring2.rotation.x += 0.005 * speed;
      ring3.rotation.y += 0.008 * speed;
      ring4.rotation.z -= 0.007 * speed;
      starField.rotation.y += 0.004 * speed;

      const pulse = 1.0 + Math.sin(elapsed * 2.5) * 0.05;
      nucleus.scale.set(pulse, pulse, pulse);

      group.rotation.y += (targetY - group.rotation.y) * 0.06;
      group.rotation.x += (targetX - group.rotation.x) * 0.06;

      renderer.render(scene, camera);
    };

    animate();

    const handleResize = () => {
      if (!container) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(animId);
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
      renderer.dispose();
    };
  }, [isStandby]);

  return (
    <div className="relative w-full max-w-5xl mx-auto flex items-center justify-center my-0 select-none z-20">
      {/* ============================================================ */}
      {/* LEFT HUD TELEMETRY BLOCK (Exact from content.png)            */}
      {/* ============================================================ */}
      <div className="absolute left-4 lg:left-12 top-1/2 -translate-y-1/2 hidden md:block text-[9px] lg:text-[10px] font-mono text-cyan-400/90 space-y-1 z-30 pointer-events-auto">
        <div className="text-cyan-300 font-bold border-b border-cyan-500/30 pb-0.5">
          BASE: ORION-09-LMC-NODE
        </div>
        <div>LOCATION: SECTOR-09</div>
        <div>CONNECTIONS: 6 ACTIVE</div>
        <div>POWER: NOMINAL ({power}%)</div>
        <div>LATENCY: {latency}MS</div>
        <div>TRAJECTORY: DEFINED</div>
        <div className="text-cyan-200 font-bold">SYNC: {syncRate}%</div>
      </div>

      {/* ============================================================ */}
      {/* RIGHT HUD TELEMETRY BLOCK (Exact from content.png)           */}
      {/* ============================================================ */}
      <div className="absolute right-4 lg:right-12 top-1/2 -translate-y-1/2 hidden md:block text-[9px] lg:text-[10px] font-mono text-cyan-400/90 space-y-1 text-right z-30 pointer-events-auto">
        <div className="text-cyan-300 font-bold border-b border-cyan-500/30 pb-0.5">
          BASE: ORION-11-LMC-NODE
        </div>
        <div>LOCATION: CARINA</div>
        <div>ORBIT: GEO-STATIONARY</div>
        <div>CONNECTIONS: 8 ACTIVE</div>
        <div>POWER: NOMINAL (96.4%)</div>
        <div>LATENCY: 2.4MS</div>
        <div>TRAJECTORY: DEFOCUS</div>
        <div className="text-cyan-200 font-bold">SYNC: 99.1%</div>
      </div>

      {/* ============================================================ */}
      {/* CENTER SPHERICAL ORB WITH 3D CANVAS & HUD CALLOUT           */}
      {/* ============================================================ */}
      <div className="relative w-80 h-80 sm:w-96 sm:h-96 md:w-[450px] md:h-[450px] flex items-center justify-center">
        {/* Background Rotating Azimuth Rings */}
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <svg viewBox="0 0 500 500" className="w-full h-full animate-spin-cw-slow opacity-40">
            <circle cx="250" cy="250" r="230" fill="none" stroke="#00ffff" strokeWidth="0.8" strokeDasharray="6 8" />
            <circle cx="250" cy="250" r="195" fill="none" stroke="#f97316" strokeWidth="1" strokeDasharray="4 6" opacity="0.6" />
          </svg>
        </div>

        {/* Ambient Cosmic Radial Glow Backlight */}
        <div className="absolute w-64 h-64 rounded-full bg-cyan-500/15 blur-[50px] pointer-events-none" />
        <div className="absolute w-44 h-44 rounded-full bg-amber-500/15 blur-[35px] pointer-events-none" />

        {/* 3D WebGL Armillary Sphere Mount */}
        <div
          ref={mountRef}
          onClick={onInspectCore}
          title="Cosmic Engine Core (Click to Inspect)"
          className="w-full h-full rounded-full cursor-pointer hover:scale-105 transition-transform duration-500 relative z-20"
        />

        {/* Cyan Callout Pointer: [-- Cosmic Engine Core */}
        {showCallout && (
          <div
            onClick={onInspectCore}
            className="absolute left-[-15%] sm:left-[-5%] top-[38%] text-xs font-mono text-cyan-300 flex items-center space-x-2 bg-black/60 px-2.5 py-1 border border-cyan-400/50 rounded cursor-pointer hover:border-cyan-300 hover:shadow-[0_0_15px_#00ffff] transition-all z-30"
          >
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping mr-1" />
            <span className="font-bold tracking-wider">[-- Cosmic Engine Core</span>
          </div>
        )}
      </div>
    </div>
  );
};

'use client';

import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

interface HavenAvatarProps {
  isSpeaking?: boolean;
  emotion?: 'calm' | 'listening' | 'speaking' | 'supportive';
  className?: string;
}

export default function HavenAvatar({
  isSpeaking = false,
  emotion = 'calm',
  className = '',
}: HavenAvatarProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loadStatus, setLoadStatus] = useState<'loading' | 'loaded' | 'fallback'>('loading');

  const sceneRef = useRef<THREE.Scene | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const modelRef = useRef<THREE.Group | null>(null);
  const headRef = useRef<THREE.Object3D | null>(null);
  const morphMeshRef = useRef<THREE.SkinnedMesh | null>(null);
  const reqIdRef = useRef<number | null>(null);
  const isSpeakingRef = useRef<boolean>(isSpeaking);

  useEffect(() => {
    isSpeakingRef.current = isSpeaking;
  }, [isSpeaking]);

  useEffect(() => {
    if (!containerRef.current) return;
    let isCancelled = false;

    const container = containerRef.current;
    const width = container.clientWidth || 360;
    const height = container.clientHeight || 420;

    // 1. Setup Three Scene & Camera
    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(38, width / height, 0.1, 100);
    camera.position.set(0, 1.45, 1.25);
    camera.lookAt(0, 1.42, 0);

    // 2. Setup WebGL Renderer with graceful error handling
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.1;
      container.innerHTML = '';
      container.appendChild(renderer.domElement);
      rendererRef.current = renderer;
    } catch (e) {
      console.warn('WebGL initialization failed, using calm fallback:', e);
      setLoadStatus('fallback');
      return;
    }

    // 3. Calming Studio Lighting suited to Haven aesthetic
    const ambientLight = new THREE.AmbientLight(0xfff5f8, 1.8);
    scene.add(ambientLight);

    const mainLight = new THREE.DirectionalLight(0xffeedd, 2.2);
    mainLight.position.set(1.5, 3, 2);
    scene.add(mainLight);

    const softFillLight = new THREE.DirectionalLight(0xe8d5ea, 1.4);
    softFillLight.position.set(-2, 2, -1);
    scene.add(softFillLight);

    // 4. Load 3D Model with GLTFLoader
    const loader = new GLTFLoader();
    loader.load(
      '/models/avatar.glb',
      (gltf) => {
        if (isCancelled) return;
        const model = gltf.scene;
        modelRef.current = model;

        // Position model centered on shoulders and face
        model.position.set(0, 0, 0);
        model.scale.set(1, 1, 1);
        scene.add(model);

        // Find head bone or mesh with morph targets
        model.traverse((child) => {
          if (child instanceof THREE.SkinnedMesh && child.morphTargetDictionary) {
            morphMeshRef.current = child;
          }
          if (child.name.toLowerCase().includes('head')) {
            headRef.current = child;
          }
        });

        setLoadStatus('loaded');
      },
      undefined,
      (err) => {
        console.warn('3D avatar model load notice, showing calming companion:', err);
        if (!isCancelled) setLoadStatus('fallback');
      }
    );

    // 5. Mouse/Touch parallax tracking
    let targetMouseX = 0;
    let targetMouseY = 0;
    let currentMouseX = 0;
    let currentMouseY = 0;

    const handlePointerMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const ny = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
      targetMouseX = Math.max(-0.4, Math.min(0.4, nx * 0.4));
      targetMouseY = Math.max(-0.25, Math.min(0.25, ny * 0.25));
    };

    window.addEventListener('pointermove', handlePointerMove);

    // 6. Smooth Animation Loop
    let clock = new THREE.Clock();
    let blinkTimer = 0;
    let isBlinking = false;
    let blinkProgress = 0;

    const animate = () => {
      reqIdRef.current = requestAnimationFrame(animate);

      const delta = clock.getDelta();
      const time = clock.getElapsedTime();

      // Smooth mouse interpolation
      currentMouseX += (targetMouseX - currentMouseX) * 0.05;
      currentMouseY += (targetMouseY - currentMouseY) * 0.05;

      // Gentle procedural breathing and idle head motion
      if (modelRef.current) {
        modelRef.current.position.y = Math.sin(time * 1.5) * 0.006;
        modelRef.current.rotation.y = currentMouseX * 0.35 + Math.sin(time * 0.7) * 0.02;
        modelRef.current.rotation.x = -currentMouseY * 0.2 + Math.cos(time * 1.2) * 0.01;
      }

      // Morph target visemes & blinking
      const mesh = morphMeshRef.current;
      if (mesh && mesh.morphTargetDictionary && mesh.morphTargetInfluences) {
        const dict = mesh.morphTargetDictionary;
        const inf = mesh.morphTargetInfluences;

        // Blinking
        blinkTimer += delta;
        if (blinkTimer > 3.5) {
          isBlinking = true;
          blinkTimer = 0;
          blinkProgress = 0;
        }

        if (isBlinking) {
          blinkProgress += delta * 7;
          const blinkVal = Math.sin(blinkProgress * Math.PI);
          if (dict['eyeBlinkLeft'] !== undefined) inf[dict['eyeBlinkLeft']] = Math.max(0, blinkVal);
          if (dict['eyeBlinkRight'] !== undefined) inf[dict['eyeBlinkRight']] = Math.max(0, blinkVal);
          if (blinkProgress >= 1) {
            isBlinking = false;
            if (dict['eyeBlinkLeft'] !== undefined) inf[dict['eyeBlinkLeft']] = 0;
            if (dict['eyeBlinkRight'] !== undefined) inf[dict['eyeBlinkRight']] = 0;
          }
        }

        // Talking mouth movement (visemes)
        if (isSpeakingRef.current) {
          const mouthOpen = Math.abs(Math.sin(time * 11)) * 0.65 + Math.abs(Math.sin(time * 7)) * 0.25;
          if (dict['jawOpen'] !== undefined) inf[dict['jawOpen']] = mouthOpen;
          if (dict['viseme_AA'] !== undefined) inf[dict['viseme_AA']] = mouthOpen * 0.8;
          if (dict['mouthOpen'] !== undefined) inf[dict['mouthOpen']] = mouthOpen * 0.5;
        } else {
          // Relax mouth smoothly
          if (dict['jawOpen'] !== undefined) inf[dict['jawOpen']] *= 0.8;
          if (dict['viseme_AA'] !== undefined) inf[dict['viseme_AA']] *= 0.8;
          if (dict['mouthOpen'] !== undefined) inf[dict['mouthOpen']] *= 0.8;
        }

        // Calming slight smile
        if (dict['mouthSmileLeft'] !== undefined) inf[dict['mouthSmileLeft']] = 0.22;
        if (dict['mouthSmileRight'] !== undefined) inf[dict['mouthSmileRight']] = 0.22;
      }

      renderer.render(scene, camera);
    };

    animate();

    // 7. Resize handling
    const handleResize = () => {
      if (!container) return;
      const nw = container.clientWidth || 360;
      const nh = container.clientHeight || 420;
      camera.aspect = nw / nh;
      camera.updateProjectionMatrix();
      renderer.setSize(nw, nh);
    };

    window.addEventListener('resize', handleResize);

    return () => {
      isCancelled = true;
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('resize', handleResize);
      if (reqIdRef.current) cancelAnimationFrame(reqIdRef.current);
      if (renderer) renderer.dispose();
      if (container) container.innerHTML = '';
    };
  }, []);

  return (
    <div className={`relative flex flex-col items-center justify-center overflow-hidden rounded-2xl bg-gradient-to-b from-rose-50/60 to-purple-50/40 dark:from-stone-900/60 dark:to-purple-950/20 border border-border/70 ${className}`}>
      {/* Three.js Canvas Container */}
      <div
        ref={containerRef}
        className={`w-full h-full min-h-[380px] sm:min-h-[440px] transition-opacity duration-700 ${
          loadStatus === 'loaded' ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
      />

      {/* Loading or Fallback Companion */}
      {loadStatus !== 'loaded' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center space-y-4">
          <div className="relative">
            <div className={`w-32 h-32 rounded-full flex items-center justify-center bg-gradient-to-tr from-primary/30 to-purple-400/30 border-2 border-primary/40 shadow-inner transition-transform duration-700 ${
              isSpeaking ? 'scale-105 animate-pulse' : 'scale-100'
            }`}>
              <span className="text-4xl select-none" role="img" aria-label="Haven Companion">
                🕊️
              </span>
            </div>
            {isSpeaking && (
              <span className="absolute -top-1 -right-1 flex h-4 w-4">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                <span className="relative inline-flex rounded-full h-4 w-4 bg-primary" />
              </span>
            )}
          </div>

          <div className="space-y-1">
            <h3 className="text-base font-semibold text-foreground">Haven Support Companion</h3>
            <p className="text-xs text-muted-foreground max-w-xs">
              {loadStatus === 'loading'
                ? 'Preparing your private conversation space…'
                : 'Here with you in a safe, judgment-free space.'}
            </p>
          </div>
        </div>
      )}

      {/* Status Badge */}
      <div className="absolute bottom-3 left-3 flex items-center gap-2 px-3 py-1 rounded-full bg-background/85 backdrop-blur border border-border/80 text-xs shadow-sm">
        <span
          className={`w-2 h-2 rounded-full ${
            isSpeaking ? 'bg-emerald-500 animate-pulse' : 'bg-primary'
          }`}
          aria-hidden="true"
        />
        <span className="font-medium text-foreground">
          {isSpeaking ? 'Haven is speaking…' : 'Haven is listening'}
        </span>
      </div>
    </div>
  );
}

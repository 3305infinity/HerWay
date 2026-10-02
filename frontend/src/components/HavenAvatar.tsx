'use client';

import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

interface HavenAvatarProps {
  isSpeaking?: boolean;
  className?: string;
}

export default function HavenAvatar({
  isSpeaking = false,
  className = '',
}: HavenAvatarProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loadStatus, setLoadStatus] = useState<'loading' | 'loaded' | 'fallback'>('loading');

  const sceneRef = useRef<THREE.Scene | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const modelRef = useRef<THREE.Group | null>(null);
  const headRef = useRef<THREE.Object3D | null>(null);
  const morphMeshRef = useRef<THREE.SkinnedMesh | null>(null);
  //: PMREM generator and its render target, so both can be released on unmount.
  //: Leaking a render target between remounts shows up as a slow GPU-memory
  //: climb every time the user navigates back to this page.
  const envRef = useRef<{ pmrem: THREE.PMREMGenerator; target: THREE.WebGLRenderTarget } | null>(null);
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

    // A longer lens flatters a face. At 38° the nose is noticeably pushed
    // forward and the cheeks fall away — the same reason portraits are shot at
    // 85mm rather than 35mm. 28° with the camera pulled back keeps the framing
    // but removes the distortion.
    const camera = new THREE.PerspectiveCamera(28, width / height, 0.1, 100);
    camera.position.set(0, 1.46, 1.72);
    camera.lookAt(0, 1.4, 0);

    // 2. Setup WebGL Renderer with graceful error handling
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      // Lowered from 1.1: with image-based lighting added below, the previous
      // exposure clipped the highlights on her forehead and cheekbones to flat
      // white, which is what made the face look plastic.
      renderer.toneMappingExposure = 0.95;
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      container.innerHTML = '';
      container.appendChild(renderer.domElement);
      rendererRef.current = renderer;
    } catch (e) {
      console.warn('WebGL initialization failed, using calm fallback:', e);
      setLoadStatus('fallback');
      return;
    }

    // 3. Image-based lighting.
    //
    // This is the single biggest change. The model uses PBR materials, and PBR
    // needs an environment to reflect — without one, skin and hair have nothing
    // to pick up and read as flat vinyl no matter how many lights are added.
    // RoomEnvironment is a small procedural studio; PMREMGenerator turns it
    // into the prefiltered map the materials sample.
    const pmrem = new THREE.PMREMGenerator(renderer);
    pmrem.compileEquirectangularShader();
    // Constructed without a renderer: the bundled type definitions declare a
    // zero-argument constructor, and the optional renderer argument is only
    // used for a legacy code path we do not need.
    const roomEnvironment = new RoomEnvironment();
    const envTarget = pmrem.fromScene(roomEnvironment, 0.04);
    scene.environment = envTarget.texture;
    roomEnvironment.dispose();
    envRef.current = { pmrem, target: envTarget };

    // 4. Three-point lighting over the top of the environment.
    //
    // The previous setup used a strong AmbientLight, which adds the same value
    // everywhere and therefore erases form — it was fighting the shading rather
    // than supporting it. A hemisphere light gives a warm-above / cool-below
    // falloff instead, which is how a real room actually behaves.
    const hemisphere = new THREE.HemisphereLight(0xffeef2, 0x3a2f3f, 0.55);
    scene.add(hemisphere);

    // Key: warm, high and slightly camera-left, the classic portrait position.
    const keyLight = new THREE.DirectionalLight(0xfff1e4, 2.0);
    keyLight.position.set(1.6, 2.6, 2.2);
    keyLight.castShadow = true;
    keyLight.shadow.mapSize.set(1024, 1024);
    keyLight.shadow.camera.near = 0.5;
    keyLight.shadow.camera.far = 8;
    keyLight.shadow.bias = -0.0012;
    keyLight.shadow.radius = 4;
    scene.add(keyLight);

    // Fill: cool and dim, opposite the key. Lifts the shadow side just enough
    // to keep detail without flattening it.
    const fillLight = new THREE.DirectionalLight(0xd9ddff, 0.5);
    fillLight.position.set(-2.4, 1.2, 1.4);
    scene.add(fillLight);

    // Rim: behind and above, catching the edge of the hair and shoulders. This
    // is what separates her from the background — without it the head reads as
    // pasted onto the gradient rather than sitting in front of it.
    const rimLight = new THREE.DirectionalLight(0xffd9ec, 1.5);
    rimLight.position.set(-1.0, 2.4, -2.6);
    scene.add(rimLight);

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

        // Find head bone or mesh with morph targets, and tune materials.
        model.traverse((child) => {
          if (child instanceof THREE.SkinnedMesh && child.morphTargetDictionary) {
            morphMeshRef.current = child;
          }
          if (child.name.toLowerCase().includes('head')) {
            headRef.current = child;
          }

          if (child instanceof THREE.Mesh) {
            child.castShadow = true;
            child.receiveShadow = true;

            const materials = Array.isArray(child.material) ? child.material : [child.material];
            for (const material of materials) {
              if (!(material instanceof THREE.MeshStandardMaterial)) continue;

              // Let the environment actually show in the surface. Exported
              // avatars commonly ship with envMapIntensity at 1, which under a
              // procedural studio map reads as dull.
              material.envMapIntensity = 1.15;

              const name = (child.name + ' ' + (material.name || '')).toLowerCase();

              if (name.includes('hair')) {
                // Hair wants an anisotropic sheen. Dropping roughness gives it
                // a soft highlight instead of looking like moulded plastic.
                material.roughness = Math.min(material.roughness, 0.42);
                material.envMapIntensity = 1.5;
              } else if (name.includes('eye') || name.includes('teeth')) {
                // Wet surfaces. These read as dead when rendered matte, and the
                // eyes are what make a face feel present.
                material.roughness = 0.12;
                material.envMapIntensity = 1.9;
              } else if (name.includes('skin') || name.includes('body') || name.includes('head')) {
                // Skin is not shiny, but it is not chalk either. A touch of
                // broad specular keeps the cheekbones and brow readable.
                material.roughness = Math.max(Math.min(material.roughness, 0.82), 0.6);
                material.envMapIntensity = 1.0;
              }

              material.needsUpdate = true;
            }
          }
        });

        // A soft contact shadow. Without it the figure floats, which is the
        // tell that most clearly reads as "3D model pasted on a background"
        // rather than someone sitting in a space.
        const shadowCatcher = new THREE.Mesh(
          new THREE.PlaneGeometry(6, 6),
          new THREE.ShadowMaterial({ opacity: 0.22 }),
        );
        shadowCatcher.rotation.x = -Math.PI / 2;
        shadowCatcher.position.y = 0.001;
        shadowCatcher.receiveShadow = true;
        scene.add(shadowCatcher);

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
    const clock = new THREE.Clock();
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
      // Release the environment map before the renderer. Leaving it behind
      // leaks GPU memory on every remount of this page.
      if (envRef.current) {
        envRef.current.target.dispose();
        envRef.current.pmrem.dispose();
        envRef.current = null;
      }
      scene.environment = null;
      if (renderer) renderer.dispose();
      if (container) container.innerHTML = '';
    };
  }, []);

  return (
    <div className={`group relative flex flex-col items-center justify-center overflow-hidden rounded-2xl border border-border/70 bg-gradient-to-b from-rose-50/60 to-purple-50/40 dark:from-stone-900/60 dark:to-purple-950/20 ${className}`}>
      {/* Backdrop.
          A radial pool of warm light behind her head, rather than a flat
          top-to-bottom gradient. It gives the figure something to stand in
          front of and makes the rim light read as coming from the scene. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_32%,rgba(244,194,214,0.42),transparent_62%)] dark:bg-[radial-gradient(ellipse_at_50%_32%,rgba(142,94,128,0.34),transparent_62%)]"
      />

      {/* Three.js Canvas Container */}
      <div
        ref={containerRef}
        className={`relative z-10 h-full w-full min-h-[380px] transition-opacity duration-1000 sm:min-h-[440px] ${
          loadStatus === 'loaded' ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
      />

      {/* Vignette. Darkens the corners slightly so the eye settles on her face
          instead of the edges of the panel. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-20 bg-[radial-gradient(ellipse_at_center,transparent_55%,rgba(60,40,55,0.16)_100%)]"
      />

      {/* Loading or Fallback Companion */}
      {loadStatus !== 'loaded' && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center space-y-4 p-6 text-center">
          <div className="relative">
            {/* Breathing halo. Gives the placeholder a sense of presence while
                the 2.9 MB model downloads, instead of a static disc. */}
            <div
              aria-hidden
              className="absolute -inset-4 rounded-full bg-primary/15 blur-xl motion-safe:animate-pulse"
            />
            <div className={`relative flex h-32 w-32 items-center justify-center rounded-full border-2 border-primary/40 bg-gradient-to-tr from-primary/30 to-purple-400/30 shadow-inner transition-transform duration-700 ${
              isSpeaking ? 'scale-105' : 'scale-100'
            }`}>
              <span className="select-none text-4xl" role="img" aria-label="Niva Support Companion">
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
            <h3 className="text-base font-semibold text-foreground">Niva Support Companion</h3>
            <p className="text-xs text-muted-foreground max-w-xs">
              {loadStatus === 'loading'
                ? 'Preparing your private conversation space…'
                : 'Here with you in a safe, judgment-free space.'}
            </p>
          </div>
        </div>
      )}

      {/* Status Badge.
          `aria-live="polite"` so a screen-reader user is told when Niva starts
          and stops speaking — previously this changed silently for them. */}
      <div
        className="absolute bottom-3 left-3 z-30 flex items-center gap-2 rounded-full border border-border/80 bg-background/80 px-3 py-1.5 text-xs shadow-sm backdrop-blur-md"
        aria-live="polite"
      >
        <span className="relative flex h-2 w-2" aria-hidden="true">
          {isSpeaking && (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          )}
          <span
            className={`relative inline-flex h-2 w-2 rounded-full ${
              isSpeaking ? 'bg-emerald-500' : 'bg-primary'
            }`}
          />
        </span>
        <span className="font-medium text-foreground">
          {isSpeaking ? 'Niva is speaking…' : 'Niva is listening'}
        </span>
      </div>
    </div>
  );
}

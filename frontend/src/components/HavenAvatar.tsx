'use client';

import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

interface HavenAvatarProps {
  isSpeaking?: boolean;
  className?: string;
}


/**
 * Morph-target name resolution.
 *
 * Different pipelines spell the same expression differently. These are the
 * spellings seen across ARKit/ReadyPlayerMe-style exports, VRoid/VRM, Blender
 * shape keys and common marketplace rigs. Matching is case-insensitive and
 * falls back to a substring scan, because exporters frequently prefix names
 * (`CTRL_expressions_jawOpen`, `Fcl_MTH_A`).
 */
const MORPH_ALIASES: Record<string, string[]> = {
  blinkLeft: ['eyeBlinkLeft', 'eyeBlink_L', 'blink_l', 'blinkLeft', 'Blink_L', 'Fcl_EYE_Close_L', 'eyesClosedL'],
  blinkRight: ['eyeBlinkRight', 'eyeBlink_R', 'blink_r', 'blinkRight', 'Blink_R', 'Fcl_EYE_Close_R', 'eyesClosedR'],
  blinkBoth: ['blink', 'eyesClosed', 'Fcl_EYE_Close', 'eye_close'],
  jawOpen: ['jawOpen', 'mouthOpen', 'viseme_AA', 'A', 'aa', 'Fcl_MTH_A', 'mouth_open', 'JawOpen'],
  smileLeft: ['mouthSmileLeft', 'mouthSmile_L', 'smile_l', 'Fcl_MTH_Joy'],
  smileRight: ['mouthSmileRight', 'mouthSmile_R', 'smile_r'],
};

/** Index of the first alias this model actually has, or undefined. */
function resolveMorph(
  dict: Record<string, number>,
  aliases: string[],
): number | undefined {
  const keys = Object.keys(dict);
  for (const alias of aliases) {
    const exact = keys.find((k) => k.toLowerCase() === alias.toLowerCase());
    if (exact !== undefined) return dict[exact];
  }
  for (const alias of aliases) {
    const partial = keys.find((k) => k.toLowerCase().includes(alias.toLowerCase()));
    if (partial !== undefined) return dict[partial];
  }
  return undefined;
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
  //: Resolved per model — see MORPH_ALIASES. Any entry may be undefined,
  //: in which case the animation loop substitutes procedural motion.
  const morphIndexRef = useRef<Record<string, number | undefined>>({});
  //: Measured from the model's bounding box so the contact shadow lands on
  //: its feet rather than on an assumed y = 0.
  const groundYRef = useRef<number>(0);
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

        // Frame the head from the model's actual geometry.
        //
        // The camera used to be hardcoded at (0, 1.46, 1.72) looking at
        // y = 1.4 — numbers that only work if a model happens to be a
        // 1.7m-tall figure standing at the origin. Anything else and the
        // camera points at empty space above the head, which is exactly what
        // happened: all you could see was the crown of a head pushing into
        // frame from below.
        //
        // Measuring instead of guessing means any GLB frames correctly —
        // tall, short, bust-only, or offset from the origin.
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());

        if (size.y > 0) {
          // Is this a full figure or already a bust?
          //
          // A standing person is roughly 3.5–4x taller than wide. A head-and-
          // shoulders model is closer to 1.5x. Framing the top third is right
          // for the first and badly wrong for the second — on a bust it crops
          // to eyes-and-mouth, which is what happened here.
          const widest = Math.max(size.x, size.z);
          const aspect = widest > 0 ? size.y / widest : 1;
          const isFullFigure = aspect > 2.2;

          // What to put in frame, and where to centre it.
          const framedHeight = isFullFigure
            ? size.y * 0.33 // top third of a standing figure
            : size.y * 0.92; // nearly all of a bust, with a little air
          const focusY = isFullFigure
            ? box.max.y - size.y * 0.16 // head-and-shoulders near the top
            : center.y + size.y * 0.04; // the bust's own centre, nudged up

          const fovRadians = (camera.fov * Math.PI) / 180;
          const distance = (framedHeight / 2 / Math.tan(fovRadians / 2)) * 1.25;

          camera.position.set(center.x, focusY, box.max.z + distance);
          camera.lookAt(center.x, focusY, center.z);
          camera.updateProjectionMatrix();

          console.info(
            `[Niva] model ${size.x.toFixed(2)}x${size.y.toFixed(2)}x${size.z.toFixed(2)} ` +
              `(aspect ${aspect.toFixed(2)}) → framed as ${isFullFigure ? 'full figure' : 'bust'}`,
          );

          const eyeLine = focusY;

          // Keep the key light relative to the subject rather than the origin,
          // so a model standing off-centre is still lit from the front-left.
          keyLight.position.set(center.x + distance * 0.7, eyeLine + size.y * 0.4, box.max.z + distance);
          keyLight.target.position.set(center.x, eyeLine, center.z);
          scene.add(keyLight.target);

          // Ground the contact shadow on the model's actual base.
          groundYRef.current = box.min.y;
        }
        scene.add(model);

        // Find head bone or mesh with morph targets, and tune materials.
        //
        // Morph target names are NOT standardised. The ARKit set this code was
        // written against (`jawOpen`, `eyeBlinkLeft`, `viseme_AA`) comes from
        // one family of exporters; a model from Blender, VRoid, Mixamo or a
        // marketplace will commonly use `Blink`, `A`, `mouth_open`, `Fcl_MTH_A`
        // or nothing at all. Matching only the ARKit spelling meant any other
        // model loaded and then sat completely frozen — alive-looking enough to
        // be unsettling, which is the worst outcome on this page.
        //
        // So: resolve each expression to whatever this model actually has, and
        // record what is missing so the animation loop can substitute
        // procedural head motion instead of doing nothing.
        model.traverse((child) => {
          if (child instanceof THREE.SkinnedMesh && child.morphTargetDictionary) {
            morphMeshRef.current = child;
            const dict = child.morphTargetDictionary as Record<string, number>;
            morphIndexRef.current = Object.fromEntries(
              Object.entries(MORPH_ALIASES).map(([key, aliases]) => [
                key,
                resolveMorph(dict, aliases),
              ]),
            );
            const found = Object.entries(morphIndexRef.current)
              .filter(([, v]) => v !== undefined)
              .map(([k]) => k);
            console.info(
              `[Niva] model expressions available: ${found.join(', ') || 'none — using procedural motion'}`,
            );
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
        shadowCatcher.position.y = groundYRef.current + 0.001;
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
      const morph = morphIndexRef.current;
      const inf = mesh?.morphTargetInfluences;

      /** Set an expression if this model has it. Returns whether it did. */
      const setMorph = (key: string, value: number): boolean => {
        const index = morph[key];
        if (index === undefined || !inf) return false;
        inf[index] = value;
        return true;
      };

      // ---- Blinking ----------------------------------------------------
      blinkTimer += delta;
      if (blinkTimer > 3.5) {
        isBlinking = true;
        blinkTimer = 0;
        blinkProgress = 0;
      }

      if (isBlinking) {
        blinkProgress += delta * 7;
        const blinkVal = Math.max(0, Math.sin(blinkProgress * Math.PI));
        // Per-eye where available, otherwise a single combined blink shape.
        const blinked =
          [setMorph('blinkLeft', blinkVal), setMorph('blinkRight', blinkVal)].some(Boolean) ||
          setMorph('blinkBoth', blinkVal);

        if (!blinked && headRef.current) {
          // No blink shape at all. Rather than freeze, give the head a small
          // downward nod on the same rhythm — it reads as a glance down and
          // keeps the model feeling inhabited.
          headRef.current.rotation.x += Math.sin(blinkProgress * Math.PI) * 0.004;
        }

        if (blinkProgress >= 1) {
          isBlinking = false;
          setMorph('blinkLeft', 0);
          setMorph('blinkRight', 0);
          setMorph('blinkBoth', 0);
        }
      }

      // ---- Speaking ----------------------------------------------------
      if (isSpeakingRef.current) {
        const mouthOpen =
          Math.abs(Math.sin(time * 11)) * 0.65 + Math.abs(Math.sin(time * 7)) * 0.25;
        const spoke = setMorph('jawOpen', mouthOpen);

        if (!spoke && headRef.current) {
          // No jaw shape: suggest speech with a faint head movement instead of
          // a motionless face, which looks broken while text is arriving.
          headRef.current.rotation.z = Math.sin(time * 9) * 0.012;
        }
      } else {
        const index = morph['jawOpen'];
        if (index !== undefined && inf) inf[index] *= 0.8;
        if (headRef.current) headRef.current.rotation.z *= 0.9;
      }

      // ---- Resting expression ------------------------------------------
      // A faint lift, not a smile — see NivaPortrait's removal note: on this
      // page a cheerful face is the wrong thing to meet someone with.
      setMorph('smileLeft', 0.22);
      setMorph('smileRight', 0.22);

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

      {/* Placeholder while the 3D model loads, and the permanent state on
          devices without WebGL.

          Deliberately NOT a drawn face. A hand-authored portrait sits straight
          in the uncanny valley — a face that is almost right is worse than no
          face, and this is the surface someone reaches when they are already
          distressed. An abstract mark cannot be unsettling, so that is what
          this is: concentric rings that breathe, in the app's own rose and
          plum, with her name set in Playfair. */}
      <div
        className={`absolute inset-0 z-20 flex flex-col items-center justify-center p-6 transition-opacity duration-1000 ${
          loadStatus === 'loaded' ? 'pointer-events-none opacity-0' : 'opacity-100'
        }`}
      >
        <div className="relative flex h-36 w-36 items-center justify-center">
          {/* Outer ring — the slowest, widest movement. */}
          <span
            aria-hidden
            className="absolute inset-0 rounded-full border border-primary/25 motion-safe:animate-[niva-ring_5s_ease-in-out_infinite]"
          />
          {/* Middle ring, offset so the two never pulse together. */}
          <span
            aria-hidden
            className="absolute inset-[14%] rounded-full border border-primary/35 motion-safe:animate-[niva-ring_5s_ease-in-out_infinite_1.6s]"
          />
          {/* Core: a soft warm disc, brighter while she is speaking. */}
          <span
            aria-hidden
            className={`absolute inset-[30%] rounded-full bg-gradient-to-br from-primary/45 to-purple-400/35 blur-[2px] transition-all duration-700 ${
              isSpeaking ? 'scale-110 opacity-100' : 'scale-100 opacity-80'
            } motion-safe:animate-[niva-core_4s_ease-in-out_infinite]`}
          />
        </div>

        <div className="mt-5 space-y-1 text-center">
          <h3 className="font-serif text-xl font-normal text-foreground">Niva</h3>
          <p className="max-w-xs text-xs leading-relaxed text-muted-foreground">
            {loadStatus === 'loading'
              ? 'Here with you. Take your time.'
              : 'Here with you in a safe, judgment-free space.'}
          </p>
        </div>
      </div>

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

import * as THREE from "three";

export type CoreTone = "healthy" | "alert" | "blocked";

export interface SpatialNode {
  name: string;
  status: string;
  permissionMode: string;
}

export interface SpatialSceneOptions {
  container: HTMLDivElement;
  labelElements: HTMLElement[];
  reducedMotion: boolean;
}

export interface SpatialSceneHandle {
  setTone: (tone: CoreTone) => void;
  setNodes: (nodes: SpatialNode[]) => void;
  shockwave: () => void;
  setActive: (active: boolean) => void;
  dispose: () => void;
}

const TONE_COLORS: Record<CoreTone, number> = {
  healthy: 0x10b981,
  alert: 0xf59e0b,
  blocked: 0xef4444,
};

export const DEFAULT_NODES: SpatialNode[] = [
  { name: "postgres-prod-mcp", status: "ONLINE", permissionMode: "HITL_REQUIRED" },
  { name: "github-repo-mcp", status: "ONLINE", permissionMode: "READ_ONLY" },
  { name: "filesystem-sandbox-mcp", status: "ONLINE", permissionMode: "ALLOW_ALL" },
  { name: "stripe-billing-mcp", status: "DEGRADED", permissionMode: "HITL_REQUIRED" },
];

function nodeColor(node: SpatialNode): number {
  if (node.status === "OFFLINE" || node.permissionMode === "STRICT_BLOCK") {
    return 0xef4444;
  }
  if (node.status === "DEGRADED" || node.permissionMode === "HITL_REQUIRED") {
    return 0xf59e0b;
  }
  if (node.permissionMode === "READ_ONLY") {
    return 0x60a5fa;
  }
  return 0x34d399;
}

export function createSpatialScene({
  container,
  labelElements,
  reducedMotion,
}: SpatialSceneOptions): SpatialSceneHandle {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(46, 1, 0.1, 100);
  camera.position.set(0, 0.35, 8.4);

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.style.width = "100%";
  renderer.domElement.style.height = "100%";
  renderer.domElement.style.display = "block";
  container.appendChild(renderer.domElement);

  const disposables: Array<{ dispose: () => void }> = [];
  const track = <T extends { dispose: () => void }>(item: T): T => {
    disposables.push(item);
    return item;
  };

  const coreGroup = new THREE.Group();
  scene.add(coreGroup);

  // --- Central core -------------------------------------------------------
  const wireframeMaterial = track(
    new THREE.MeshBasicMaterial({
      color: TONE_COLORS.healthy,
      wireframe: true,
      transparent: true,
      opacity: 0.34,
    }),
  );
  const outerWire = new THREE.Mesh(
    track(new THREE.IcosahedronGeometry(1.62, 1)),
    wireframeMaterial,
  );
  coreGroup.add(outerWire);

  const innerWireMaterial = track(
    new THREE.MeshBasicMaterial({
      color: TONE_COLORS.healthy,
      wireframe: true,
      transparent: true,
      opacity: 0.16,
    }),
  );
  const innerWire = new THREE.Mesh(
    track(new THREE.IcosahedronGeometry(1.24, 0)),
    innerWireMaterial,
  );
  coreGroup.add(innerWire);

  const orbMaterial = track(
    new THREE.MeshStandardMaterial({
      color: TONE_COLORS.healthy,
      emissive: TONE_COLORS.healthy,
      emissiveIntensity: 1.5,
      roughness: 0.28,
      metalness: 0.62,
      transparent: true,
      opacity: 0.92,
    }),
  );
  const orb = new THREE.Mesh(track(new THREE.SphereGeometry(0.54, 40, 40)), orbMaterial);
  coreGroup.add(orb);

  const haloMaterial = track(
    new THREE.MeshBasicMaterial({
      color: TONE_COLORS.healthy,
      transparent: true,
      opacity: 0.12,
      side: THREE.BackSide,
    }),
  );
  const halo = new THREE.Mesh(track(new THREE.SphereGeometry(0.86, 32, 32)), haloMaterial);
  coreGroup.add(halo);

  const coreLight = new THREE.PointLight(TONE_COLORS.healthy, 2.4, 12, 2);
  coreGroup.add(coreLight);
  scene.add(new THREE.AmbientLight(0x334155, 1.1));

  // --- Orbiting particle ring --------------------------------------------
  const PARTICLES = 720;
  const particlePositions = new Float32Array(PARTICLES * 3);
  for (let index = 0; index < PARTICLES; index += 1) {
    const angle = (index / PARTICLES) * Math.PI * 2;
    const radius = 2.05 + Math.random() * 0.5;
    const wobble = (Math.random() - 0.5) * 0.22;
    particlePositions[index * 3] = Math.cos(angle) * radius;
    particlePositions[index * 3 + 1] = wobble;
    particlePositions[index * 3 + 2] = Math.sin(angle) * radius;
  }
  const particleGeometry = track(new THREE.BufferGeometry());
  particleGeometry.setAttribute(
    "position",
    new THREE.BufferAttribute(particlePositions, 3),
  );
  const particleMaterial = track(
    new THREE.PointsMaterial({
      color: TONE_COLORS.healthy,
      size: 0.028,
      transparent: true,
      opacity: 0.75,
      sizeAttenuation: true,
      depthWrite: false,
    }),
  );
  const particleRing = new THREE.Points(particleGeometry, particleMaterial);
  particleRing.rotation.x = Math.PI / 2.6;
  coreGroup.add(particleRing);

  // --- Orbiting MCP nodes + energy conduits -------------------------------
  const NODE_COUNT = 4;
  const nodeGroup = new THREE.Group();
  coreGroup.add(nodeGroup);

  const conduitMaterial = track(
    new THREE.MeshBasicMaterial({
      color: 0x10b981,
      transparent: true,
      opacity: 0.26,
    }),
  );

  const nodeMeshes: THREE.Mesh[] = [];
  const nodePositions: THREE.Vector3[] = [];

  for (let index = 0; index < NODE_COUNT; index += 1) {
    const angle = (index / NODE_COUNT) * Math.PI * 2;
    const radius = 3.05;
    const position = new THREE.Vector3(
      Math.cos(angle) * radius,
      Math.sin(angle * 1.4) * 0.62,
      Math.sin(angle) * radius,
    );
    nodePositions.push(position);

    const material = track(
      new THREE.MeshStandardMaterial({
        color: 0x34d399,
        emissive: 0x34d399,
        emissiveIntensity: 1.1,
        metalness: 0.5,
        roughness: 0.35,
      }),
    );
    const mesh = new THREE.Mesh(track(new THREE.OctahedronGeometry(0.2, 0)), material);
    mesh.position.copy(position);
    nodeMeshes.push(mesh);
    nodeGroup.add(mesh);

    const curve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0, 0, 0),
      position.clone().multiplyScalar(0.42).add(new THREE.Vector3(0, 0.22, 0)),
      position.clone().multiplyScalar(0.78).add(new THREE.Vector3(0, -0.16, 0)),
      position.clone(),
    ]);
    const conduit = new THREE.Mesh(
      track(new THREE.TubeGeometry(curve, 42, 0.012, 6, false)),
      conduitMaterial,
    );
    nodeGroup.add(conduit);
  }

  // --- Shockwave rings ----------------------------------------------------
  const shockwaves: Array<{
    mesh: THREE.Mesh;
    material: THREE.MeshBasicMaterial;
    born: number;
  }> = [];
  const shockGeometry = track(new THREE.TorusGeometry(1.2, 0.018, 8, 96));

  const triggerShockwave = () => {
    const material = new THREE.MeshBasicMaterial({
      color: TONE_COLORS.healthy,
      transparent: true,
      opacity: 0.9,
    });
    const mesh = new THREE.Mesh(shockGeometry, material);
    mesh.rotation.x = Math.PI / 2;
    coreGroup.add(mesh);
    shockwaves.push({ mesh, material, born: performance.now() });
  };

  // --- Interaction --------------------------------------------------------
  const pointer = { x: 0, y: 0 };
  const smoothed = { x: 0, y: 0 };
  const onPointerMove = (event: PointerEvent) => {
    pointer.x = (event.clientX / window.innerWidth) * 2 - 1;
    pointer.y = (event.clientY / window.innerHeight) * 2 - 1;
  };
  const onPointerLeave = () => {
    pointer.x = 0;
    pointer.y = 0;
  };
  window.addEventListener("pointermove", onPointerMove, { passive: true });
  window.addEventListener("pointerleave", onPointerLeave);

  let active = true;
  let tone: CoreTone = "healthy";
  let nodes: SpatialNode[] = [];
  let frameId = 0;
  let lastTime = performance.now();

  const applyTone = () => {
    const color = TONE_COLORS[tone];
    wireframeMaterial.color.setHex(color);
    innerWireMaterial.color.setHex(color);
    orbMaterial.color.setHex(color);
    orbMaterial.emissive.setHex(color);
    haloMaterial.color.setHex(color);
    particleMaterial.color.setHex(color);
    coreLight.color.setHex(color);
    orbMaterial.emissiveIntensity = tone === "healthy" ? 1.5 : 2.2;
  };

  const applyNodes = () => {
    nodeMeshes.forEach((mesh, index) => {
      const node = nodes[index];
      const color = node ? nodeColor(node) : 0x52525b;
      const material = mesh.material as THREE.MeshStandardMaterial;
      material.color.setHex(color);
      material.emissive.setHex(color);
    });
    conduitMaterial.color.setHex(TONE_COLORS[tone]);
  };

  const resize = () => {
    const width = container.clientWidth || 1;
    const height = container.clientHeight || 1;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
  };
  resize();

  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(container);

  const projected = new THREE.Vector3();

  const updateLabels = () => {
    const width = container.clientWidth || 1;
    const height = container.clientHeight || 1;
    nodeMeshes.forEach((mesh, index) => {
      const element = labelElements[index];
      if (!element) return;
      mesh.getWorldPosition(projected);
      projected.project(camera);
      const x = (projected.x * 0.5 + 0.5) * width;
      const y = (-projected.y * 0.5 + 0.5) * height;
      const depth = THREE.MathUtils.clamp(1 - (projected.z + 1) / 2, 0, 1);
      element.style.transform = `translate(-50%, -50%) translate(${x.toFixed(1)}px, ${(y - 34).toFixed(1)}px)`;
      element.style.opacity = `${(0.35 + depth * 0.65).toFixed(3)}`;
    });
  };

  const animate = (now: number) => {
    frameId = requestAnimationFrame(animate);
    if (!active || document.hidden) {
      lastTime = now;
      return;
    }
    const delta = Math.min((now - lastTime) / 1000, 0.05);
    lastTime = now;
    const speed = reducedMotion ? 0.15 : 1;

    smoothed.x += (pointer.x - smoothed.x) * 0.045;
    smoothed.y += (pointer.y - smoothed.y) * 0.045;

    coreGroup.rotation.y += delta * 0.24 * speed;
    nodeGroup.rotation.y -= delta * 0.16 * speed;
    outerWire.rotation.x += delta * 0.12 * speed;
    outerWire.rotation.z += delta * 0.05 * speed;
    innerWire.rotation.x -= delta * 0.2 * speed;
    innerWire.rotation.y += delta * 0.14 * speed;
    particleRing.rotation.z += delta * 0.1 * speed;

    const pulse = 1 + Math.sin(now / 620) * 0.035;
    orb.scale.setScalar(pulse);
    halo.scale.setScalar(1 + Math.sin(now / 900) * 0.06);

    camera.position.x = smoothed.x * 0.75;
    camera.position.y = 0.35 - smoothed.y * 0.45;
    camera.lookAt(0, 0, 0);

    for (let index = shockwaves.length - 1; index >= 0; index -= 1) {
      const wave = shockwaves[index];
      const age = (now - wave.born) / 1400;
      if (age >= 1) {
        coreGroup.remove(wave.mesh);
        wave.material.dispose();
        shockwaves.splice(index, 1);
        continue;
      }
      const scale = 0.4 + age * 3.6;
      wave.mesh.scale.setScalar(scale);
      wave.material.opacity = 0.85 * (1 - age);
    }

    updateLabels();
    renderer.render(scene, camera);
  };
  frameId = requestAnimationFrame(animate);

  return {
    setTone: (next) => {
      if (next === tone) return;
      tone = next;
      applyTone();
      applyNodes();
    },
    setNodes: (next) => {
      nodes = next.slice(0, NODE_COUNT);
      applyNodes();
    },
    shockwave: triggerShockwave,
    setActive: (next) => {
      active = next;
      lastTime = performance.now();
    },
    dispose: () => {
      cancelAnimationFrame(frameId);
      resizeObserver.disconnect();
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerleave", onPointerLeave);
      shockwaves.forEach((wave) => {
        coreGroup.remove(wave.mesh);
        wave.material.dispose();
      });
      disposables.forEach((item) => item.dispose());
      renderer.dispose();
      if (renderer.domElement.parentElement === container) {
        container.removeChild(renderer.domElement);
      }
    },
  };
}

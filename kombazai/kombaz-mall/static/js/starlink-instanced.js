/**
 * starlink-instanced.js
 * KOMBAZ.ME — Optimized Starlink constellation
 * Uses THREE.InstancedMesh for GPU-efficient rendering
 * Load after Three.js
 */

window.createStarlinkInstanced = function(scene, earthMesh, count = 36) {
  if (!window.THREE) return null;

  const geo = new THREE.BoxGeometry(0.1, 0.02, 0.07);
  const mat = new THREE.MeshStandardMaterial({
    color: 0x9090bb, metalness: 0.72, roughness: 0.25
  });

  const mesh = new THREE.InstancedMesh(geo, mat, count);
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  scene.add(mesh);

  // Pre-compute orbital params
  const orbits = Array.from({ length: count }, (_, i) => ({
    a:   (i / count) * Math.PI * 2,
    inc: (Math.random() - 0.5) * 0.4,
    r:   4.5 * 1.14 + Math.random() * 1.4  // earth radius * 1.14
  }));

  const dummy = new THREE.Object3D();

  function update(T) {
    const ep = earthMesh ? earthMesh.position : new THREE.Vector3();
    orbits.forEach((o, i) => {
      const a   = o.a + T * (0.12 + o.r * 0.002);
      const cos = Math.cos(a) * o.r * Math.cos(o.inc);
      const sin = Math.sin(a) * o.r * Math.cos(o.inc);
      const y   = Math.sin(o.inc) * o.r;

      dummy.position.set(ep.x + cos, ep.y + y, ep.z + sin);
      dummy.lookAt(ep);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  }

  return { mesh, update };
};

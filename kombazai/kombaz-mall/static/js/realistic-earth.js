// realistic-earth.js
// Google Maps style Earth with detailed continents

(function() {
  'use strict';
  
  console.log('🗺️ Google Maps Earth loading...');
  
  function init() {
    if (typeof THREE === 'undefined') {
      setTimeout(init, 100);
      return;
    }
    setTimeout(findAndUpgradeEarth, 3000);
  }
  
  function createGoogleMapsTexture() {
    // High resolution canvas
    const canvas = document.createElement('canvas');
    canvas.width = 4096;
    canvas.height = 2048;
    const ctx = canvas.getContext('2d');
    
    // ═══════════════════════════════════════════
    // OCEAN — Google Maps blue
    // ═══════════════════════════════════════════
    const oceanGradient = ctx.createLinearGradient(0, 0, 0, 2048);
    oceanGradient.addColorStop(0, '#a3ccff');
    oceanGradient.addColorStop(0.5, '#aadaff');
    oceanGradient.addColorStop(1, '#a3ccff');
    ctx.fillStyle = oceanGradient;
    ctx.fillRect(0, 0, 4096, 2048);
    
    // ═══════════════════════════════════════════
    // CONTINENTS — Google Maps land color
    // ═══════════════════════════════════════════
    
    const landColor = '#f5f1e8';      // Light beige (Google Maps)
    const grassColor = '#c8d8a0';     // Light green
    const desertColor = '#e8d4a0';    // Desert beige
    const mountainColor = '#b8a888';  // Mountain brown
    const forestColor = '#a3c293';    // Forest green
    
    // ═══════════════════════════════════════════
    // NORTH AMERICA
    // ═══════════════════════════════════════════
    ctx.fillStyle = landColor;
    ctx.beginPath();
    // Alaska
    ctx.moveTo(180, 380);
    ctx.lineTo(380, 350);
    ctx.lineTo(450, 380);
    // Canada
    ctx.lineTo(900, 350);
    ctx.lineTo(950, 400);
    ctx.lineTo(1000, 450);
    // East Coast
    ctx.lineTo(980, 550);
    ctx.lineTo(950, 650);
    // Florida
    ctx.lineTo(880, 750);
    ctx.lineTo(850, 770);
    // Gulf of Mexico
    ctx.lineTo(750, 760);
    ctx.lineTo(700, 780);
    // Mexico
    ctx.lineTo(680, 850);
    ctx.lineTo(620, 880);
    // West Coast (US)
    ctx.lineTo(500, 850);
    ctx.lineTo(450, 700);
    ctx.lineTo(400, 600);
    ctx.lineTo(350, 500);
    ctx.lineTo(280, 450);
    ctx.lineTo(180, 380);
    ctx.closePath();
    ctx.fill();
    
    // Greenland
    ctx.beginPath();
    ctx.moveTo(1100, 250);
    ctx.lineTo(1300, 240);
    ctx.lineTo(1380, 350);
    ctx.lineTo(1320, 480);
    ctx.lineTo(1180, 460);
    ctx.lineTo(1080, 380);
    ctx.closePath();
    ctx.fill();
    
    // Forests of Canada (green)
    ctx.fillStyle = forestColor;
    ctx.beginPath();
    ctx.moveTo(450, 480);
    ctx.lineTo(900, 470);
    ctx.lineTo(880, 580);
    ctx.lineTo(450, 590);
    ctx.closePath();
    ctx.fill();
    
    // Rocky Mountains
    ctx.fillStyle = mountainColor;
    ctx.beginPath();
    ctx.moveTo(450, 500);
    ctx.lineTo(550, 480);
    ctx.lineTo(580, 700);
    ctx.lineTo(480, 720);
    ctx.closePath();
    ctx.fill();
    
    // Desert (US Southwest)
    ctx.fillStyle = desertColor;
    ctx.beginPath();
    ctx.moveTo(550, 700);
    ctx.lineTo(700, 720);
    ctx.lineTo(680, 850);
    ctx.lineTo(560, 830);
    ctx.closePath();
    ctx.fill();
    
    // ═══════════════════════════════════════════
    // SOUTH AMERICA
    // ═══════════════════════════════════════════
    ctx.fillStyle = forestColor;
    ctx.beginPath();
    ctx.moveTo(900, 950);
    ctx.lineTo(1100, 920);
    ctx.lineTo(1180, 1000);
    ctx.lineTo(1200, 1200);
    ctx.lineTo(1150, 1400);
    ctx.lineTo(1050, 1550);
    ctx.lineTo(950, 1600);
    ctx.lineTo(880, 1500);
    ctx.lineTo(850, 1300);
    ctx.lineTo(820, 1100);
    ctx.lineTo(880, 1000);
    ctx.closePath();
    ctx.fill();
    
    // Andes Mountains
    ctx.fillStyle = mountainColor;
    ctx.beginPath();
    ctx.moveTo(890, 1000);
    ctx.lineTo(940, 990);
    ctx.lineTo(950, 1500);
    ctx.lineTo(900, 1520);
    ctx.closePath();
    ctx.fill();
    
    // ═══════════════════════════════════════════
    // EUROPE
    // ═══════════════════════════════════════════
    ctx.fillStyle = grassColor;
    ctx.beginPath();
    // Scandinavia
    ctx.moveTo(2050, 350);
    ctx.lineTo(2200, 320);
    ctx.lineTo(2280, 400);
    ctx.lineTo(2250, 500);
    // Europe mainland
    ctx.lineTo(2300, 600);
    ctx.lineTo(2280, 700);
    ctx.lineTo(2200, 750);
    // Spain/Portugal
    ctx.lineTo(2100, 770);
    ctx.lineTo(2000, 760);
    ctx.lineTo(1950, 700);
    ctx.lineTo(1980, 600);
    ctx.lineTo(2000, 500);
    ctx.lineTo(2050, 400);
    ctx.closePath();
    ctx.fill();
    
    // British Isles
    ctx.beginPath();
    ctx.arc(1980, 520, 40, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(1940, 540, 25, 0, Math.PI * 2);
    ctx.fill();
    
    // Alps
    ctx.fillStyle = mountainColor;
    ctx.beginPath();
    ctx.moveTo(2150, 650);
    ctx.lineTo(2280, 640);
    ctx.lineTo(2270, 680);
    ctx.lineTo(2160, 690);
    ctx.closePath();
    ctx.fill();
    
    // ═══════════════════════════════════════════
    // AFRICA
    // ═══════════════════════════════════════════
    
    // Sahara Desert
    ctx.fillStyle = desertColor;
    ctx.beginPath();
    ctx.moveTo(2050, 800);
    ctx.lineTo(2400, 780);
    ctx.lineTo(2500, 850);
    ctx.lineTo(2480, 1000);
    ctx.lineTo(2050, 1020);
    ctx.lineTo(2000, 900);
    ctx.closePath();
    ctx.fill();
    
    // Central Africa (forest)
    ctx.fillStyle = forestColor;
    ctx.beginPath();
    ctx.moveTo(2050, 1020);
    ctx.lineTo(2480, 1000);
    ctx.lineTo(2500, 1200);
    ctx.lineTo(2400, 1400);
    ctx.lineTo(2300, 1500);
    ctx.lineTo(2200, 1500);
    ctx.lineTo(2100, 1400);
    ctx.lineTo(2050, 1200);
    ctx.closePath();
    ctx.fill();
    
    // Madagascar
    ctx.fillStyle = grassColor;
    ctx.beginPath();
    ctx.ellipse(2580, 1380, 30, 80, 0.2, 0, Math.PI * 2);
    ctx.fill();
    
    // ═══════════════════════════════════════════
    // ASIA
    // ═══════════════════════════════════════════
    ctx.fillStyle = grassColor;
    ctx.beginPath();
    // Russia
    ctx.moveTo(2280, 380);
    ctx.lineTo(3500, 350);
    ctx.lineTo(3700, 400);
    ctx.lineTo(3800, 500);
    // East Asia
    ctx.lineTo(3700, 650);
    ctx.lineTo(3500, 750);
    // China
    ctx.lineTo(3400, 850);
    ctx.lineTo(3200, 900);
    // India
    ctx.lineTo(3000, 950);
    ctx.lineTo(2950, 1050);
    ctx.lineTo(2900, 1100);
    ctx.lineTo(2800, 1080);
    ctx.lineTo(2750, 1000);
    ctx.lineTo(2700, 900);
    // Middle East
    ctx.lineTo(2600, 850);
    ctx.lineTo(2550, 800);
    ctx.lineTo(2500, 750);
    // Back to Europe
    ctx.lineTo(2350, 600);
    ctx.lineTo(2300, 500);
    ctx.lineTo(2280, 380);
    ctx.closePath();
    ctx.fill();
    
    // Himalayas
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.moveTo(2950, 850);
    ctx.lineTo(3200, 840);
    ctx.lineTo(3180, 880);
    ctx.lineTo(2960, 890);
    ctx.closePath();
    ctx.fill();
    
    // Gobi Desert
    ctx.fillStyle = desertColor;
    ctx.beginPath();
    ctx.ellipse(3300, 750, 200, 60, 0, 0, Math.PI * 2);
    ctx.fill();
    
    // ═══════════════════════════════════════════
    // SOUTHEAST ASIA & INDONESIA
    // ═══════════════════════════════════════════
    ctx.fillStyle = forestColor;
    
    // Indochina
    ctx.beginPath();
    ctx.moveTo(3300, 1000);
    ctx.lineTo(3450, 990);
    ctx.lineTo(3470, 1100);
    ctx.lineTo(3380, 1150);
    ctx.lineTo(3300, 1100);
    ctx.closePath();
    ctx.fill();
    
    // Indonesia islands
    [
      [3400, 1250], [3500, 1280], [3600, 1300],
      [3700, 1320], [3450, 1340], [3550, 1360]
    ].forEach(([x, y]) => {
      ctx.beginPath();
      ctx.ellipse(x, y, 60, 25, Math.random() * Math.PI, 0, Math.PI * 2);
      ctx.fill();
    });
    
    // Philippines
    ctx.beginPath();
    ctx.ellipse(3650, 1100, 30, 80, 0.3, 0, Math.PI * 2);
    ctx.fill();
    
    // Japan
    ctx.beginPath();
    ctx.ellipse(3780, 700, 30, 100, 0.4, 0, Math.PI * 2);
    ctx.fill();
    
    // ═══════════════════════════════════════════
    // AUSTRALIA
    // ═══════════════════════════════════════════
    ctx.fillStyle = desertColor;
    ctx.beginPath();
    ctx.moveTo(3500, 1450);
    ctx.lineTo(3800, 1450);
    ctx.lineTo(3850, 1550);
    ctx.lineTo(3800, 1650);
    ctx.lineTo(3500, 1680);
    ctx.lineTo(3400, 1600);
    ctx.lineTo(3450, 1500);
    ctx.closePath();
    ctx.fill();
    
    // East coast (green)
    ctx.fillStyle = grassColor;
    ctx.beginPath();
    ctx.moveTo(3750, 1450);
    ctx.lineTo(3850, 1480);
    ctx.lineTo(3870, 1600);
    ctx.lineTo(3800, 1660);
    ctx.lineTo(3750, 1500);
    ctx.closePath();
    ctx.fill();
    
    // New Zealand
    ctx.beginPath();
    ctx.ellipse(3950, 1700, 30, 60, 0.3, 0, Math.PI * 2);
    ctx.fill();
    
    // ═══════════════════════════════════════════
    // ANTARCTICA
    // ═══════════════════════════════════════════
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 1850, 4096, 200);
    
    // ═══════════════════════════════════════════
    // BORDERS / GRID (Google Maps style)
    // ═══════════════════════════════════════════
    ctx.strokeStyle = 'rgba(150, 150, 150, 0.2)';
    ctx.lineWidth = 1;
    
    // Latitude lines
    for (let y = 0; y < 2048; y += 200) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(4096, y);
      ctx.stroke();
    }
    
    // Longitude lines
    for (let x = 0; x < 4096; x += 200) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, 2048);
      ctx.stroke();
    }
    
    return canvas;
  }
  
  function findAndUpgradeEarth() {
    const scene = findScene();
    
    if (!scene) {
      console.log('⏳ Waiting for scene...');
      setTimeout(findAndUpgradeEarth, 1000);
      return;
    }
    
    // Find ALL spheres and upgrade the most likely Earth
    const spheres = [];
    scene.traverse((obj) => {
      if (obj.isMesh && obj.geometry && obj.geometry.type === 'SphereGeometry') {
        const radius = obj.geometry.parameters.radius;
        if (radius && radius > 0.5 && radius < 5) {
          spheres.push({mesh: obj, radius: radius, distance: obj.position.length()});
        }
      }
    });
    
    if (spheres.length === 0) {
      console.log('❌ No spheres found');
      return;
    }
    
    // Sort by likelihood of being Earth (medium size, has color)
    spheres.sort((a, b) => {
      const aHasColor = a.mesh.material && a.mesh.material.color;
      const bHasColor = b.mesh.material && b.mesh.material.color;
      
      if (aHasColor && !bHasColor) return -1;
      if (!aHasColor && bHasColor) return 1;
      
      // Prefer blue/green colored spheres
      if (aHasColor && bHasColor) {
        const aBlue = a.mesh.material.color.b > 0.3;
        const bBlue = b.mesh.material.color.b > 0.3;
        if (aBlue && !bBlue) return -1;
        if (!aBlue && bBlue) return 1;
      }
      
      return 0;
    });
    
    const earthMesh = spheres[0].mesh;
    console.log('🌍 Earth identified, upgrading...');
    
    // Create Google Maps style texture
    const canvas = createGoogleMapsTexture();
    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    
    // Create realistic material
    const newMaterial = new THREE.MeshPhongMaterial({
      map: texture,
      shininess: 30,
      specular: new THREE.Color(0x333344),
      bumpScale: 0.05
    });
    
    // Apply
    if (earthMesh.material) {
      earthMesh.material.dispose();
    }
    earthMesh.material = newMaterial;
    
    // Add atmosphere
    const radius = earthMesh.geometry.parameters.radius;
    const atmosphereGeometry = new THREE.SphereGeometry(radius * 1.08, 64, 64);
    const atmosphereMaterial = new THREE.ShaderMaterial({
      uniforms: {
        glowColor: { value: new THREE.Color(0x4a9eff) }
      },
      vertexShader: `
        varying vec3 vNormal;
        void main() {
          vNormal = normalize(normalMatrix * normal);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        uniform vec3 glowColor;
        varying vec3 vNormal;
        void main() {
          float intensity = pow(0.65 - dot(vNormal, vec3(0, 0, 1.0)), 2.0);
          gl_FragColor = vec4(glowColor, intensity * 0.7);
        }
      `,
      side: THREE.BackSide,
      blending: THREE.AdditiveBlending,
      transparent: true
    });
    
    const atmosphere = new THREE.Mesh(atmosphereGeometry, atmosphereMaterial);
    atmosphere.name = 'earth_atmosphere';
    earthMesh.add(atmosphere);
    
    console.log('✅ Earth upgraded to Google Maps style!');
    console.log('🌐 Atmosphere added');
  }
  
  function findScene() {
    if (window.scene && window.scene.isScene) return window.scene;
    if (window.SCENE && window.SCENE.isScene) return window.SCENE;
    
    for (let key in window) {
      try {
        if (window[key] && window[key].isScene) {
          return window[key];
        }
      } catch(e) {}
    }
    return null;
  }
  
  if (document.readyState === 'complete') {
    init();
  } else {
    window.addEventListener('load', init);
  }
})();
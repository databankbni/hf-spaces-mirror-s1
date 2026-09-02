// ========== 3D CHOPPER MASCOT ==========
// Uses Three.js (loaded globally) to render an animated Chopper in the navbar
// Works with file://, Hugging Face Spaces, GitHub Pages — any static host

(function() {
  'use strict';

  // ========== CONFIG ==========
  var CONFIG = {
    modelPath: 'resources/chopper.glb',
    walkSpeed: 0.3,
    walkRange: 0.6,
    waveDuration: 6000,
    waveInterval: 12000,
    angryDuration: 3000,
    idleTimeout: 8000,
  };

  // ========== STATE ==========
  var mixer = null;
  var model = null;
  var clock = null;
  var renderer = null;
  var scene = null;
  var camera = null;
  var actions = {};
  var currentAction = null;
  var walkDirection = 1;
  var isAngry = false;
  var isWaving = false;
  var isSadIdle = false;
  var lastUserActivity = Date.now();

  // ========== SETUP ==========
  function init() {
    var canvas = document.getElementById('chopperCanvas');
    if (!canvas || typeof THREE === 'undefined') return;

    var container = canvas.parentElement;
    var width = container.clientWidth;
    var height = container.clientHeight;

    // Renderer
    renderer = new THREE.WebGLRenderer({
      canvas: canvas,
      alpha: true,
      antialias: true,
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputEncoding = THREE.sRGBEncoding;

    // Scene
    scene = new THREE.Scene();

    // Camera — orthographic for consistent sizing
    var aspect = width / height;
    var frustum = 0.7;
    camera = new THREE.OrthographicCamera(
      -frustum * aspect, frustum * aspect,
      frustum, -frustum,
      0.1, 100
    );
    camera.position.set(0, 0.3, 3);
    camera.lookAt(0, 0, 0);

    // Lights
    scene.add(new THREE.AmbientLight(0xffffff, 1.6));

    var dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
    dirLight.position.set(2, 3, 4);
    scene.add(dirLight);

    var fillLight = new THREE.DirectionalLight(0x88ccff, 0.5);
    fillLight.position.set(-2, 1, -2);
    scene.add(fillLight);

    // Clock
    clock = new THREE.Clock();

    // Load model
    var loader = new THREE.GLTFLoader();
    loader.load(
      CONFIG.modelPath,
      function(gltf) { onModelLoaded(gltf); },
      undefined,
      function(err) {
        console.warn('Chopper GLB failed to load (normal on file://):', err);
        showFallback(container);
      }
    );

    // Click handler
    container.addEventListener('click', onChopperClick);

    // Track user activity
    ['mousemove', 'scroll', 'keydown', 'click', 'touchstart'].forEach(function(evt) {
      document.addEventListener(evt, function() { lastUserActivity = Date.now(); }, { passive: true });
    });

    // Idle checker
    setInterval(checkUserIdle, 2000);

    // Animate loop
    animate();
  }

  // ========== MODEL LOADED ==========
  function onModelLoaded(gltf) {
    model = gltf.scene;
    
    // Auto-scale and center the model
    var box = new THREE.Box3().setFromObject(model);
    var size = box.getSize(new THREE.Vector3());
    var center = box.getCenter(new THREE.Vector3());
    var maxDim = Math.max(size.x, size.y, size.z);
    
    if (maxDim > 0) {
      var scale = 1.0 / maxDim;
      model.scale.set(scale, scale, scale);
    }
    
    // Recompute box after scale to center it exactly at (0,0,0)
    box.setFromObject(model);
    box.getCenter(center);
    model.position.sub(center);
    model.position.x += 0.3; // Shift slightly to the right so left horn is visible
    
    scene.add(model);

    // Setup animation mixer
    mixer = new THREE.AnimationMixer(model);

    // Map animations by name
    gltf.animations.forEach(function(clip) {
      var name = clip.name.toLowerCase();
      actions[name] = mixer.clipAction(clip);

      if (name === 'walking' || name === 'sad_idle' || name === 'wave') {
        actions[name].setLoop(THREE.LoopRepeat);
      } else {
        actions[name].setLoop(THREE.LoopOnce);
        actions[name].clampWhenFinished = true;
      }
    });

    console.log('Chopper animations loaded:', Object.keys(actions));

    // Start walking
    playAction('walking');

    // Setup periodic wave
    scheduleWave();
  }

  // ========== ANIMATION CONTROL ==========
  function playAction(name, fadeDuration) {
    fadeDuration = fadeDuration || 0.4;
    if (!actions[name]) return;
    if (currentAction === name) return;

    // Fade out current
    if (currentAction && actions[currentAction]) {
      actions[currentAction].fadeOut(fadeDuration);
    }

    // Play new
    actions[name].reset().fadeIn(fadeDuration).play();
    currentAction = name;
  }

  // ========== WALKING LOGIC ==========
  function updateWalk(delta) {
    // Translation removed completely. Chopper stays perfectly in the center.
    // He will "walk in place" (or just animate) without moving left/right.
    if (!model) return;
    model.rotation.y = 0; // Always face forward
  }

  // ========== CLICK → ANGRY ==========
  function onChopperClick() {
    if (isAngry || !mixer) return;
    isAngry = true;
    isSadIdle = false;

    playAction('angry', 0.25);

    var onFinished = function(e) {
      if (e.action === actions['angry']) {
        mixer.removeEventListener('finished', onFinished);
        isAngry = false;
        playAction('walking', 0.4);
      }
    };
    mixer.addEventListener('finished', onFinished);

    // Safety fallback
    setTimeout(function() {
      if (isAngry) {
        isAngry = false;
        playAction('walking', 0.4);
      }
    }, CONFIG.angryDuration);
  }

  // ========== PERIODIC WAVE ==========
  function scheduleWave() {
    setInterval(function() {
      if (isAngry || isWaving || isSadIdle) return;
      isWaving = true;

      if (model) model.rotation.y = 0;
      playAction('wave', 0.3);

      var onFinished = function(e) {
        if (e.action === actions['wave']) {
          mixer.removeEventListener('finished', onFinished);
          isWaving = false;
          playAction('walking', 0.4);
        }
      };
      mixer.addEventListener('finished', onFinished);

      setTimeout(function() {
        if (isWaving) {
          isWaving = false;
          playAction('walking', 0.4);
        }
      }, CONFIG.waveDuration);
    }, CONFIG.waveInterval);
  }

  // ========== IDLE → SAD ==========
  function checkUserIdle() {
    var elapsed = Date.now() - lastUserActivity;

    if (elapsed > CONFIG.idleTimeout && !isSadIdle && !isAngry && !isWaving) {
      isSadIdle = true;
      if (model) model.rotation.y = 0;
      playAction('sad_idle', 0.6);
    }

    if (elapsed < CONFIG.idleTimeout && isSadIdle) {
      isSadIdle = false;
      playAction('walking', 0.5);
    }
  }

  // ========== RENDER LOOP ==========
  function animate() {
    requestAnimationFrame(animate);
    if (!clock) return;

    var delta = clock.getDelta();
    if (mixer) mixer.update(delta);
    updateWalk(delta);

    if (renderer && scene && camera) {
      renderer.render(scene, camera);
    }
  }

  // ========== RESIZE ==========
  window.addEventListener('resize', function() {
    var container = document.querySelector('.navbar__chopper-container');
    if (!container || !renderer || !camera) return;

    var width = container.clientWidth;
    var height = container.clientHeight;
    var aspect = width / height;
    var frustum = 0.7;

    camera.left = -frustum * aspect;
    camera.right = frustum * aspect;
    camera.top = frustum;
    camera.bottom = -frustum;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  });

  // ========== FALLBACK (for file:// protocol) ==========
  function showFallback(container) {
    // Hide the canvas
    var canvas = container.querySelector('canvas');
    if (canvas) canvas.style.display = 'none';

    // Show a cute emoji fallback
    var fallback = document.createElement('span');
    fallback.textContent = '👾';
    fallback.style.cssText = 'font-size:1.8rem;display:flex;align-items:center;justify-content:center;width:100%;height:100%;cursor:default;animation:chopperBounce 2s ease-in-out infinite;';
    container.appendChild(fallback);

    // Add bounce animation
    var style = document.createElement('style');
    style.textContent = '@keyframes chopperBounce{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}';
    document.head.appendChild(style);
  }

  // ========== START ==========
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();

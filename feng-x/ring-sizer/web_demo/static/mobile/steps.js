// Tiny linear step controller for the mobile flow.
//
// Each step registers a `mount(container)` function that paints itself
// into the supplied DOM container, plus an optional `unmount()` for
// cleanup (e.g. tearing down a camera stream when leaving the capture
// step). The controller maintains an index into a fixed step order and
// exposes `next()` / `back()` / `goTo(name)` for transitions.
//
// Deliberately minimal: no transitions, no history-API integration, no
// deep-linking. Five linear steps with back/forward — anything fancier
// can be added when the UX calls for it.

const stepRegistry = new Map();
let order = [];
let currentIndex = -1;
let currentStep = null;
let rootContainer = null;

export function registerStep(name, step) {
  if (typeof step.mount !== "function") {
    throw new Error(`Step "${name}" must define mount(container)`);
  }
  stepRegistry.set(name, step);
}

export function setOrder(names) {
  for (const name of names) {
    if (!stepRegistry.has(name)) {
      throw new Error(`Step "${name}" is not registered`);
    }
  }
  order = [...names];
}

export function start(container) {
  rootContainer = container;
  if (!order.length) throw new Error("setOrder() must be called before start()");
  goTo(order[0]);
}

// `data` is an optional payload handed to the destination step's
// mount() — used by the capture step to forward the measurement result
// to the result step. Steps that don't need data can ignore the third
// argument; steps that need persistent state should still maintain it
// themselves (the controller doesn't survive a hard reload).
export function goTo(name, data) {
  const idx = order.indexOf(name);
  if (idx === -1) throw new Error(`Step "${name}" is not in the active order`);
  if (currentStep && typeof currentStep.unmount === "function") {
    try {
      currentStep.unmount();
    } catch (err) {
      console.error(`Step "${order[currentIndex]}" unmount failed:`, err);
    }
  }
  rootContainer.innerHTML = "";
  currentIndex = idx;
  currentStep = stepRegistry.get(name);
  // Pass a small `nav` API down so steps don't need to import this
  // module — keeps each step file standalone and easy to test.
  const nav = {
    next: (payload) => {
      if (currentIndex < order.length - 1) goTo(order[currentIndex + 1], payload);
    },
    back: (payload) => {
      if (currentIndex > 0) goTo(order[currentIndex - 1], payload);
    },
    goTo,
    isFirst: () => currentIndex === 0,
    isLast: () => currentIndex === order.length - 1,
    progress: () => ({ index: currentIndex, total: order.length }),
  };
  currentStep.mount(rootContainer, nav, data);
}

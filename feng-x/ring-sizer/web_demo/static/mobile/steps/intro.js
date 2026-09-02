// Step 1 — Intro / value prop.
// Mirrors the desktop hero copy: red eyebrow, large display headline,
// muted sub-line. No panel — this lives directly on the gradient
// background, same as the desktop column-left treatment.

export default {
  mount(container, nav) {
    container.innerHTML = `
      <section class="step step-intro">
        <div class="step-body">
          <p class="hero-eyebrow">Femometer Smart Ring Sizer</p>
          <h1 class="hero-headline">Upload a photo to quickly measure ring size</h1>
          <p class="hero-sub">
            Using a card of standard credit card size for scale reference.
          </p>
        </div>
        <footer class="step-foot">
          <button type="button" class="primary step-next">Get Started</button>
        </footer>
      </section>
    `;
    container.querySelector(".step-next").addEventListener("click", nav.next);
  },
};

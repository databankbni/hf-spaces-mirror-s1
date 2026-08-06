import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["drawer", "backdrop"]

  connect() {
    this.mediaQuery = window.matchMedia('(max-width: 1023px)')
    this.mediaQueryListener = (e) => {
      if (!e.matches) {
        // Desktop view: drawer must be interactive and not marked as hidden/inert
        if (this.hasDrawerTarget) {
          this.drawerTarget.removeAttribute("inert")
          this.drawerTarget.removeAttribute("aria-hidden")
        }
        document.body.classList.remove("overflow-hidden")
      } else {
        // Mobile view: default to closed/inert state
        if (this.hasDrawerTarget && this.drawerTarget.classList.contains("-translate-x-full")) {
          this.drawerTarget.setAttribute("inert", "")
          this.drawerTarget.setAttribute("aria-hidden", "true")
        }
      }
    }
    
    this.mediaQuery.addEventListener("change", this.mediaQueryListener)
    this.mediaQueryListener(this.mediaQuery)

    this.escapeListener = (e) => {
      if (e.key === "Escape" && this.isMobileOrTabletOpen()) {
        this.close()
      }
    }
    document.addEventListener("keydown", this.escapeListener)
  }

  disconnect() {
    if (this.mediaQuery) {
      this.mediaQuery.removeEventListener("change", this.mediaQueryListener)
    }
    document.removeEventListener("keydown", this.escapeListener)
    document.body.classList.remove("overflow-hidden")
  }

  isMobileOrTabletOpen() {
    const isMobileOrTablet = window.matchMedia('(max-width: 1023px)').matches
    return isMobileOrTablet && this.hasDrawerTarget && !this.drawerTarget.hasAttribute("inert")
  }

  open(event) {
    if (event) event.preventDefault()

    this.previouslyFocusedElement = document.activeElement

    if (this.hasDrawerTarget) {
      this.drawerTarget.classList.remove("-translate-x-full")
      this.drawerTarget.classList.add("translate-x-0")
      this.drawerTarget.removeAttribute("inert")
      this.drawerTarget.setAttribute("aria-hidden", "false")

      // Focus management: move focus to the drawer container
      setTimeout(() => {
        if (this.hasDrawerTarget) {
          this.drawerTarget.focus()
        }
      }, 50)
    }

    if (this.hasBackdropTarget) {
      this.backdropTarget.classList.remove("opacity-0", "pointer-events-none")
      this.backdropTarget.classList.add("opacity-100", "pointer-events-auto")
    }

    document.body.classList.add("overflow-hidden")
  }

  close(event) {
    if (event) event.preventDefault()

    if (this.hasDrawerTarget) {
      this.drawerTarget.classList.remove("translate-x-0")
      this.drawerTarget.classList.add("-translate-x-full")
      
      // On mobile view, mark drawer as inert and aria-hidden
      if (window.matchMedia('(max-width: 1023px)').matches) {
        this.drawerTarget.setAttribute("inert", "")
        this.drawerTarget.setAttribute("aria-hidden", "true")
      }
    }

    if (this.hasBackdropTarget) {
      this.backdropTarget.classList.remove("opacity-100", "pointer-events-auto")
      this.backdropTarget.classList.add("opacity-0", "pointer-events-none")
    }

    document.body.classList.remove("overflow-hidden")

    // Restore focus to previously focused element
    if (this.previouslyFocusedElement) {
      this.previouslyFocusedElement.focus()
      this.previouslyFocusedElement = null
    }
  }

  toggle(event) {
    if (event) event.preventDefault()

    if (this.hasDrawerTarget) {
      if (this.drawerTarget.classList.contains("-translate-x-full")) {
        this.open()
      } else {
        this.close()
      }
    }
  }
}

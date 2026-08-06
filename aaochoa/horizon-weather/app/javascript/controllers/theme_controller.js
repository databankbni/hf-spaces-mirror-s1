import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = [ "lightIcon", "darkIcon" ]

  connect() {
    this.applyTheme()
    this.setupSystemThemeListener()
  }

  disconnect() {
    if (this.mediaQuery && this.systemThemeListener) {
      this.mediaQuery.removeEventListener("change", this.systemThemeListener)
    }
  }

  setupSystemThemeListener() {
    this.mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")
    this.systemThemeListener = (e) => {
      if (!localStorage.getItem("theme")) {
        this.applyTheme()
        const event = new CustomEvent("theme-changed", { detail: { theme: e.matches ? "dark" : "light" } })
        document.dispatchEvent(event)
      }
    }
    this.mediaQuery.addEventListener("change", this.systemThemeListener)
  }

  toggle() {
    const currentTheme = this.getCurrentTheme()
    const newTheme = currentTheme === "dark" ? "light" : "dark"
    localStorage.setItem("theme", newTheme)
    this.applyTheme()
    
    // Dispatch a custom event so other components (like Leaflet map) can update
    const event = new CustomEvent("theme-changed", { detail: { theme: newTheme } })
    document.dispatchEvent(event)
  }

  getCurrentTheme() {
    if (localStorage.getItem("theme")) {
      return localStorage.getItem("theme")
    }
    return document.documentElement.classList.contains("dark") ? "dark" : "light"
  }

  applyTheme() {
    const theme = localStorage.getItem("theme") || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    
    if (theme === "dark") {
      document.documentElement.classList.add("dark")
    } else {
      document.documentElement.classList.remove("dark")
    }
    
    this.updateIcons(theme)
  }

  updateIcons(theme) {
    if (theme === "dark") {
      // In dark theme, we want to show the Sun icon (to switch to light)
      if (this.hasLightIconTarget) this.lightIconTarget.classList.remove("hidden")
      if (this.hasDarkIconTarget) this.darkIconTarget.classList.add("hidden")
    } else {
      // In light theme, we want to show the Moon icon (to switch to dark)
      if (this.hasLightIconTarget) this.lightIconTarget.classList.add("hidden")
      if (this.hasDarkIconTarget) this.darkIconTarget.classList.remove("hidden")
    }
  }
}

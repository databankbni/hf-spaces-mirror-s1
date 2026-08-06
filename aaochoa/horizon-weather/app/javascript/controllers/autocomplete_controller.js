import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["input", "results"]

  connect() {
    this.searchTimeout = null
    // Close results when clicking outside
    this.outsideClickListener = this.closeResults.bind(this)
    document.addEventListener("click", this.outsideClickListener)
  }

  disconnect() {
    document.removeEventListener("click", this.outsideClickListener)
    if (this.searchTimeout) {
      clearTimeout(this.searchTimeout)
    }
  }

  onInput() {
    if (this.searchTimeout) {
      clearTimeout(this.searchTimeout)
    }

    const query = this.inputTarget.value.trim()
    if (query.length < 2) {
      this.resultsTarget.innerHTML = ""
      this.resultsTarget.classList.add("hidden")
      return
    }

    this.searchTimeout = setTimeout(() => {
      this.fetchResults(query)
    }, 300)
  }

  async fetchResults(query) {
    try {
      const response = await fetch(`/search?q=${encodeURIComponent(query)}`)
      if (!response.ok) throw new Error("Search failed")
      
      const cities = await response.json()
      this.renderResults(cities)
    } catch (error) {
      console.error("Autocomplete fetch error:", error)
    }
  }

  renderResults(cities) {
    if (cities.length === 0) {
      this.resultsTarget.innerHTML = `<div class="p-3 text-slate-500 dark:text-slate-400 text-sm">No cities found</div>`
      this.resultsTarget.classList.remove("hidden")
      return
    }

    const html = cities.map(city => {
      return `
        <button type="button" 
                class="w-full text-left px-4 py-3 hover:bg-slate-100 dark:hover:bg-slate-800 text-sm text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-800 last:border-0 transition flex flex-col justify-start cursor-pointer"
                data-action="click->autocomplete#selectCity"
                data-name="${city.name}"
                data-lat="${city.latitude}"
                data-lon="${city.longitude}">
          <span class="font-semibold">${city.name}</span>
          <span class="text-xs text-slate-500 dark:text-slate-400">${city.country || ""}</span>
        </button>
      `
    }).join("")

    this.resultsTarget.innerHTML = html
    this.resultsTarget.classList.remove("hidden")
  }

  selectCity(event) {
    event.preventDefault()
    const button = event.currentTarget
    const name = button.dataset.name
    const lat = button.dataset.lat
    const lon = button.dataset.lon

    this.inputTarget.value = name
    this.resultsTarget.classList.add("hidden")

    // Redirect to load weather for selected coordinates
    const url = new URL(window.location.origin)
    url.searchParams.set("lat", lat)
    url.searchParams.set("lon", lon)
    url.searchParams.set("name", name)

    // Using Turbo to load page smoothly
    if (window.Turbo) {
      window.Turbo.visit(url.toString())
    } else {
      window.location.href = url.toString()
    }
  }

  useCurrentLocation(event) {
    event.preventDefault()
    const button = event.currentTarget
    
    button.disabled = true
    button.innerHTML = `<i data-lucide="loader" class="w-4.5 h-4.5 animate-spin text-cyan-500"></i>`
    if (typeof lucide !== 'undefined') lucide.createIcons()
 
    if (!navigator.geolocation) {
      alert("Geolocation is not supported by your browser.")
      button.disabled = false
      button.innerHTML = `<i data-lucide="map-pin" class="w-4.5 h-4.5"></i>`
      if (typeof lucide !== 'undefined') lucide.createIcons()
      return
    }
 
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = position.coords.latitude
        const lon = position.coords.longitude
        
        // Load weather with lat/lon and a generic location name
        const url = new URL(window.location.origin)
        url.searchParams.set("lat", lat.toFixed(4))
        url.searchParams.set("lon", lon.toFixed(4))
        url.searchParams.set("name", "Your Location")
        
        if (window.Turbo) {
          window.Turbo.visit(url.toString())
        } else {
          window.location.href = url.toString()
        }
      },
      (error) => {
        console.error("Geolocation error:", error)
        alert(`Could not get location: ${error.message}`)
        button.disabled = false
        button.innerHTML = `<i data-lucide="map-pin" class="w-4.5 h-4.5"></i>`
        if (typeof lucide !== 'undefined') lucide.createIcons()
      },
      { timeout: 10000 }
    )
  }

  closeResults(event) {
    if (!this.element.contains(event.target)) {
      this.resultsTarget.classList.add("hidden")
    }
  }
}

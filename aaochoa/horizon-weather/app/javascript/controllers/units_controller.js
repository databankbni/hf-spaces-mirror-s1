import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = [ "button" ]
  static values = {
    current: String,
    updateUrl: String
  }

  connect() {
    this.unit = this.currentValue
    this.applyUnits(this.unit, false)
  }

  toggle(event) {
    event.preventDefault()
    const newUnit = event.submitter ? event.submitter.dataset.unitSystem : event.target.dataset.unitSystem
    if (!newUnit || newUnit === this.unit) return

    this.unit = newUnit
    this.applyUnits(this.unit, true)
  }

  applyUnits(unit, persist = true) {
    // 1. Update buttons styling
    this.buttonTargets.forEach(btn => {
      const isCurrent = btn.dataset.unitSystem === unit
      if (isCurrent) {
        btn.classList.add("bg-white", "dark:bg-slate-700", "text-cyan-600", "dark:text-cyan-400", "shadow-sm", "font-extrabold")
        btn.classList.remove("text-slate-500", "dark:text-slate-400")
      } else {
        btn.classList.remove("bg-white", "dark:bg-slate-700", "text-cyan-600", "dark:text-cyan-400", "shadow-sm", "font-extrabold")
        btn.classList.add("text-slate-500", "dark:text-slate-400")
      }
    })

    // 2. Scan DOM and convert values
    document.querySelectorAll("[data-unit-type]").forEach(el => {
      const type = el.dataset.unitType
      const metricVal = parseFloat(el.dataset.metricValue)
      if (isNaN(metricVal)) return

      if (type === "temp") {
        const showSuffix = el.dataset.unitSuffix === "true"
        if (unit === "imperial") {
          const f = Math.round(metricVal * 1.8 + 32)
          el.textContent = showSuffix ? `${f}°F` : `${f}°`
        } else {
          const c = Math.round(metricVal)
          el.textContent = showSuffix ? `${c}°C` : `${c}°`
        }
      } else if (type === "wind") {
        if (unit === "imperial") {
          const mph = Math.round(metricVal * 0.621371)
          el.textContent = `${mph} mph`
        } else {
          const kmh = Math.round(metricVal)
          el.textContent = `${kmh} km/h`
        }
      } else if (type === "precip") {
        if (unit === "imperial") {
          const inches = (metricVal / 25.4).toFixed(2)
          el.textContent = `${inches} in`
        } else {
          el.textContent = `${metricVal} mm`
        }
      }
    })

    // 3. Update the Leaflet Map if it exists
    const mapEl = document.getElementById("weather_map_container")
    if (mapEl) {
      const unitSymbol = unit === "imperial" ? "°F" : "°C"
      mapEl.setAttribute("data-weather-map-unit-symbol-value", unitSymbol)

      const rawTemp = parseFloat(mapEl.getAttribute("data-weather-map-temp-value"))
      const metricTemp = parseFloat(mapEl.getAttribute("data-metric-temp-value") || rawTemp)
      let displayTemp = metricTemp
      if (unit === "imperial") {
        displayTemp = Math.round(metricTemp * 1.8 + 32)
      } else {
        displayTemp = Math.round(metricTemp)
      }

      const rawPrecip = parseFloat(mapEl.getAttribute("data-weather-map-precip-value"))
      const metricPrecip = parseFloat(mapEl.getAttribute("data-metric-precip-value") || rawPrecip)
      let displayPrecip = metricPrecip
      let precipUnit = "mm"
      if (unit === "imperial") {
        displayPrecip = (metricPrecip / 25.4).toFixed(2)
        precipUnit = "in"
      } else {
        displayPrecip = metricPrecip.toFixed(1)
      }

      mapEl.setAttribute("data-weather-map-precip-value", displayPrecip)
      mapEl.setAttribute("data-weather-map-precip-unit-value", precipUnit)

      const mapEvent = new CustomEvent("units-changed", { detail: { 
        unit: unit, 
        unitSymbol: unitSymbol, 
        temp: displayTemp,
        precip: displayPrecip,
        precipUnit: precipUnit
      } })
      document.dispatchEvent(mapEvent)
    }

    // 4. Persist to server in the background (silent fetch)
    if (persist && this.hasUpdateUrlValue) {
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content")
      fetch(this.updateUrlValue, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
          "Accept": "application/json"
        },
        body: JSON.stringify({ unit_system: unit })
      }).catch(err => console.error("Failed to persist unit preference", err))
    }
  }
}

import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  locateUser(event) {
    event.preventDefault()
    const button = event.currentTarget
    const originalHtml = button.innerHTML

    button.disabled = true
    button.innerHTML = `<i data-lucide="loader" class="w-5 h-5 animate-spin text-cyan-500"></i>`
    if (typeof lucide !== 'undefined') lucide.createIcons()

    if (!navigator.geolocation) {
      alert("Geolocation is not supported by your browser.")
      button.disabled = false
      button.innerHTML = originalHtml
      if (typeof lucide !== 'undefined') lucide.createIcons()
      return
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = position.coords.latitude
        const lon = position.coords.longitude

        const url = new URL(window.location.origin)
        url.searchParams.set("lat", lat.toFixed(4))
        url.searchParams.set("lon", lon.toFixed(4))

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
        button.innerHTML = originalHtml
        if (typeof lucide !== 'undefined') lucide.createIcons()
      },
      { timeout: 10000 }
    )
  }
}

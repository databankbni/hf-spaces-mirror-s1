import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  connect() {
    // Only run this on the homepage "/"
    if (window.location.pathname !== "/") return

    const urlParams = new URLSearchParams(window.location.search)
    
    // 1. If the URL already has lat and lon, save it if the user is logged in
    if (urlParams.has("lat") && urlParams.has("lon")) {
      this.maybeSaveCurrentLocationToStorage(urlParams.get("lat"), urlParams.get("lon"))
      return
    }

    // 2. Retrieve user information from body data attributes
    const userId = document.body.dataset.userId
    const isLoggedIn = document.body.dataset.userLoggedIn === "true"

    // 3. If logged in, try to load saved location from local storage
    if (isLoggedIn && userId) {
      const storedLocation = localStorage.getItem(`user_location_${userId}`)
      if (storedLocation) {
        try {
          const { lat, lon } = JSON.parse(storedLocation)
          if (lat && lon) {
            this.redirectToLocation(lat, lon)
            return
          }
        } catch (e) {
          console.error("Error parsing stored user location:", e)
        }
      }
    }

    // 4. Fallback to requesting browser geolocation
    this.askForUserLocation()
  }

  maybeSaveCurrentLocationToStorage(lat, lon) {
    const userId = document.body.dataset.userId
    const isLoggedIn = document.body.dataset.userLoggedIn === "true"
    if (isLoggedIn && userId && lat && lon) {
      localStorage.setItem(`user_location_${userId}`, JSON.stringify({ lat, lon }))
    }
  }

  askForUserLocation() {
    if (!navigator.geolocation) return

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = position.coords.latitude
        const lon = position.coords.longitude

        // Save it if logged in
        this.maybeSaveCurrentLocationToStorage(lat.toFixed(4), lon.toFixed(4))

        // Redirect to load the weather for this location
        this.redirectToLocation(lat, lon)
      },
      (error) => {
        console.warn("Geolocation permission denied or failed:", error)
      },
      { timeout: 10000 }
    )
  }

  redirectToLocation(lat, lon) {
    const url = new URL(window.location.href)
    url.searchParams.set("lat", parseFloat(lat).toFixed(4))
    url.searchParams.set("lon", parseFloat(lon).toFixed(4))

    if (window.Turbo) {
      window.Turbo.visit(url.toString(), { action: "replace" })
    } else {
      window.location.replace(url.toString())
    }
  }
}

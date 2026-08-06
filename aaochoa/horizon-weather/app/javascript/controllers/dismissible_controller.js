import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static values = {
    storageKey: String
  }

  connect() {
    if (this.hasStorageKeyValue && localStorage.getItem(this.storageKeyValue) === "true") {
      this.element.classList.add("hidden")
    }
  }

  dismiss(event) {
    event.preventDefault()
    this.element.classList.add("transition-all", "duration-300", "opacity-0", "scale-95")
    setTimeout(() => {
      this.element.classList.add("hidden")
      if (this.hasStorageKeyValue) {
        localStorage.setItem(this.storageKeyValue, "true")
      }
    }, 300)
  }
}

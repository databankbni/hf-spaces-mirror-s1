class ApplicationController < ActionController::Base
  include Authentication
  # Only allow modern browsers supporting webp images, web push, badges, import maps, CSS nesting, and CSS :has.
  allow_browser versions: :modern

  # Changes to the importmap will invalidate the etag for HTML responses
  stale_when_importmap_changes

  helper_method :unit_system

  def unit_system
    if authenticated?
      Current.user.unit_system
    else
      session[:unit_system] || "imperial"
    end
  end
end

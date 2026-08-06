class WeatherController < ApplicationController
  allow_unauthenticated_access only: %i[ index search ]

  def index
    # Default to Chicago, IL if no coordinates are specified
    @latitude = params[:lat].presence || "41.8781"
    @longitude = params[:lon].presence || "-87.6298"

    @weather = WeatherService.get_weather(
      @latitude.to_f.round(4),
      @longitude.to_f.round(4),
      unit_system: unit_system,
      force_refresh: params[:refresh] == "true"
    )

    @location_name = params[:name].presence
    if @location_name.blank?
      if params[:lat].present? && params[:lon].present?
        @location_name = WeatherService.reverse_geocode(@latitude.to_f, @longitude.to_f)
      else
        @location_name = "Chicago, IL"
      end
    end

    if @weather && @weather["timezone"]
      begin
        @local_time = Time.current.in_time_zone(@weather["timezone"])
      rescue
        @local_time = Time.current
      end
    else
      @local_time = Time.current
    end

    if authenticated?
      @favorites = Current.user.favorite_locations.order(:name)
      @is_favorited = @favorites.any? { |f| (f.latitude - @latitude.to_f).abs < 0.001 && (f.longitude - @longitude.to_f).abs < 0.001 }
    else
      @favorites = []
      @is_favorited = false
    end

    respond_to do |format|
      format.html
      format.turbo_stream { render :index, formats: :html, content_type: "text/html" }
    end
  end

  def search
    query = params[:q]
    results = WeatherService.search_cities(query)
    render json: results
  end
end

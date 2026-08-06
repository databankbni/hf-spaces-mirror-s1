class FavoriteLocationsController < ApplicationController
  # Require authentication for all actions in this controller
  # (already set by default in application_controller)

  def create
    @favorite = Current.user.favorite_locations.new(favorite_params)

    if @favorite.save
      flash[:notice] = "#{@favorite.name} added to favorites."
    else
      flash[:alert] = @favorite.errors.full_messages.to_sentence
    end

    @latitude = @favorite.latitude || params[:lat]
    @longitude = @favorite.longitude || params[:lon]
    @location_name = @favorite.name || params[:name]
    @favorites = Current.user.favorite_locations.order(:name)
    @is_favorited = @favorites.any? { |f| (f.latitude - @latitude.to_f).abs < 0.001 && (f.longitude - @longitude.to_f).abs < 0.001 }

    respond_to do |format|
      format.turbo_stream
      format.html { redirect_to root_path(lat: @latitude, lon: @longitude, name: @location_name), status: :see_other }
    end
  end

  def destroy
    @favorite = Current.user.favorite_locations.find(params[:id])
    name = @favorite.name
    @favorite.destroy

    flash[:notice] = "#{name} removed from favorites."

    @latitude = params[:lat]
    @longitude = params[:lon]
    @location_name = params[:name]
    @favorites = Current.user.favorite_locations.order(:name)
    @is_favorited = @favorites.any? { |f| (f.latitude - @latitude.to_f).abs < 0.001 && (f.longitude - @longitude.to_f).abs < 0.001 }

    respond_to do |format|
      format.turbo_stream
      format.html { redirect_to root_path(lat: @latitude, lon: @longitude, name: @location_name), status: :see_other }
    end
  end

  private

  def favorite_params
    params.require(:favorite_location).permit(:name, :latitude, :longitude)
  end
end

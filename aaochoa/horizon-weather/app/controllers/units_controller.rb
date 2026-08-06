class UnitsController < ApplicationController
  allow_unauthenticated_access only: :update

  def update
    unit = params[:unit_system]
    if %w[imperial metric].include?(unit)
      if authenticated?
        Current.user.update!(unit_system: unit)
      else
        session[:unit_system] = unit
      end
    end

    respond_to do |format|
      format.json { render json: { success: true } }
      format.html { redirect_back_or_to root_path }
      format.turbo_stream { redirect_back_or_to root_path }
    end
  end
end

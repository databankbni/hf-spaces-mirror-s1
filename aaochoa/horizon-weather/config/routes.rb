Rails.application.routes.draw do
  resource :session
  resources :passwords, param: :token

  get "signup" => "registrations#new", as: :signup
  post "signup" => "registrations#create"

  get "search" => "weather#search", as: :search_cities
  resources :favorite_locations, only: [ :create, :destroy ]
  resource :unit, only: [ :update ]

  # Reveal health status on /up that returns 200 if the app boots with no exceptions, otherwise 500.
  # Can be used by load balancers and uptime monitors to verify that the app is live.
  get "up" => "rails/health#show", as: :rails_health_check

  # Defines the root path route ("/")
  root "weather#index"
end

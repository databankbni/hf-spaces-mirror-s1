from django.urls import path
from . import views

urlpatterns= [
    # Designate the blank home page as the root application route
    path('', views.HomeView.as_view(), name='home'),

    # Explicit provider routes mapping to dedicated view functions
    path('<str:provider_id>/', views.ProviderDashboardView.as_view(), name='dashboard'),
]
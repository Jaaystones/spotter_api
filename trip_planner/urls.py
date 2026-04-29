from django.urls import path

from .views import ApiInfoView, HealthCheckView, PlanTripView

urlpatterns = [
    path('', ApiInfoView.as_view(), name='api-info'),
    path('health', HealthCheckView.as_view(), name='health'),
    path('plan-trip', PlanTripView.as_view(), name='plan-trip'),
]

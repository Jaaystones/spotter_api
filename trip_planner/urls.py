from django.urls import path

from .views import ApiInfoView, HealthCheckView, LogSheetView, PlanTripView

urlpatterns = [
    path('', ApiInfoView.as_view(), name='api-info'),
    path('health', HealthCheckView.as_view(), name='health'),
    path('plan-trip', PlanTripView.as_view(), name='plan-trip'),
    path('log-sheets', LogSheetView.as_view(), name='log-sheets'),
]

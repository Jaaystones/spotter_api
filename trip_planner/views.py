from drf_spectacular.utils import extend_schema, OpenApiExample
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import TripRequestSerializer
from .services import build_trip_plan


class HealthCheckView(APIView):
    """Health check endpoint to verify API is running."""
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        description='Check if the Trip Planner API is healthy and responsive',
        responses={200: {'type': 'object', 'properties': {'status': {'type': 'string'}, 'service': {'type': 'string'}}}},
    )
    def get(self, request):
        """Returns health status of the API."""
        return Response({'status': 'ok', 'service': 'trip-planner-api'}, status=status.HTTP_200_OK)


class ApiInfoView(APIView):
    """API information and endpoint listing."""
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        description='Get API metadata and available endpoints',
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'version': {'type': 'string'},
                    'endpoints': {
                        'type': 'object',
                        'properties': {
                            'health': {'type': 'string'},
                            'plan_trip': {'type': 'string'},
                        },
                    },
                },
            }
        },
    )
    def get(self, request):
        """Returns API name, version, and available endpoints."""
        return Response(
            {
                'name': 'Spotter Trip Planner API',
                'version': '1.0.0',
                'endpoints': {
                    'health': '/api/health',
                    'plan_trip': '/api/plan-trip',
                },
            },
            status=status.HTTP_200_OK,
        )


class PlanTripView(APIView):
    """Plan a route with HOS (Hours of Service) compliance."""

    @extend_schema(
        description='Generate a trip plan with route instructions and ELD duty logs based on HOS regulations',
        request=TripRequestSerializer,
        examples=[
            OpenApiExample(
                'Valid trip from Miami to Seattle',
                value={
                    'current_location': 'Miami, FL',
                    'pickup_location': 'Boston, MA',
                    'dropoff_location': 'Seattle, WA',
                    'cycle_used_hours': 0,
                },
                request_only=True,
            ),
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'route': {
                        'type': 'object',
                        'properties': {
                            'total_distance_miles': {'type': 'number'},
                            'estimated_duration_hours': {'type': 'number'},
                            'locations': {'type': 'array', 'items': {'type': 'string'}},
                        },
                    },
                    'stops': {'type': 'array'},
                    'daily_logs': {'type': 'array'},
                    'summary': {'type': 'object'},
                },
            }
        },
    )
    def post(self, request):
        """
        Generate a trip plan that includes:
        - Route details (distance, duration, waypoints)
        - Planned stops (pickup, dropoff, fuel, breaks)
        - Daily ELD logs with duty status breakdown
        - Summary with total hours and fuel stops
        """
        serializer = TripRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = build_trip_plan(serializer.validated_data)
        return Response(plan, status=status.HTTP_200_OK)

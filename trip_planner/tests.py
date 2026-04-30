from datetime import datetime
from unittest.mock import patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase
from .models import EldLogSheet

from .services import build_trip_plan


class PlanTripApiTests(APITestCase):
    def setUp(self):
        self.base_payload = {
            'current_location': 'Dallas, TX',
            'pickup_location': 'Oklahoma City, OK',
            'dropoff_location': 'Denver, CO',
            'cycle_used_hours': 24,
            'trip_start_time': '2026-04-29T08:00:00Z',
        }
        self.geocode_patcher = patch('trip_planner.services._geocode_location')
        self.route_patcher = patch('trip_planner.services._resolve_route')
        self.mock_geocode = self.geocode_patcher.start()
        self.mock_route = self.route_patcher.start()

        self.mock_geocode.side_effect = [
            {'lat': 32.7767, 'lng': -96.7970},
            {'lat': 35.4676, 'lng': -97.5164},
            {'lat': 39.7392, 'lng': -104.9903},
        ] * 20
        self.mock_route.return_value = {
            'distance_miles': 810.2,
            'duration_minutes': 760,
            'geometry': {'type': 'LineString', 'coordinates': [[-96.79, 32.77], [-97.51, 35.46], [-104.99, 39.73]]},
            'provider': 'mock_provider',
        }

    def tearDown(self):
        self.geocode_patcher.stop()
        self.route_patcher.stop()

    def test_health_endpoint_returns_ok(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'ok')

    def test_api_info_endpoint_returns_endpoints(self):
        response = self.client.get('/api/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('endpoints', response.data)

    def test_log_sheet_save_endpoint_persists_payload(self):
        payload = {
            'trip_form': {
                'current_location': 'Dallas, TX',
                'pickup_location': 'Oklahoma City, OK',
                'dropoff_location': 'Denver, CO',
                'cycle_used_hours': 24,
            },
            'driver_info': {
                'carrier': 'Spotter Freight',
                'vehicle': 'TRK-18',
            },
            'selected_log_index': 0,
            'sheet_details': {
                '0': {
                    'remarks': 'Loaded and ready to roll',
                    'shippingDocument': 'BOL-1234',
                    'commodity': 'Produce',
                }
            },
            'plan_result': {'daily_logs': []},
        }

        response = self.client.post('/api/log-sheets', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['payload']['driver_info']['carrier'], 'Spotter Freight')
        self.assertEqual(EldLogSheet.objects.count(), 1)

    def test_plan_trip_returns_full_backend_payload(self):
        response = self.client.post('/api/plan-trip', self.base_payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('route', response.data)
        self.assertIn('stops', response.data)
        self.assertIn('duty_events', response.data)
        self.assertIn('daily_logs', response.data)
        self.assertIn('summary', response.data)
        self.assertIn('assumptions_applied', response.data)

    def test_plan_trip_has_ordered_events(self):
        response = self.client.post('/api/plan-trip', self.base_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        events = response.data['duty_events']
        for idx in range(1, len(events)):
            prev = datetime.fromisoformat(events[idx - 1]['start_time'])
            current = datetime.fromisoformat(events[idx]['start_time'])
            self.assertLessEqual(prev, current)

    def test_plan_trip_includes_required_pickup_and_dropoff_stops(self):
        response = self.client.post('/api/plan-trip', self.base_payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        stop_types = [stop['type'] for stop in response.data['stops']]
        self.assertIn('pickup', stop_types)
        self.assertIn('dropoff', stop_types)

    def test_long_trip_inserts_fuel_stop(self):
        payload = {
            **self.base_payload,
            'current_location': 'Miami, FL',
            'pickup_location': 'Houston, TX',
            'dropoff_location': 'Seattle, WA',
        }
        self.mock_geocode.side_effect = [
            {'lat': 25.7617, 'lng': -80.1918},
            {'lat': 29.7604, 'lng': -95.3698},
            {'lat': 47.6062, 'lng': -122.3321},
        ]
        response = self.client.post('/api/plan-trip', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        stop_types = [stop['type'] for stop in response.data['stops']]
        self.assertIn('fuel', stop_types)

    def test_high_cycle_used_requires_off_duty_reset(self):
        payload = {**self.base_payload, 'cycle_used_hours': 69}
        response = self.client.post('/api/plan-trip', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        event_types = [event['type'] for event in response.data['duty_events']]
        self.assertIn('OFF_DUTY', event_types)

    def test_multi_day_trip_generates_multiple_daily_logs(self):
        payload = {
            **self.base_payload,
            'current_location': 'San Diego, CA',
            'pickup_location': 'Phoenix, AZ',
            'dropoff_location': 'New York, NY',
        }
        response = self.client.post('/api/plan-trip', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data['daily_logs']), 1)

    def test_daily_log_totals_have_expected_keys(self):
        response = self.client.post('/api/plan-trip', self.base_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        first_log = response.data['daily_logs'][0]
        totals = first_log['totals_by_status']
        self.assertIn('OFF_DUTY', totals)
        self.assertIn('DRIVING', totals)
        self.assertIn('ON_DUTY_NOT_DRIVING', totals)

    def test_plan_trip_rejects_invalid_cycle_used_hours(self):
        payload = {**self.base_payload, 'cycle_used_hours': 90}
        response = self.client.post('/api/plan-trip', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_plan_trip_rejects_duplicate_locations(self):
        payload = {
            **self.base_payload,
            'current_location': 'Dallas, TX',
            'pickup_location': 'Dallas, TX',
            'dropoff_location': 'Denver, CO',
        }
        response = self.client.post('/api/plan-trip', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class PlannerServiceTests(TestCase):
    def setUp(self):
        self.payload = {
            'current_location': 'Current City',
            'pickup_location': 'Pickup City',
            'dropoff_location': 'Dropoff City',
            'cycle_used_hours': 10,
            'trip_start_time': '2026-04-29T06:00:00Z',
        }

    @patch('trip_planner.services._resolve_route')
    @patch('trip_planner.services._geocode_location')
    def test_build_trip_plan_uses_expected_leg_distances(self, mock_geocode, mock_route):
        mock_geocode.side_effect = [
            {'lat': 32.7767, 'lng': -96.797},
            {'lat': 35.4676, 'lng': -97.5164},
            {'lat': 39.7392, 'lng': -104.9903},
        ]
        mock_route.return_value = {
            'distance_miles': 810.2,
            'duration_minutes': 760,
            'geometry': {'type': 'LineString', 'coordinates': []},
            'provider': 'mock_provider',
        }

        result = build_trip_plan(self.payload)

        self.assertEqual(result['route']['provider'], 'mock_provider')
        self.assertEqual(len(result['route']['legs']), 2)
        self.assertGreater(result['route']['legs'][0]['distance_miles'], 0)
        self.assertGreater(result['route']['legs'][1]['distance_miles'], 0)

    @patch('trip_planner.services._resolve_route')
    @patch('trip_planner.services._geocode_location')
    def test_build_trip_plan_generates_non_empty_daily_logs(self, mock_geocode, mock_route):
        mock_geocode.side_effect = [
            {'lat': 33.0, 'lng': -96.0},
            {'lat': 35.0, 'lng': -97.0},
            {'lat': 36.0, 'lng': -101.0},
        ]
        mock_route.return_value = {
            'distance_miles': 500.0,
            'duration_minutes': 540,
            'geometry': {'type': 'LineString', 'coordinates': []},
            'provider': 'mock_provider',
        }

        result = build_trip_plan(self.payload)

        self.assertGreaterEqual(len(result['daily_logs']), 1)
        self.assertGreater(len(result['duty_events']), 0)
        self.assertGreaterEqual(result['summary']['days'], 1)

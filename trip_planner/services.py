import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

AVERAGE_SPEED_MPH = 55
CYCLE_LIMIT_HOURS = 70
FUEL_INTERVAL_MILES = 1000
FUEL_STOP_MINUTES = 30
PICKUP_DROPOFF_MINUTES = 60
MAX_DRIVING_HOURS_PER_SHIFT = 11
MAX_ON_DUTY_HOURS_PER_SHIFT = 14
MANDATORY_BREAK_AFTER_DRIVING_HOURS = 8
MANDATORY_BREAK_MINUTES = 30
RESET_OFF_DUTY_HOURS = 10


def _env_flag(name: str, default: str = 'false') -> bool:
    return os.getenv(name, default).strip().lower() in {'1', 'true', 'yes', 'on'}


USE_EXTERNAL_GEOCODING = _env_flag('TRIP_PLANNER_USE_EXTERNAL_GEOCODING')
USE_EXTERNAL_ROUTING = _env_flag('TRIP_PLANNER_USE_EXTERNAL_ROUTING')


def _parse_start_time(data: dict) -> datetime:
    start_time = data.get('trip_start_time')
    if not start_time:
        return datetime.now(timezone.utc)

    if isinstance(start_time, datetime):
        parsed = start_time
    else:
        parsed = datetime.fromisoformat(str(start_time).replace('Z', '+00:00'))

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _pseudo_geocode(location: str) -> dict:
    normalized = location.strip().lower()
    if not normalized:
        return {'lat': 39.5, 'lng': -98.35}

    seed = sum(ord(char) for char in normalized)
    lat = 25 + (seed % 2300) / 100
    lng = -125 + (seed % 5800) / 100
    return {
        'lat': round(min(max(lat, 24.0), 49.0), 6),
        'lng': round(min(max(lng, -124.0), -66.0), 6),
    }


def _geocode_location(location: str) -> dict:
    if not USE_EXTERNAL_GEOCODING:
        return _pseudo_geocode(location)

    try:
        response = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={'q': location, 'format': 'json', 'limit': 1},
            headers={'User-Agent': 'spotter-trip-planner/1.0'},
            timeout=6,
        )
        response.raise_for_status()
        payload = response.json()
        if payload:
            return {'lat': float(payload[0]['lat']), 'lng': float(payload[0]['lon'])}
    except (requests.RequestException, ValueError, KeyError, IndexError):
        pass

    return _pseudo_geocode(location)


def _distance_miles(a: dict, b: dict) -> float:
    radius_miles = 3958.8
    lat1 = math.radians(a['lat'])
    lon1 = math.radians(a['lng'])
    lat2 = math.radians(b['lat'])
    lon2 = math.radians(b['lng'])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius_miles * math.asin(math.sqrt(h))


def _fetch_osrm_route(points: list[dict]) -> dict | None:
    coordinates = ';'.join(f"{point['lng']},{point['lat']}" for point in points)
    url = f'https://router.project-osrm.org/route/v1/driving/{coordinates}'

    try:
        response = requests.get(
            url,
            params={'overview': 'full', 'geometries': 'geojson', 'steps': 'false'},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        route = payload['routes'][0]
        return {
            'distance_miles': round(route['distance'] / 1609.34, 1),
            'duration_minutes': int(route['duration'] / 60),
            'geometry': route['geometry'],
            'provider': 'osrm',
        }
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None


def _fallback_route(points: list[dict]) -> dict:
    total_miles = 0.0
    for idx in range(len(points) - 1):
        total_miles += _distance_miles(points[idx], points[idx + 1])

    return {
        'distance_miles': round(total_miles, 1),
        'duration_minutes': int((total_miles / AVERAGE_SPEED_MPH) * 60),
        'geometry': {
            'type': 'LineString',
            'coordinates': [[point['lng'], point['lat']] for point in points],
        },
        'provider': 'fallback_haversine',
    }


def _resolve_route(points: list[dict]) -> dict:
    if not USE_EXTERNAL_ROUTING:
        return _fallback_route(points)

    osrm = _fetch_osrm_route(points)
    if osrm:
        return osrm
    return _fallback_route(points)


def _event_dict(event_type: str, duty_status: str, start: datetime, end: datetime, location: str, notes: str = '') -> dict:
    return {
        'type': event_type,
        'duty_status': duty_status,
        'start_time': start.isoformat(),
        'end_time': end.isoformat(),
        'duration_minutes': int((end - start).total_seconds() // 60),
        'location': location,
        'notes': notes,
    }


class PlannerState:
    def __init__(self, cycle_used_hours: float, start_time: datetime):
        self.current_time = start_time
        self.shift_driving_hours = 0.0
        self.shift_on_duty_hours = 0.0
        self.driving_since_break_hours = 0.0
        self.cycle_remaining_hours = max(0.0, CYCLE_LIMIT_HOURS - cycle_used_hours)
        self.total_driving_hours = 0.0
        self.total_on_duty_hours = 0.0
        self.total_off_duty_hours = 0.0
        self.fuel_miles_since_last_stop = 0.0
        self.events: list[dict] = []
        self.stops: list[dict] = []

    def _append_event(self, event_type: str, duty_status: str, duration_minutes: int, location: str, notes: str = '') -> dict:
        start = self.current_time
        end = start + timedelta(minutes=duration_minutes)
        event = _event_dict(event_type, duty_status, start, end, location, notes)
        self.events.append(event)
        self.current_time = end

        duration_hours = duration_minutes / 60
        if duty_status == 'DRIVING':
            self.shift_driving_hours += duration_hours
            self.shift_on_duty_hours += duration_hours
            self.driving_since_break_hours += duration_hours
            self.total_driving_hours += duration_hours
            self.total_on_duty_hours += duration_hours
            self.cycle_remaining_hours = max(0.0, self.cycle_remaining_hours - duration_hours)
        elif duty_status == 'ON_DUTY_NOT_DRIVING':
            self.shift_on_duty_hours += duration_hours
            self.total_on_duty_hours += duration_hours
            self.cycle_remaining_hours = max(0.0, self.cycle_remaining_hours - duration_hours)
        else:
            self.total_off_duty_hours += duration_hours

        return event

    def _add_stop(self, stop_type: str, event: dict):
        self.stops.append(
            {
                'type': stop_type,
                'eta': event['start_time'],
                'duration_minutes': event['duration_minutes'],
                'location': event['location'],
            }
        )

    def _take_reset_break(self, location: str, reason: str, reset_cycle: bool = False):
        self._append_event(
            event_type='OFF_DUTY',
            duty_status='OFF_DUTY',
            duration_minutes=RESET_OFF_DUTY_HOURS * 60,
            location=location,
            notes=reason,
        )
        self.shift_driving_hours = 0.0
        self.shift_on_duty_hours = 0.0
        self.driving_since_break_hours = 0.0
        if reset_cycle:
            self.cycle_remaining_hours = CYCLE_LIMIT_HOURS

    def _take_short_break_if_needed(self, location: str):
        if self.driving_since_break_hours < MANDATORY_BREAK_AFTER_DRIVING_HOURS:
            return

        self._append_event(
            event_type='BREAK',
            duty_status='OFF_DUTY',
            duration_minutes=MANDATORY_BREAK_MINUTES,
            location=location,
            notes='30-minute break after 8 hours driving',
        )
        self.driving_since_break_hours = 0.0

    def _ensure_capacity_for_on_duty(self, duration_hours: float, location: str):
        while (
            self.shift_on_duty_hours + duration_hours > MAX_ON_DUTY_HOURS_PER_SHIFT
            or self.cycle_remaining_hours < duration_hours
        ):
            needs_cycle_reset = self.cycle_remaining_hours < duration_hours
            self._take_reset_break(
                location,
                'Reset before on-duty event',
                reset_cycle=needs_cycle_reset,
            )

    def add_on_duty_stop(self, stop_type: str, location: str, duration_minutes: int, notes: str):
        self._ensure_capacity_for_on_duty(duration_minutes / 60, location)
        event = self._append_event(
            event_type=stop_type.upper(),
            duty_status='ON_DUTY_NOT_DRIVING',
            duration_minutes=duration_minutes,
            location=location,
            notes=notes,
        )
        self._add_stop(stop_type, event)

    def drive_leg(self, miles: float, location_label: str):
        remaining = max(0.0, miles)

        while remaining > 0.01:
            self._take_short_break_if_needed(location_label)

            if (
                self.shift_driving_hours >= MAX_DRIVING_HOURS_PER_SHIFT
                or self.shift_on_duty_hours >= MAX_ON_DUTY_HOURS_PER_SHIFT
                or self.cycle_remaining_hours <= 0.01
            ):
                needs_cycle_reset = self.cycle_remaining_hours <= 0.01
                self._take_reset_break(
                    location_label,
                    'Shift or cycle reset before driving',
                    reset_cycle=needs_cycle_reset,
                )
                continue

            max_hours_shift = min(
                MAX_DRIVING_HOURS_PER_SHIFT - self.shift_driving_hours,
                MAX_ON_DUTY_HOURS_PER_SHIFT - self.shift_on_duty_hours,
            )
            max_hours_break_rule = MANDATORY_BREAK_AFTER_DRIVING_HOURS - self.driving_since_break_hours
            allowed_hours = min(max_hours_shift, max_hours_break_rule, self.cycle_remaining_hours)

            if allowed_hours <= 0.01:
                needs_cycle_reset = self.cycle_remaining_hours <= 0.01
                self._take_reset_break(
                    location_label,
                    'Reset to continue driving',
                    reset_cycle=needs_cycle_reset,
                )
                continue

            miles_by_hours = allowed_hours * AVERAGE_SPEED_MPH
            next_fuel_gap = FUEL_INTERVAL_MILES - self.fuel_miles_since_last_stop
            miles_chunk = min(remaining, miles_by_hours, next_fuel_gap)

            if miles_chunk <= 0.01:
                self.add_on_duty_stop(
                    stop_type='fuel',
                    location=location_label,
                    duration_minutes=FUEL_STOP_MINUTES,
                    notes='Fueling stop every 1,000 miles',
                )
                self.fuel_miles_since_last_stop = 0.0
                continue

            duration_minutes = max(1, int((miles_chunk / AVERAGE_SPEED_MPH) * 60))
            self._append_event(
                event_type='DRIVING',
                duty_status='DRIVING',
                duration_minutes=duration_minutes,
                location=location_label,
                notes=f'Driving segment {round(miles_chunk, 1)} miles',
            )

            driven_miles = (duration_minutes / 60) * AVERAGE_SPEED_MPH
            remaining = max(0.0, remaining - driven_miles)
            self.fuel_miles_since_last_stop += driven_miles

            if self.fuel_miles_since_last_stop >= FUEL_INTERVAL_MILES - 0.01:
                self.add_on_duty_stop(
                    stop_type='fuel',
                    location=location_label,
                    duration_minutes=FUEL_STOP_MINUTES,
                    notes='Fueling stop every 1,000 miles',
                )
                self.fuel_miles_since_last_stop = 0.0


def _split_events_by_day(events: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)

    for event in events:
        start = datetime.fromisoformat(event['start_time'])
        end = datetime.fromisoformat(event['end_time'])
        cursor = start

        while cursor < end:
            next_midnight = (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            chunk_end = min(end, next_midnight)
            date_key = cursor.date().isoformat()
            grouped[date_key].append(
                {
                    **event,
                    'start_time': cursor.isoformat(),
                    'end_time': chunk_end.isoformat(),
                    'duration_minutes': int((chunk_end - cursor).total_seconds() // 60),
                }
            )
            cursor = chunk_end

    daily_logs = []
    for date_key in sorted(grouped.keys()):
        totals = {
            'OFF_DUTY': 0.0,
            'SLEEPER': 0.0,
            'DRIVING': 0.0,
            'ON_DUTY_NOT_DRIVING': 0.0,
        }
        for event in grouped[date_key]:
            status = event['duty_status']
            totals[status] = totals.get(status, 0.0) + (event['duration_minutes'] / 60)

        daily_logs.append(
            {
                'date': date_key,
                'events': grouped[date_key],
                'totals_by_status': {k: round(v, 2) for k, v in totals.items()},
            }
        )

    return daily_logs


def build_trip_plan(data: dict) -> dict:
    current = _geocode_location(data['current_location'])
    pickup = _geocode_location(data['pickup_location'])
    dropoff = _geocode_location(data['dropoff_location'])

    waypoints = [
        {'label': 'current', **current, 'name': data['current_location']},
        {'label': 'pickup', **pickup, 'name': data['pickup_location']},
        {'label': 'dropoff', **dropoff, 'name': data['dropoff_location']},
    ]

    leg1_miles = _distance_miles(current, pickup)
    leg2_miles = _distance_miles(pickup, dropoff)

    route_data = _resolve_route([current, pickup, dropoff])
    start_time = _parse_start_time(data)
    state = PlannerState(cycle_used_hours=data['cycle_used_hours'], start_time=start_time)

    state.drive_leg(leg1_miles, data['pickup_location'])
    state.add_on_duty_stop(
        stop_type='pickup',
        location=data['pickup_location'],
        duration_minutes=PICKUP_DROPOFF_MINUTES,
        notes='Pickup handling time',
    )

    state.drive_leg(leg2_miles, data['dropoff_location'])
    state.add_on_duty_stop(
        stop_type='dropoff',
        location=data['dropoff_location'],
        duration_minutes=PICKUP_DROPOFF_MINUTES,
        notes='Dropoff handling time',
    )

    daily_logs = _split_events_by_day(state.events)

    return {
        'route': {
            'distance_miles': route_data['distance_miles'],
            'duration_minutes': route_data['duration_minutes'],
            'geometry': route_data['geometry'],
            'provider': route_data['provider'],
            'waypoints': waypoints,
            'legs': [
                {
                    'start': data['current_location'],
                    'end': data['pickup_location'],
                    'distance_miles': round(leg1_miles, 1),
                },
                {
                    'start': data['pickup_location'],
                    'end': data['dropoff_location'],
                    'distance_miles': round(leg2_miles, 1),
                },
            ],
        },
        'stops': state.stops,
        'duty_events': state.events,
        'daily_logs': daily_logs,
        'summary': {
            'days': len(daily_logs),
            'driving_hours': round(state.total_driving_hours, 2),
            'on_duty_hours': round(state.total_on_duty_hours, 2),
            'off_duty_hours': round(state.total_off_duty_hours, 2),
            'remaining_cycle_hours': round(state.cycle_remaining_hours, 2),
        },
        'assumptions_applied': {
            'cycle_limit_hours': CYCLE_LIMIT_HOURS,
            'fuel_interval_miles': FUEL_INTERVAL_MILES,
            'pickup_dropoff_minutes_each': PICKUP_DROPOFF_MINUTES,
            'no_adverse_driving_conditions': True,
            'property_carrying_driver': True,
        },
    }

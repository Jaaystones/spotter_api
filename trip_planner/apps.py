import logging

from django.apps import AppConfig
from django.conf import settings


class TripPlannerConfig(AppConfig):
    name = 'trip_planner'

    def ready(self):
        if getattr(settings, 'DATABASE_FALLBACK_TO_SQLITE', False):
            logging.getLogger(__name__).info(getattr(settings, 'DATABASE_FALLBACK_MESSAGE', 'Using SQLite fallback database.'))

from rest_framework import serializers


class TripRequestSerializer(serializers.Serializer):
    current_location = serializers.CharField(
        max_length=255,
        help_text='Starting location (city, address, or landmark)',
    )
    pickup_location = serializers.CharField(
        max_length=255,
        help_text='Location where passenger/cargo is picked up',
    )
    dropoff_location = serializers.CharField(
        max_length=255,
        help_text='Final destination for passenger/cargo delivery',
    )
    cycle_used_hours = serializers.FloatField(
        min_value=0,
        max_value=70,
        help_text='Hours already used in current 8-day HOS cycle (0-70)',
    )
    trip_start_time = serializers.DateTimeField(
        required=False,
        help_text='Start time for the trip (defaults to current time if not provided)',
    )

    def validate(self, attrs):
        current = attrs['current_location'].strip().lower()
        pickup = attrs['pickup_location'].strip().lower()
        dropoff = attrs['dropoff_location'].strip().lower()

        if current == pickup:
            raise serializers.ValidationError('Current and pickup locations must be different.')
        if pickup == dropoff:
            raise serializers.ValidationError('Pickup and dropoff locations must be different.')

        return attrs

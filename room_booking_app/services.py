from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.http import HttpResponseBadRequest, HttpResponse

from .models import Booking


def timing_validation(start_time, end_time):
    now = timezone.now()

    if start_time <= now:
        raise ValueError("Start time must be in the future.")

    if end_time <= start_time:
        raise ValueError("End time must be after start time.")


# critical section - must  enforce mutual exclusion
@transaction.atomic
def create_booking(user, room, start_time, end_time):
    timing_validation(start_time, end_time)

    now = timezone.now()

    # Expire pending bookings whose 10-minute hold has ended.
    Booking.objects.filter(
        booking_status=Booking.Status.PENDING,
        expires_at__lte=now,
    ).update(booking_status=Booking.Status.EXPIRED)

    # Check for overlapping pending or confirmed bookings.
    overlapping = Booking.objects.filter(
        room=room,
        booking_status__in=[
            Booking.Status.PENDING,
            Booking.Status.CONFIRMED,
        ],
        start_time__lt=end_time,
        end_time__gt=start_time,
    ).exists()

    if overlapping:
        return HttpResponse(
            "This room is already booked for the requested time.", status=409
        )

    # Create a temporary reservation lasting 10 minutes.
    booking = Booking.objects.create(
        user=user,
        room=room,
        start_time=start_time,
        end_time=end_time,
        booking_status=Booking.Status.PENDING,
        expires_at=now + timedelta(minutes=10),
    )

    return booking

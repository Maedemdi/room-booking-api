from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .. import models
from ..services import timing_validation, create_booking


class ServicesTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user1 = models.User.objects.create_user(
            email="user1@gmail.com",
            password="test-password-123",
        )
        cls.user2 = models.User.objects.create_user(
            email="user2@gmail.com",
            password="test-password-123",
        )

        cls.room1 = models.Room.objects.create(
            name="conference room",
            capacity=12,
        )
        cls.room2 = models.Room.objects.create(
            name="big office",
            capacity=4,
        )

    def setUp(self):
        # Keep test booking times in the future.
        self.start_time = timezone.now() + timedelta(hours=1)
        self.end_time = self.start_time + timedelta(hours=1)

    def create_existing_booking(
        self,
        *,
        room=None,
        user=None,
        start_time=None,
        end_time=None,
        status=models.Booking.Status.PENDING,
        expires_at=None,
    ):
        """Helper for creating bookings used by multiple tests."""
        now = timezone.now()

        return models.Booking.objects.create(
            room=room or self.room1,
            user=user or self.user1,
            booking_status=status,
            start_time=start_time or self.start_time,
            end_time=end_time or self.end_time,
            expires_at=expires_at or now + timedelta(minutes=10),
        )

    def test_rejects_start_time_in_the_past(self):
        start = timezone.now() - timedelta(minutes=1)
        end = start + timedelta(hours=1)

        with self.assertRaises(ValueError):
            timing_validation(start, end)

    def test_rejects_start_time_equal_to_now(self):
        now = timezone.now()

        with self.assertRaises(ValueError):
            timing_validation(now, now + timedelta(hours=1))

    def test_rejects_end_time_before_start_time(self):
        start = timezone.now() + timedelta(hours=2)
        end = start - timedelta(hours=1)

        with self.assertRaises(ValueError):
            timing_validation(start, end)

    def test_rejects_end_time_equal_to_start_time(self):
        start = timezone.now() + timedelta(hours=1)

        with self.assertRaises(ValueError):
            timing_validation(start, start)

    def test_accepts_valid_time_interval(self):
        # Should not raise an exception.
        timing_validation(self.start_time, self.end_time)

    # create_booking tests

    def test_creates_pending_booking(self):
        booking = create_booking(
            self.user1,
            self.room1,
            self.start_time,
            self.end_time,
        )

        self.assertIsInstance(booking, models.Booking)
        self.assertEqual(booking.user, self.user1)
        self.assertEqual(booking.room, self.room1)
        self.assertEqual(
            booking.booking_status,
            models.Booking.Status.PENDING,
        )
        self.assertGreater(booking.expires_at, timezone.now())
        self.assertLessEqual(
            booking.expires_at,
            timezone.now() + timedelta(minutes=10, seconds=1),
        )

    def test_rejects_overlapping_pending_booking(self):
        self.create_existing_booking()

        response = create_booking(
            self.user2,
            self.room1,
            self.start_time + timedelta(minutes=30),
            self.end_time + timedelta(minutes=30),
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(models.Booking.objects.count(), 1)

    def test_rejects_overlapping_confirmed_booking(self):
        self.create_existing_booking(
            status=models.Booking.Status.CONFIRMED,
        )

        response = create_booking(
            self.user2,
            self.room1,
            self.start_time,
            self.end_time,
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(models.Booking.objects.count(), 1)

    def test_allows_overlapping_time_in_a_different_room(self):
        booking = create_booking(
            self.user2,
            self.room2,
            self.start_time,
            self.end_time,
        )

        self.assertIsInstance(booking, models.Booking)
        self.assertEqual(booking.room, self.room2)

    def test_allows_adjacent_bookings(self):
        self.create_existing_booking()

        booking = create_booking(
            self.user2,
            self.room1,
            self.end_time,
            self.end_time + timedelta(hours=1),
        )

        self.assertIsInstance(booking, models.Booking)

    def test_expired_pending_booking_no_longer_blocks_slot(self):
        existing = self.create_existing_booking(
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        booking = create_booking(
            self.user2,
            self.room1,
            self.start_time,
            self.end_time,
        )

        existing.refresh_from_db()

        self.assertEqual(
            existing.booking_status,
            models.Booking.Status.EXPIRED,
        )
        self.assertIsInstance(booking, models.Booking)

    def test_expiration_does_not_allow_overlap_with_confirmed_booking(self):
        self.create_existing_booking(
            status=models.Booking.Status.CONFIRMED,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = create_booking(
            self.user2,
            self.room1,
            self.start_time,
            self.end_time,
        )

        self.assertEqual(response.status_code, 409)

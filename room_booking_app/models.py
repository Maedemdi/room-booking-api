from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import (
    RangeBoundary,
    RangeOperators,
    DateTimeRangeField,
)
from django.contrib.postgres.operations import BtreeGistExtension
from django.db.models import Func, Q


def get_expiration_time():
    return timezone.now() + timedelta(minutes=10)


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")

        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email


class Room(models.Model):
    name = models.CharField(max_length=250)
    capacity = models.PositiveIntegerField()

    def get_schedule(self):
        now = timezone.now()

        bookings = (
            Booking.objects.filter(
                room=self,
                booking_status__in=[
                    Booking.Status.PENDING,
                    Booking.Status.CONFIRMED,
                ],
            )
            .filter(
                models.Q(booking_status=Booking.Status.CONFIRMED)
                | models.Q(expires_at__gt=now)
            )
            .order_by("start_time")
        )

        for booking in bookings:
            yield {
                "start_time": booking.start_time,
                "end_time": booking.end_time,
                "status": booking.booking_status,
            }

    def __str__(self):
        return self.name


class Booking(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    class Meta:
        constraints = [
            # enforces mutual exclusion
            ExclusionConstraint(
                name="no_overlapping_active_room_booking_requests",
                expressions=[
                    (
                        TsTzRange("start_time", "end_time", RangeBoundary()),
                        RangeOperators.OVERLAPS,
                    ),
                    ("room", RangeOperators.EQUAL),
                ],
                condition=Q(booking_status__in=["PENDING", "CONFIRMED"]),
            ),
        ]

    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="bookings",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="bookings",
    )

    booking_status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )

    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=get_expiration_time)

    def __str__(self):
        return f"{self.room.name}: {self.start_time} - {self.end_time}"

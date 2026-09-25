import secrets

from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from .models import OTPVerification, User


OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_MAX_RESENDS = 5


def normalize_email(email):
    """
    Normalize an email address for authentication purposes.
    """
    return email.strip().lower()


def generate_otp():
    """
    Generate a cryptographically secure 6-digit OTP.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


def create_otp(
    email,
    purpose=OTPVerification.Purpose.REGISTRATION,
    ip_address=None,
    user_agent="",
):
    """
    Create and securely store a new OTP.

    The plaintext OTP is returned only so the caller can send it
    through the configured email backend.

    The database stores only the hashed OTP.
    """

    email = normalize_email(email)

    now = timezone.now()

    # Prevent excessive OTP creation.
    latest = (
        OTPVerification.objects
        .filter(
            email=email,
            purpose=purpose,
            is_verified=False,
        )
        .order_by("-created_at")
        .first()
    )

    if latest:
        if latest.last_sent_at:
            elapsed = (now - latest.last_sent_at).total_seconds()

            if elapsed < OTP_RESEND_COOLDOWN_SECONDS:
                remaining = int(
                    OTP_RESEND_COOLDOWN_SECONDS - elapsed
                )

                raise ValueError(
                    f"Please wait {remaining} seconds before requesting another OTP."
                )

        if latest.resend_count >= OTP_MAX_RESENDS:
            raise ValueError(
                "Maximum OTP resend limit reached. Please try again later."
            )

    otp = generate_otp()

    otp_record = OTPVerification.objects.create(
        email=email,
        otp_hash=make_password(otp),
        purpose=purpose,
        is_verified=False,
        attempts=0,
        max_attempts=OTP_MAX_ATTEMPTS,
        expires_at=now + timedelta(minutes=OTP_EXPIRY_MINUTES),
        last_sent_at=now,
        resend_count=(latest.resend_count + 1 if latest else 0),
        max_resends=OTP_MAX_RESENDS,
        ip_address=ip_address,
        user_agent=user_agent[:1000],
    )

    return otp_record, otp


def verify_otp(otp_record, submitted_otp):
    """
    Verify a submitted OTP securely.
    """

    now = timezone.now()

    if otp_record.is_verified:
        return False, "This OTP has already been used."

    if now >= otp_record.expires_at:
        return False, "This OTP has expired."

    if otp_record.attempts >= otp_record.max_attempts:
        return False, "Maximum OTP attempts reached."

    submitted_otp = submitted_otp.strip()

    if not submitted_otp.isdigit() or len(submitted_otp) != 6:
        otp_record.attempts += 1
        otp_record.save(update_fields=["attempts"])

        return False, "Invalid OTP."

    if not check_password(
        submitted_otp,
        otp_record.otp_hash,
    ):
        otp_record.attempts += 1
        otp_record.save(update_fields=["attempts"])

        return False, "Invalid OTP."

    otp_record.is_verified = True
    otp_record.verified_at = now

    otp_record.save(
        update_fields=[
            "is_verified",
            "verified_at",
        ]
    )

    return True, None


@transaction.atomic
def create_student_from_registration(
    email,
    full_name,
    phone,
    password_hash,
):
    """
    Create the student account after successful OTP verification.

    The password passed here must already be a Django password hash.
    """

    email = normalize_email(email)

    existing_user = (
        User.objects
        .select_for_update()
        .filter(username=email)
        .first()
    )

    if existing_user:
        raise ValueError(
            "An account with this email already exists."
        )

    name_parts = full_name.strip().split()

    first_name = name_parts[0] if name_parts else ""

    last_name = (
        " ".join(name_parts[1:])
        if len(name_parts) > 1
        else ""
    )

    user = User(
        username=email,
        email=email,
        first_name=first_name,
        last_name=last_name,
        phone=phone.strip(),
        role=User.Role.STUDENT,
        is_active=True,
    )

    # The password is already hashed.
    user.password = password_hash

    user.save()

    return user
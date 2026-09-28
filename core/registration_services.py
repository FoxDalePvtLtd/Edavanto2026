from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import make_password

from .auth_services import normalize_email
from .models import *


def validate_student_registration(
    full_name,
    email,
    phone,
    password,
    confirm_password,
):
    """
    Validate the registration data before sending OTP.
    """

    errors = []

    full_name = full_name.strip()
    email = normalize_email(email)
    phone = phone.strip()

    if not full_name:
        errors.append("Full name is required.")

    if not email:
        errors.append("Email is required.")

    if password != confirm_password:
        errors.append("Passwords do not match.")

    if User.objects.filter(username=email).exists():
        errors.append(
            "An account with this email already exists."
        )

    if not errors:
        try:
            validate_password(password)
        except ValidationError as exc:
            errors.extend(exc.messages)

    return {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "password_hash": (
            make_password(password)
            if not errors
            else None
        ),
        "errors": errors,
    }
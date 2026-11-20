"""
Django settings for config project.

Edvanto Education Platform
Phase 1 — Foundation
"""

import os
import secrets
from pathlib import Path

import environ


# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent


# Environment
env = environ.Env(
    DEBUG=(bool, True),
)

environ.Env.read_env(BASE_DIR / ".env")


# Security
SECRET_KEY = env(
    "SECRET_KEY",
    default="django-insecure-change-this-in-production",
)

DEBUG = env("DEBUG")

ALLOWED_HOSTS = env.list(
    "ALLOWED_HOSTS",
    default=[
        "127.0.0.1",
        "localhost",
        "192.168.1.26:8000",
        "192.168.1.26"
    ],
)


# Applications
INSTALLED_APPS = [

    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "django_rq",

    # Local
    "core",
    "admin_panel",
]

AUTH_USER_MODEL = "core.User"


# Middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# URLs
ROOT_URLCONF = "config.urls"


# Templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",

        "DIRS": [
            BASE_DIR / "templates",
        ],

        "APP_DIRS": True,

        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",

                # Custom context processor 
                "core.context_processors.admin_notification_context",
                "admin_panel.context_processors.admin_notifications",

            ],
        },
    },
]


# WSGI / ASGI
WSGI_APPLICATION = "config.wsgi.application"

ASGI_APPLICATION = "config.asgi.application"
#============================================================
#DEFAULT DATABASES
#============================================================
DATABASES = {
     "default": {
         "ENGINE": "django.db.backends.sqlite3",
         "NAME": BASE_DIR / "db.sqlite3",
     }   
 }



# DATABASES = {
#     "default": {
#         "ENGINE": "django.db.backends.postgresql",

#         "NAME": env(
#             "DB_NAME",
#             default="edvanto",
#         ),

#         "USER": env(
#             "DB_USER",
#             default="postgres",
#         ),

#         "PASSWORD": env(
#             "DB_PASSWORD",
#             default="",
#         ),

#         "HOST": env(
#             "DB_HOST",
#             default="127.0.0.1",
#         ),

#         "PORT": env(
#             "DB_PORT",
#             default="5432",
#         ),
#     }
# }


# Password validators
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# i18n
LANGUAGE_CODE = "en-us"

TIME_ZONE = "Asia/Kolkata"

USE_I18N = True

USE_TZ = True


# Static files
STATIC_URL = "/static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = BASE_DIR / "staticfiles"


# Media files
MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR / "media"


# Private media (encrypted lesson material)
# Not exposed via URL. Read-only through core:serve_lesson_material.
PRIVATE_MEDIA_ROOT = BASE_DIR / "private_media"

PRIVATE_MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

PRIVATE_MEDIA_URL = "/private-media/"   # reserved; not routed


# AES-256-GCM key for lesson material.
# MUST be 64 hex chars (32 bytes). Override via env in any real deployment.
def _default_material_key() -> str:
    """
    If no env key is provided, generate a random one for this process.

    WARNING: a per-process random key means material uploaded in one run
    cannot be decrypted after a restart. Always set
    LESSON_MATERIAL_ENCRYPTION_KEY in .env for real use.
    """
    return secrets.token_hex(32)


LESSON_MATERIAL_ENCRYPTION_KEY = env(
    "LESSON_MATERIAL_ENCRYPTION_KEY",
    default="",
)

if not LESSON_MATERIAL_ENCRYPTION_KEY:
    raise RuntimeError(
        "LESSON_MATERIAL_ENCRYPTION_KEY is not set. "
        "Generate one with:  python -c \"import secrets; print(secrets.token_hex(32))\"  "
        "and add it to .env"
    )

if len(LESSON_MATERIAL_ENCRYPTION_KEY) != 64:
    raise RuntimeError(
        "LESSON_MATERIAL_ENCRYPTION_KEY must be exactly 64 hex characters (32 bytes)."
    )


# Storage backends
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
    "private_materials": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {
            "location": PRIVATE_MEDIA_ROOT,
            "base_url": None,
        },
    },
}


# Primary key
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Login / logout
# LOGIN_URL = "login"
# LOGIN_REDIRECT_URL = "/"
# LOGOUT_REDIRECT_URL = "/"

LOGIN_URL = "core:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:home"



# =================================
# EMAIL CONFIGURATION
# =================================

EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)

EMAIL_HOST = env(
    "EMAIL_HOST",
    default="",
)

EMAIL_PORT = env.int(
    "EMAIL_PORT",
    default=587,
)

EMAIL_HOST_USER = env(
    "EMAIL_HOST_USER",
    default="",
)

EMAIL_HOST_PASSWORD = env(
    "EMAIL_HOST_PASSWORD",
    default="",
)

EMAIL_USE_TLS = env.bool(
    "EMAIL_USE_TLS",
    default=True,
)

EMAIL_USE_SSL = env.bool(
    "EMAIL_USE_SSL",
    default=False,
)

EMAIL_TIMEOUT = 20

DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    default="noreply@edvanto.local",
)



# Redis
REDIS_URL = env(
    "REDIS_URL",
    default="redis://127.0.0.1:6379/1",
)


# django-rq
RQ_QUEUES = {
    "default": {
        "URL": REDIS_URL,
        "DEFAULT_TIMEOUT": 300,
    },
}


# Logging
LOG_DIR = BASE_DIR / "logs"

LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,

    "disable_existing_loggers": False,

    "formatters": {
        "verbose": {
            "format": (
                "{levelname} {asctime} "
                "{module} {process:d} {thread:d} "
                "{message}"
            ),
            "style": "{",
        },
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },

        "file": {
            "class": "logging.FileHandler",
            "filename": LOG_DIR / "edvanto.log",
            "formatter": "verbose",
        },
    },

    "root": {
        "handlers": [
            "console",
            "file",
        ],
        "level": "INFO",
    },
}


# Development security
# SECURE_BROWSER_XSS_FILTER is deprecated in modern Django — no effect.
# SECURE_BROWSER_XSS_FILTER = True

SECURE_CONTENT_TYPE_NOSNIFF = True

X_FRAME_OPTIONS = "DENY"

# Razorpay Payment Gateway Configuration
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", default="")

"""
Authenticated, authorization-checked serving of encrypted lesson materials.

Rules:
  - Anonymous users → 302 to login.
  - Logged-in but not enrolled in the owning course → 403.
  - Enrollment must be ACCEPTED, PAID (or partially_paid per policy),
    not paused.
  - File is decrypted in-memory and streamed back.
  - Response headers forbid caching, framing, referrer leak.
  - Every access is logged.
"""

from __future__ import annotations

import mimetypes
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.http import (
    FileResponse,
    Http404,
    HttpResponseForbidden,
    HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_GET
from django.urls import reverse

from core.models import LessonMaterial, Enrollment, MaterialAccessLog
from core.services.material_crypto import decrypt_bytes


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _has_access(user, material: LessonMaterial) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    course = material.lesson.module.course

    enrollment = Enrollment.objects.filter(
        student=user,
        course=course,
    ).first()

    if not enrollment:
        return False

    if enrollment.approval_status != Enrollment.ApprovalStatus.ACCEPTED:
        return False
    if enrollment.access_paused:
        return False
    if enrollment.payment_status not in (
        Enrollment.PaymentStatus.PAID,
        Enrollment.PaymentStatus.PARTIALLY_PAID,
    ):
        return False

    return True


@login_required
@require_GET
def serve_lesson_material(request, material_id: int):
    material = get_object_or_404(
        LessonMaterial.objects.select_related(
            "lesson__module__course"
        ),
        pk=material_id,
        is_active=True,
    )

    if not _has_access(request.user, material):
        return HttpResponseForbidden("You do not have access to this material.")

    # Read the encrypted file from private storage.
    try:
        material.file.open("rb")
        blob = material.file.read()
    finally:
        material.file.close()

    try:
        plaintext = decrypt_bytes(blob)
    except Exception:
        # Never leak crypto details to the client.
        raise Http404("Material unavailable.")

    # Audit.
    MaterialAccessLog.objects.create(
        material=material,
        student=request.user,
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:1024],
    )

    content_type = (
        material.content_type
        or mimetypes.guess_type(material.original_filename)[0]
        or "application/octet-stream"
    )

    response = FileResponse(
        iter([plaintext]),
        content_type=content_type,
    )

    # INLINE — discourage "Save As" but browsers may still allow it.
    safe_name = quote(material.original_filename or material.title)
    disposition = "inline" if not material.allow_printing else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{safe_name}"'

    # Anti-cache, anti-frame, anti-referrer.
    patch_cache_control(
        response,
        no_store=True,
        no_cache=True,
        must_revalidate=True,
        private=True,
        max_age=0,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "DENY"
    response["Referrer-Policy"] = "no-referrer"
    response["Cross-Origin-Resource-Policy"] = "same-origin"

    # Optional: CSP that blocks inline scripts on rendered documents.
    # Not all browsers obey it for PDFs, but it does not hurt.
    response["Content-Security-Policy"] = (
        "default-src 'none'; img-src 'self' data:; "
        "style-src 'unsafe-inline'; sandbox"
    )

    return response
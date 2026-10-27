"""
Authenticated, authorization-checked serving and note conversion of lesson materials and resources.

Security Rules:
  - Anonymous users → 302 to login.
  - Logged-in but not enrolled (and not staff/instructor) → 403 Forbidden.
  - Cross-site / outside website access blocked via Sec-Fetch-Site and Referer checks.
  - File decrypted in-memory and rendered/streamed inline (no attachment download).
  - Documents (DOCX, TXT, MD) converted into web notes for native reading.
  - X-Frame-Options set to SAMEORIGIN (allows in-site embedded reader, denies third-party framing).
  - Every access is logged for auditability.
"""

from __future__ import annotations

import mimetypes
from urllib.parse import quote, urlparse

from django.contrib.auth.decorators import login_required
from django.http import (
    FileResponse,
    Http404,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_GET

from core.models import LessonMaterial, Resource, Enrollment, MaterialAccessLog
from core.services.material_crypto import decrypt_bytes
from core.services.doc_converter import convert_material_to_note_html


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _is_request_from_site(request) -> bool:
    """
    Checks Sec-Fetch-Site and Referer to ensure request originates
    from within the Edvanto website, blocking outside access / hotlinking.
    """
    sec_fetch_site = (request.META.get("HTTP_SEC_FETCH_SITE") or "").lower()
    if sec_fetch_site == "cross-site":
        return False

    referer = request.META.get("HTTP_REFERER", "")
    if referer:
        try:
            parsed = urlparse(referer)
            req_host = request.get_host().split(":")[0].lower()
            ref_host = parsed.netloc.split(":")[0].lower()
            if ref_host and ref_host != req_host:
                return False
        except Exception:
            return False

    return True


def _has_material_access(user, material: LessonMaterial) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True

    course = material.lesson.module.course
    if course.instructor == user:
        return True

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


def _has_resource_access(user, resource: Resource) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True

    course = resource.lesson.module.course
    if course.instructor == user:
        return True

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
    """
    Serves encrypted lesson material inline for in-browser viewing only.
    Forbids cross-site access and forces SAMEORIGIN framing.
    """
    if not _is_request_from_site(request):
        return HttpResponseForbidden("Direct external access to study materials is forbidden.")

    material = get_object_or_404(
        LessonMaterial.objects.select_related("lesson__module__course"),
        pk=material_id,
        is_active=True,
    )

    if not _has_material_access(request.user, material):
        return HttpResponseForbidden("You do not have access to this material.")

    # Read the encrypted file from private storage.
    try:
        material.file.open("rb")
        blob = material.file.read()
    except (FileNotFoundError, OSError):
        raise Http404("Material file is currently unavailable or missing on the server.")
    finally:
        try:
            material.file.close()
        except Exception:
            pass

    try:
        plaintext = decrypt_bytes(blob)
    except Exception:
        raise Http404("Material unavailable.")

    # Audit log
    MaterialAccessLog.objects.create(
        material=material,
        student=request.user,
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:1024],
    )

    content_type = (
        material.content_type
        or mimetypes.guess_type(material.original_filename)[0]
        or "application/pdf"
    )

    response = FileResponse(
        iter([plaintext]),
        content_type=content_type,
    )

    # Restrict to INLINE only (never attachment) so materials open inside the browser viewer
    safe_name = quote(material.original_filename or material.title)
    response["Content-Disposition"] = f'inline; filename="{safe_name}"'

    # Security headers: SAMEORIGIN allows embedded reader inside Edvanto, blocks 3rd party frames
    patch_cache_control(
        response,
        no_store=True,
        no_cache=True,
        must_revalidate=True,
        private=True,
        max_age=0,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "SAMEORIGIN"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    response["Cross-Origin-Embedder-Policy"] = "require-corp"

    return response


@login_required
@require_GET
def material_note_api(request, material_id: int):
    """
    Decodes and converts document materials (DOCX, TXT, MD) into clean HTML notes
    for direct in-browser reading without any file download.
    """
    if not _is_request_from_site(request):
        return HttpResponseForbidden("Direct external access is forbidden.")

    material = get_object_or_404(
        LessonMaterial.objects.select_related("lesson__module__course"),
        pk=material_id,
        is_active=True,
    )

    if not _has_material_access(request.user, material):
        return HttpResponseForbidden("You do not have access to this material.")

    try:
        material.file.open("rb")
        blob = material.file.read()
    except (FileNotFoundError, OSError):
        raise Http404("Material file missing.")
    finally:
        try:
            material.file.close()
        except Exception:
            pass

    try:
        plaintext = decrypt_bytes(blob)
    except Exception:
        raise Http404("Material unavailable.")

    # Convert to notes HTML
    note_html = convert_material_to_note_html(
        plaintext,
        filename=material.original_filename or material.title,
        material_type=material.material_type,
    )

    # Audit log
    MaterialAccessLog.objects.create(
        material=material,
        student=request.user,
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:1024],
    )

    return JsonResponse({
        "success": True,
        "id": material.pk,
        "title": material.title,
        "material_type": material.material_type,
        "original_filename": material.original_filename or material.title,
        "html": note_html,
    })


@login_required
@require_GET
def serve_resource_file(request, resource_id: int):
    """
    Serves attached Resource files safely with enrollment checks and anti-hotlink restrictions.
    """
    if not _is_request_from_site(request):
        return HttpResponseForbidden("Direct external access is forbidden.")

    resource = get_object_or_404(
        Resource.objects.select_related("lesson__module__course"),
        pk=resource_id,
    )

    if not _has_resource_access(request.user, resource):
        return HttpResponseForbidden("You do not have access to this resource.")

    if not resource.file:
        raise Http404("No file attached to this resource.")

    try:
        resource.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("Resource file is unavailable.")

    content_type = mimetypes.guess_type(resource.file.name)[0] or "application/octet-stream"
    response = FileResponse(resource.file, content_type=content_type)
    safe_name = quote(resource.title)
    response["Content-Disposition"] = f'inline; filename="{safe_name}"'

    patch_cache_control(
        response,
        no_store=True,
        no_cache=True,
        must_revalidate=True,
        private=True,
        max_age=0,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "SAMEORIGIN"
    response["Cross-Origin-Resource-Policy"] = "same-origin"

    return response

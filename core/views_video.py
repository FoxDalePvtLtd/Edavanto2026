"""
Authenticated, authorization-checked video streaming with HTTP Range support
and anti-hotlinking / external access restrictions.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from django.contrib.auth.decorators import login_required
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseForbidden,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control

from core.models import Lesson, VideoAsset, Enrollment, Course
from core.services.learning import get_lesson_video_state, VideoState


def _is_request_from_site(request) -> bool:
    """Blocks cross-site requests and external hotlinking."""
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


def _has_video_access(user, lesson: Lesson) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True

    course = lesson.module.course
    if course.instructor == user:
        return True

    if course.mode == Course.Mode.OFFLINE:
        return False

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


class RangeFileWrapper:
    """Iterates over a file-like object yielding byte chunks between start and end."""
    def __init__(self, file_obj, offset: int, length: int, chunk_size: int = 128 * 1024):
        self.file_obj = file_obj
        self.file_obj.seek(offset)
        self.remaining = length
        self.chunk_size = chunk_size

    def __iter__(self):
        return self

    def __next__(self):
        if self.remaining <= 0:
            try:
                self.file_obj.close()
            except Exception:
                pass
            raise StopIteration

        read_len = min(self.chunk_size, self.remaining)
        data = self.file_obj.read(read_len)
        if not data:
            try:
                self.file_obj.close()
            except Exception:
                pass
            raise StopIteration

        self.remaining -= len(data)
        return data


@login_required
def stream_lesson_video(request, lesson_id: int):
    """
    Streams lesson video with HTTP Range (206) support.
    Strictly forbids hotlinking or access outside the website.
    """
    if not _is_request_from_site(request):
        return HttpResponseForbidden("Direct external access to video streams is forbidden.")

    lesson = get_object_or_404(
        Lesson.objects.select_related("module__course"),
        pk=lesson_id,
    )

    if not _has_video_access(request.user, lesson):
        return HttpResponseForbidden("You do not have access to stream this video.")

    video_state = get_lesson_video_state(lesson)
    if video_state != VideoState.READY:
        if video_state == VideoState.PROCESSING:
            return HttpResponseForbidden("Video is currently processing.")
        elif video_state == VideoState.FAILED:
            return HttpResponseForbidden("Video processing failed.")
        elif video_state == VideoState.EMPTY:
            raise Http404("Video file is missing or not yet uploaded.")
        else:
            raise Http404("No video asset associated with this lesson.")

    video_asset = lesson.video_asset

    try:
        file_handle = video_asset.original_file.open("rb")
        total_size = video_asset.original_file.size
    except (FileNotFoundError, OSError):
        raise Http404("Video file is currently unavailable on disk.")

    content_type = "video/mp4"
    http_range = request.META.get("HTTP_RANGE", "")

    if http_range:
        # Range: bytes=start-end
        range_match = re.search(r"bytes=(\d+)-(\d*)", http_range)
        if range_match:
            start = int(range_match.group(1))
            end_str = range_match.group(2)
            end = int(end_str) if end_str else total_size - 1

            if start >= total_size:
                file_handle.close()
                return HttpResponse(status=416)  # Range Not Satisfiable

            end = min(end, total_size - 1)
            length = (end - start) + 1

            response = StreamingHttpResponse(
                RangeFileWrapper(file_handle, start, length),
                status=206,
                content_type=content_type,
            )
            response["Content-Range"] = f"bytes {start}-{end}/{total_size}"
            response["Content-Length"] = str(length)
        else:
            response = StreamingHttpResponse(
                RangeFileWrapper(file_handle, 0, total_size),
                status=200,
                content_type=content_type,
            )
            response["Content-Length"] = str(total_size)
    else:
        response = StreamingHttpResponse(
            RangeFileWrapper(file_handle, 0, total_size),
            status=200,
            content_type=content_type,
        )
        response["Content-Length"] = str(total_size)

    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = "inline; filename=\"lesson_video.mp4\""
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "SAMEORIGIN"
    response["Cross-Origin-Resource-Policy"] = "same-origin"

    patch_cache_control(
        response,
        private=True,
        no_cache=True,
        no_store=True,
        must_revalidate=True,
        max_age=0,
    )

    return response

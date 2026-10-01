from django.contrib import admin
from .models import *
from django.contrib import admin
from django.contrib import messages

from .services.payments import *


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "is_active",
        "is_staff",
    )
    list_filter = ("role", "is_active", "is_staff")
    search_fields = (
        "username",
        "email",
        "first_name",
        "last_name",
        "phone",
    )


@admin.register(Center)
class CenterAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "city", "state", "email")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "slug",
        "mode",
        "price",
        "status",
        "instructor",
        "center",
    )
    list_filter = (
        "mode",
        "status",
        "requires_instructor_approval",
    )
    search_fields = (
        "title",
        "slug",
        "category",
        "instructor__username",
        "instructor__email",
    )
    prepopulated_fields = {"slug": ("title",)}


@admin.register(Syllabus)
class SyllabusAdmin(admin.ModelAdmin):
    list_display = ("course", "title", "order")
    search_fields = ("title", "course__title")
    list_filter = ("course",)


@admin.register(SyllabusTopic)
class SyllabusTopicAdmin(admin.ModelAdmin):
    list_display = ("syllabus", "title", "order")
    list_filter = ("syllabus",)
    search_fields = ("title",)


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = (
        "course",
        "title",
        "order",
        "unlock_order",
    )
    search_fields = ("title", "course__title")
    list_filter = ("course",)


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = (
        "module",
        "title",
        "order",
        "unlock_order",
        "status",
        "is_published",
    )
    list_filter = ("status", "is_published")
    search_fields = (
        "title",
        "module__title",
        "module__course__title",
    )


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = (
        "lesson",
        "title",
        "resource_type",
        "created_at",
    )
    list_filter = ("resource_type",)
    search_fields = ("title", "lesson__title")


@admin.register(VideoAsset)
class VideoAssetAdmin(admin.ModelAdmin):
    list_display = (
        "lesson",
        "processing_status",
        "duration_seconds",
        "resolution",
        "created_at",
    )
    list_filter = ("processing_status",)
    search_fields = (
        "lesson__title",
        "resolution",
    )


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):

    list_display = (
        "student",
        "course",
        "payment_status",
        "approval_status",
        "progress_percent",
        "enrolled_at",
    )

    list_filter = (
        "payment_status",
        "approval_status",
        "access_paused",
    )

    search_fields = (
        "student__username",
        "student__email",
        "course__title",
    )

    readonly_fields = (
        "enrolled_at",
        "accepted_at",
        "progress_percent",
    )

@admin.register(LearningProgress)
class LearningProgressAdmin(admin.ModelAdmin):
    list_display = (
        "enrollment",
        "lesson",
        "status",
        "watched_percent",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = (
        "enrollment__student__username",
        "enrollment__student__email",
        "lesson__title",
    )


@admin.register(LearningEvent)
class LearningEventAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "event_type",
        "lesson",
        "created_at",
    )
    list_filter = ("event_type",)
    search_fields = (
        "student__username",
        "student__email",
        "lesson__title",
    )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):

    list_display = (
        "order_number",
        "student",
        "course",
        "total_amount",
        "payment_plan",
        "payment_method",
        "status",
        "created_at",
    )

    list_filter = (
        "payment_method",
        "payment_plan",
        "status",
    )

    search_fields = (
        "order_number",
        "student__username",
        "student__email",
        "course__title",
    )

    readonly_fields = (
        "order_number",
        "student",
        "course",
        "total_amount",
        "payment_plan",
        "payment_method",
        "created_at",
        "updated_at",
    )

    actions = (
        "approve_offline_requests",
        "reject_offline_requests",
    )

    @admin.action(
        description="Approve selected offline payment requests"
    )
    def approve_offline_requests(
        self,
        request,
        queryset,
    ):

        approved_count = 0
        skipped_count = 0

        for order in queryset:

            if (
                order.payment_method
                != Order.PaymentMethod.OFFLINE
            ):
                skipped_count += 1
                continue

            if order.status == Order.Status.PAID:
                skipped_count += 1
                continue

            try:
                approve_offline_payment(
                    order=order,
                    approved_by=request.user,
                )
                approved_count += 1

            except ValueError as exc:
                skipped_count += 1

                self.message_user(
                    request,
                    (
                        f"{order.order_number}: "
                        f"{exc}"
                    ),
                    level=messages.ERROR,
                )

        if approved_count:
            self.message_user(
                request,
                (
                    f"{approved_count} offline "
                    f"payment request(s) approved."
                ),
                level=messages.SUCCESS,
            )

        if skipped_count:
            self.message_user(
                request,
                (
                    f"{skipped_count} request(s) "
                    f"were skipped."
                ),
                level=messages.WARNING,
            )

    @admin.action(
        description="Reject selected offline payment requests"
    )
    def reject_offline_requests(
        self,
        request,
        queryset,
    ):

        rejected_count = 0
        skipped_count = 0

        for order in queryset:

            if (
                order.payment_method
                != Order.PaymentMethod.OFFLINE
            ):
                skipped_count += 1
                continue

            if order.status == Order.Status.PAID:
                skipped_count += 1
                continue

            try:
                reject_offline_payment(
                    order=order,
                    rejected_by=request.user,
                )
                rejected_count += 1

            except ValueError as exc:
                skipped_count += 1

                self.message_user(
                    request,
                    (
                        f"{order.order_number}: "
                        f"{exc}"
                    ),
                    level=messages.ERROR,
                )

        if rejected_count:
            self.message_user(
                request,
                (
                    f"{rejected_count} offline "
                    f"payment request(s) rejected."
                ),
                level=messages.SUCCESS,
            )

        if skipped_count:
            self.message_user(
                request,
                (
                    f"{skipped_count} request(s) "
                    f"were skipped."
                ),
                level=messages.WARNING,
            )


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):

    list_display = (
        "order",
        "amount",
        "status",
        "paid_at",
        "created_at",
    )

    list_filter = (
        "status",
    )

    search_fields = (
        "order__order_number",
        "order__student__username",
        "order__student__email",
        "razorpay_order_id",
        "razorpay_payment_id",
    )

    readonly_fields = (
        "order",
        "amount",
        "razorpay_order_id",
        "razorpay_payment_id",
        "razorpay_signature",
        "status",
        "failure_reason",
        "paid_at",
        "metadata",
        "created_at",
    )


@admin.register(InstallmentPlan)
class InstallmentPlanAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "total_installments",
        "created_at",
    )
    search_fields = ("order__order_number",)


@admin.register(Installment)
class InstallmentAdmin(admin.ModelAdmin):
    list_display = (
        "plan",
        "installment_number",
        "amount",
        "due_date",
        "status",
        "paid_at",
    )
    list_filter = ("status",)
    search_fields = ("plan__order__order_number",)


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "module",
        "assessment_type",
        "total_marks",
        "pass_percentage",
        "is_published",
        "created_at",
    )
    list_filter = (
        "assessment_type",
        "is_published",
    )
    search_fields = (
        "title",
        "module__title",
        "module__course__title",
    )


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = (
        "assessment",
        "question_type",
        "marks",
        "order",
    )
    list_filter = ("question_type",)
    search_fields = (
        "question_text",
        "assessment__title",
    )


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "assessment",
        "student",
        "score",
        "status",
        "submitted_at",
        "graded_at",
    )
    list_filter = ("status",)
    search_fields = (
        "student__username",
        "student__email",
        "assessment__title",
    )


@admin.register(DoubtThread)
class DoubtThreadAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "lesson",
        "subject",
        "status",
        "assigned_instructor",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = (
        "student__username",
        "student__email",
        "subject",
        "lesson__title",
    )


@admin.register(DoubtMessage)
class DoubtMessageAdmin(admin.ModelAdmin):
    list_display = (
        "thread",
        "sender",
        "created_at",
    )
    search_fields = (
        "sender__username",
        "sender__email",
        "thread__subject",
    )


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "course",
        "center",
        "instructor",
        "start_date",
        "status",
    )
    list_filter = ("status",)
    search_fields = (
        "name",
        "course__title",
        "center__name",
        "instructor__username",
    )


@admin.register(BatchSession)
class BatchSessionAdmin(admin.ModelAdmin):
    list_display = (
        "batch",
        "title",
        "date",
        "start_time",
        "end_time",
        "instructor",
        "status",
    )
    list_filter = ("status", "date")
    search_fields = (
        "title",
        "batch__name",
        "instructor__username",
    )


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "student",
        "status",
        "marked_by",
        "marked_at",
    )
    list_filter = ("status",)
    search_fields = (
        "student__username",
        "student__email",
        "session__title",
    )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "recipient",
        "title",
        "notification_type",
        "is_read",
        "created_at",
    )
    list_filter = (
        "notification_type",
        "is_read",
    )
    search_fields = (
        "title",
        "recipient__username",
        "recipient__email",
    )


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "notification",
        "channel",
        "status",
        "attempts",
        "sent_at",
        "created_at",
    )
    list_filter = (
        "channel",
        "status",
    )
    search_fields = (
        "notification__title",
        "notification__recipient__username",
        "notification__recipient__email",
    )


@admin.register(ConsultationBooking)
class ConsultationBookingAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "email",
        "phone",
        "preferred_date",
        "status",
        "assigned_to",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = (
        "name",
        "email",
        "phone",
        "assigned_to__username",
    )


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "course",
        "certificate_number",
        "verification_code",
        "issued_at",
        "status",
    )
    list_filter = ("status",)
    search_fields = (
        "student__username",
        "student__email",
        "certificate_number",
        "verification_code",
        "course__title",
    )


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "event_type",
        "severity",
        "ip_address",
        "created_at",
    )
    list_filter = (
        "severity",
        "event_type",
    )
    search_fields = (
        "user__username",
        "user__email",
        "event_type",
        "ip_address",
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "actor",
        "action",
        "model_name",
        "object_id",
        "ip_address",
        "created_at",
    )
    list_filter = (
        "action",
        "model_name",
    )
    search_fields = (
        "actor__username",
        "actor__email",
        "action",
        "model_name",
        "object_id",
    )
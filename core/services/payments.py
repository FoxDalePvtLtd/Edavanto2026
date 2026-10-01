from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from ..models import *

from .enrollment import *


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _get_course_amount(course):
    """
    Return the effective course price.
    Discounted price is used when available.
    """

    if (
        course.discounted_price is not None
        and course.discounted_price > 0
    ):
        return course.discounted_price

    return course.price


def _create_notification(
    recipient,
    title,
    message,
):
    """
    Create an in-app notification.

    Email delivery will be connected later through the
    centralized notification system.
    """

    return Notification.objects.create(
        recipient=recipient,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.PAYMENT,
    )


def _create_invoice(
    order,
    paid=False,
):
    """
    Create the existing invoice record for an order.

    An invoice is created only once.
    """
    invoice_number = (
        f"INV-{timezone.now():%Y%m%d%H%M%S}-"
        f"{uuid4().hex[:8].upper()}"
    )
    invoice, created = Invoice.objects.get_or_create(
        order=order,
        defaults={
            "student": order.student,
            "course": order.course,
            "amount": order.total_amount,
            "tax_amount": 0,
            "total_amount": order.total_amount,
            "invoice_number": invoice_number,
            "status": (
                Invoice.Status.PAID
                if paid
                else Invoice.Status.ISSUED
            ),
            "issued_at": timezone.now(),
            "paid_at": (
                timezone.now()
                if paid
                else None
            ),
        },
    )

    if not created and paid:
        invoice.status = Invoice.Status.PAID
        invoice.paid_at = timezone.now()
        invoice.save(
            update_fields=[
                "status",
                "paid_at",
                "updated_at",
            ]
        )

    return invoice


# ============================================================
# TEST PAYMENT
# ============================================================

@transaction.atomic
def create_test_payment(
    *,
    student,
    course,
):
    """
    Create and immediately complete a development/test payment.

    This is NOT a real payment gateway.

    Flow:
        Order → PaymentTransaction → Enrollment → Access
    """

    if student.role != User.Role.STUDENT:
        raise ValueError(
            "Only students can make course payments."
        )

    if course.status != Course.Status.PUBLISHED:
        raise ValueError(
            "This course is not available for purchase."
        )

    existing_enrollment = (
        Enrollment.objects
        .filter(
            student=student,
            course=course,
        )
        .first()
    )

    if existing_enrollment:
        raise ValueError(
            "You already have an enrollment for this course."
        )

    amount = _get_course_amount(course)

    if amount is None or amount <= 0:
        raise ValueError(
            "This course does not have a valid price."
        )

    order = Order.objects.create(
        student=student,
        course=course,
        order_number=(
            f"TEST-{timezone.now():%Y%m%d%H%M%S}-"
            f"{uuid4().hex[:8].upper()}"
        ),
        total_amount=amount,
        payment_plan=Order.PaymentPlan.FULL,
        payment_method=Order.PaymentMethod.TEST,
        status=Order.Status.CREATED,
    )

    payment_transaction = PaymentTransaction.objects.create(
        order=order,
        amount=amount,
        status=PaymentTransaction.Status.SUCCESS,
        paid_at=timezone.now(),
        metadata={
            "payment_method": Order.PaymentMethod.TEST,
            "test_payment": True,
        },
    )

    order.status = Order.Status.PAID
    order.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    enrollment, _ = create_enrollment(
        student,
        course,
    )

    if enrollment is None:
        raise ValueError(
            "Enrollment could not be created."
        )

    enrollment.payment_status = (
        Enrollment.PaymentStatus.PAID
    )

    if course.requires_instructor_approval:
        enrollment.approval_status = (
            Enrollment.ApprovalStatus.PENDING
        )
    else:
        enrollment.approval_status = (
            Enrollment.ApprovalStatus.ACCEPTED
        )
        enrollment.accepted_at = timezone.now()

    enrollment.save(
        update_fields=[
            "payment_status",
            "approval_status",
            "accepted_at",
        ]
    )

    if (
        enrollment.approval_status
        == Enrollment.ApprovalStatus.ACCEPTED
    ):
        initialize_learning_progress(
            enrollment
        )

    _create_invoice(
        order,
        paid=True,
    )

    _create_notification(
        recipient=student,
        title="Test payment successful",
        message=(
            f"Your test payment for "
            f"{course.title} was successful."
        ),
    )

    return order, payment_transaction, enrollment


# ============================================================
# OFFLINE PAYMENT REQUEST
# ============================================================

@transaction.atomic
def create_offline_payment_request(
    *,
    student,
    course,
):
    """
    Create an offline payment request.

    No payment is considered successful at this stage.

    Flow:
        Order CREATED
        PaymentTransaction CREATED
        Enrollment PENDING
    """

    if student.role != User.Role.STUDENT:
        raise ValueError(
            "Only students can request course enrollment."
        )

    if course.status != Course.Status.PUBLISHED:
        raise ValueError(
            "This course is not available for enrollment."
        )

    existing_enrollment = (
        Enrollment.objects
        .filter(
            student=student,
            course=course,
        )
        .first()
    )

    if existing_enrollment:
        raise ValueError(
            "You already have an enrollment request "
            "for this course."
        )

    amount = _get_course_amount(course)

    if amount is None or amount <= 0:
        raise ValueError(
            "This course does not have a valid price."
        )

    order = Order.objects.create(
        student=student,
        course=course,
        order_number=(
            f"OFF-{timezone.now():%Y%m%d%H%M%S}-"
            f"{uuid4().hex[:8].upper()}"
        ),
        total_amount=amount,
        payment_plan=Order.PaymentPlan.FULL,
        payment_method=Order.PaymentMethod.OFFLINE,
        status=Order.Status.CREATED,
    )

    payment_transaction = PaymentTransaction.objects.create(
        order=order,
        amount=amount,
        status=PaymentTransaction.Status.CREATED,
        metadata={
            "payment_method": Order.PaymentMethod.OFFLINE,
            "offline_request": True,
        },
    )

    enrollment, _ = create_enrollment(
        student,
        course,
    )

    if enrollment is None:
        raise ValueError(
            "Enrollment could not be created."
        )

    enrollment.payment_status = (
        Enrollment.PaymentStatus.PENDING
    )

    enrollment.approval_status = (
        Enrollment.ApprovalStatus.PENDING
    )

    enrollment.save(
        update_fields=[
            "payment_status",
            "approval_status",
        ]
    )

    _create_invoice(
        order,
        paid=False,
    )

    _create_notification(
        recipient=student,
        title="Offline payment request submitted",
        message=(
            f"Your offline payment request for "
            f"{course.title} has been submitted "
            f"and is waiting for admin approval."
        ),
    )

    return order, payment_transaction, enrollment


# ============================================================
# ADMIN APPROVE OFFLINE PAYMENT
# ============================================================

@transaction.atomic
def approve_offline_payment(
    *,
    order,
    approved_by=None,
):
    """
    Approve an offline payment request.

    Approval means:
        Payment confirmed
        Order paid
        Enrollment accepted
        Learning access initialized
    """

    if order.payment_method != Order.PaymentMethod.OFFLINE:
        raise ValueError(
            "This order is not an offline payment request."
        )

    if order.status == Order.Status.PAID:
        raise ValueError(
            "This payment has already been approved."
        )

    enrollment = (
        Enrollment.objects
        .select_for_update()
        .filter(
            student=order.student,
            course=order.course,
        )
        .first()
    )

    if enrollment is None:
        raise ValueError(
            "Enrollment for this order was not found."
        )

    payment_transaction = (
        order.transactions
        .select_for_update()
        .filter(
            status=PaymentTransaction.Status.CREATED
        )
        .order_by("-created_at")
        .first()
    )

    if payment_transaction is None:
        raise ValueError(
            "Pending payment transaction was not found."
        )

    now = timezone.now()

    payment_transaction.status = (
        PaymentTransaction.Status.SUCCESS
    )
    payment_transaction.paid_at = now
    payment_transaction.metadata = {
        **payment_transaction.metadata,
        "approved_by": (
            approved_by.pk
            if approved_by
            else None
        ),
        "approved_at": now.isoformat(),
    }

    payment_transaction.save(
        update_fields=[
            "status",
            "paid_at",
            "metadata",
        ]
    )

    order.status = Order.Status.PAID
    order.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    enrollment.payment_status = (
        Enrollment.PaymentStatus.PAID
    )
    enrollment.approval_status = (
        Enrollment.ApprovalStatus.ACCEPTED
    )
    enrollment.accepted_at = now

    enrollment.save(
        update_fields=[
            "payment_status",
            "approval_status",
            "accepted_at",
        ]
    )

    initialize_learning_progress(
        enrollment
    )

    _create_invoice(
        order,
        paid=True,
    )

    _create_notification(
        recipient=order.student,
        title="Payment approved",
        message=(
            f"Your offline payment for "
            f"{order.course.title} has been approved. "
            f"Your course access is now active."
        ),
    )

    return order, payment_transaction, enrollment


# ============================================================
# ADMIN REJECT OFFLINE PAYMENT
# ============================================================

@transaction.atomic
def reject_offline_payment(
    *,
    order,
    rejected_by=None,
    reason="",
):
    """
    Reject an offline payment request.
    """

    if order.payment_method != Order.PaymentMethod.OFFLINE:
        raise ValueError(
            "This order is not an offline payment request."
        )

    if order.status == Order.Status.PAID:
        raise ValueError(
            "A paid order cannot be rejected."
        )

    enrollment = (
        Enrollment.objects
        .select_for_update()
        .filter(
            student=order.student,
            course=order.course,
        )
        .first()
    )

    if enrollment is None:
        raise ValueError(
            "Enrollment for this order was not found."
        )

    payment_transaction = (
        order.transactions
        .select_for_update()
        .filter(
            status=PaymentTransaction.Status.CREATED
        )
        .order_by("-created_at")
        .first()
    )

    now = timezone.now()

    if payment_transaction:
        payment_transaction.status = (
            PaymentTransaction.Status.FAILED
        )
        payment_transaction.failure_reason = (
            reason or "Offline payment request rejected."
        )
        payment_transaction.metadata = {
            **payment_transaction.metadata,
            "rejected_by": (
                rejected_by.pk
                if rejected_by
                else None
            ),
            "rejected_at": now.isoformat(),
        }

        payment_transaction.save(
            update_fields=[
                "status",
                "failure_reason",
                "metadata",
            ]
        )

    order.status = Order.Status.CANCELLED
    order.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    enrollment.payment_status = (
        Enrollment.PaymentStatus.FAILED
    )
    enrollment.approval_status = (
        Enrollment.ApprovalStatus.REJECTED
    )

    enrollment.save(
        update_fields=[
            "payment_status",
            "approval_status",
        ]
    )

    _create_notification(
        recipient=order.student,
        title="Offline payment request rejected",
        message=(
            f"Your offline payment request for "
            f"{order.course.title} was rejected."
            + (
                f" Reason: {reason}"
                if reason
                else ""
            )
        ),
    )

    return order, payment_transaction, enrollment
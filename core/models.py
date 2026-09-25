from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


# =========================================================
# USER
# =========================================================

class User(AbstractUser):

    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        INSTRUCTOR = "instructor", "Instructor"
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STUDENT,
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
    )

    profile_photo = models.ImageField(
        upload_to="profiles/",
        blank=True,
        null=True,
    )

    bio = models.TextField(
        blank=True,
    )

    def __str__(self):
        return self.get_full_name() or self.username




# ============================================================
# OTP VERIFICATION
# ============================================================

class OTPVerification(models.Model):

    class Purpose(models.TextChoices):
        REGISTRATION = "registration", "Registration"
        PASSWORD_RESET = "password_reset", "Password Reset"
        EMAIL_CHANGE = "email_change", "Email Change"
        PHONE_VERIFICATION = "phone_verification", "Phone Verification"

    # --------------------------------------------------------
    # Verification destination
    # --------------------------------------------------------

    email = models.EmailField()

    # --------------------------------------------------------
    # OTP security
    # --------------------------------------------------------

    otp_hash = models.CharField(max_length=128)

    purpose = models.CharField(
        max_length=30,
        choices=Purpose.choices,
    )

    # --------------------------------------------------------
    # Verification state
    # --------------------------------------------------------

    is_verified = models.BooleanField(default=False)

    attempts = models.PositiveIntegerField(default=0)

    max_attempts = models.PositiveIntegerField(default=5)

    # --------------------------------------------------------
    # Expiry / resend protection
    # --------------------------------------------------------

    expires_at = models.DateTimeField()

    last_sent_at = models.DateTimeField()

    resend_count = models.PositiveIntegerField(default=0)

    max_resends = models.PositiveIntegerField(default=5)

    # --------------------------------------------------------
    # Security metadata
    # --------------------------------------------------------

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
    )

    user_agent = models.TextField(
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["email", "purpose", "is_verified"]
            ),
            models.Index(
                fields=["expires_at"]
            ),
        ]

    def __str__(self):
        return f"{self.email} - {self.purpose}"
# =========================================================
# CENTER
# =========================================================

class Center(models.Model):

    name = models.CharField(max_length=150)

    address = models.TextField(
        blank=True,
    )

    city = models.CharField(
        max_length=100,
        blank=True,
    )

    state = models.CharField(
        max_length=100,
        blank=True,
    )

    postal_code = models.CharField(
        max_length=20,
        blank=True,
    )

    contact_number = models.CharField(
        max_length=20,
        blank=True,
    )

    email = models.EmailField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return self.name


# =========================================================
# COURSE
# =========================================================

class Course(models.Model):

    class Mode(models.TextChoices):
        ONLINE = "online", "Online"
        OFFLINE = "offline", "Offline"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    title = models.CharField(
        max_length=200,
    )

    slug = models.SlugField(
        unique=True,
    )

    description = models.TextField()

    category = models.CharField(
        max_length=100,
        blank=True,
    )

    mode = models.CharField(
        max_length=20,
        choices=Mode.choices,
        default=Mode.ONLINE,
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    discounted_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )

    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="courses_taught",
        limit_choices_to={"role": User.Role.INSTRUCTOR},
    )

    center = models.ForeignKey(
        Center,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="courses",
    )

    thumbnail = models.ImageField(
        upload_to="courses/",
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    requires_instructor_approval = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return self.title


# =========================================================
# SYLLABUS
# =========================================================

class Syllabus(models.Model):

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="syllabi",
    )

    title = models.CharField(
        max_length=200,
    )

    description = models.TextField(
        blank=True,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.course.title} - {self.title}"


# =========================================================
# SYLLABUS TOPIC
# =========================================================

class SyllabusTopic(models.Model):

    syllabus = models.ForeignKey(
        Syllabus,
        on_delete=models.CASCADE,
        related_name="topics",
    )

    title = models.CharField(
        max_length=200,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.title


# =========================================================
# MODULE
# =========================================================

class Module(models.Model):

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="modules",
    )

    title = models.CharField(
        max_length=200,
    )

    description = models.TextField(
        blank=True,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    unlock_order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.course.title} - {self.title}"


# =========================================================
# LESSON
# =========================================================

class Lesson(models.Model):

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name="lessons",
    )

    title = models.CharField(
        max_length=200,
    )

    description = models.TextField(
        blank=True,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    unlock_order = models.PositiveIntegerField(
        default=0,
    )

    duration_seconds = models.PositiveIntegerField(
        default=0,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    is_published = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.title


# =========================================================
# RESOURCE
# =========================================================

class Resource(models.Model):

    class ResourceType(models.TextChoices):
        PDF = "pdf", "PDF"
        DOCUMENT = "document", "Document"
        IMAGE = "image", "Image"
        LINK = "link", "External Link"
        OTHER = "other", "Other"

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="resources",
    )

    title = models.CharField(
        max_length=200,
    )

    resource_type = models.CharField(
        max_length=20,
        choices=ResourceType.choices,
        default=ResourceType.OTHER,
    )

    file = models.FileField(
        upload_to="resources/",
        blank=True,
        null=True,
    )

    external_url = models.URLField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return self.title


# =========================================================
# VIDEO ASSET
# =========================================================

class VideoAsset(models.Model):

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    lesson = models.OneToOneField(
        Lesson,
        on_delete=models.CASCADE,
        related_name="video_asset",
    )

    original_file = models.FileField(
        upload_to="videos/original/",
    )

    hls_manifest = models.CharField(
        max_length=500,
        blank=True,
    )

    duration_seconds = models.PositiveIntegerField(
        default=0,
    )

    resolution = models.CharField(
        max_length=50,
        blank=True,
    )

    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
    )

    processing_error = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    processed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    def __str__(self):
        return f"Video - {self.lesson.title}"


# =========================================================
# ENROLLMENT
# =========================================================

class Enrollment(models.Model):

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    class ApprovalStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="enrollments",
        limit_choices_to={"role": User.Role.STUDENT},
    )

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="enrollments",
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )

    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )

    progress_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[
            MinValueValidator(0),
        ],
    )

    enrolled_at = models.DateTimeField(
        auto_now_add=True,
    )

    accepted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    access_paused = models.BooleanField(
        default=False,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"],
                name="unique_student_course_enrollment",
            ),
        ]

    def __str__(self):
        return f"{self.student} - {self.course}"


# =========================================================
# LEARNING PROGRESS
# =========================================================

class LearningProgress(models.Model):

    class Status(models.TextChoices):
        LOCKED = "locked", "Locked"
        UNLOCKED = "unlocked", "Unlocked"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.CASCADE,
        related_name="lesson_progress",
    )

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="student_progress",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.LOCKED,
    )

    watched_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    last_position_seconds = models.PositiveIntegerField(
        default=0,
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["enrollment", "lesson"],
                name="unique_enrollment_lesson_progress",
            ),
        ]

    def __str__(self):
        return f"{self.enrollment} - {self.lesson}"


# =========================================================
# LEARNING EVENT
# =========================================================

class LearningEvent(models.Model):

    class EventType(models.TextChoices):
        VIDEO_STARTED = "video_started", "Video Started"
        VIDEO_PROGRESS = "video_progress", "Video Progress"
        VIDEO_COMPLETED = "video_completed", "Video Completed"
        LESSON_OPENED = "lesson_opened", "Lesson Opened"
        LESSON_COMPLETED = "lesson_completed", "Lesson Completed"
        ASSESSMENT_STARTED = "assessment_started", "Assessment Started"
        ASSESSMENT_COMPLETED = "assessment_completed", "Assessment Completed"
        RESOURCE_OPENED = "resource_opened", "Resource Opened"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="learning_events",
    )

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.CASCADE,
        related_name="learning_events",
    )

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="learning_events",
    )

    event_type = models.CharField(
        max_length=40,
        choices=EventType.choices,
    )

    progress = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]


# =========================================================
# ORDER
# =========================================================

class Order(models.Model):

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PAID = "paid", "Paid"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentPlan(models.TextChoices):
        FULL = "full", "Full"
        INSTALLMENT = "installment", "Installment"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="orders",
    )

    order_number = models.CharField(
        max_length=50,
        unique=True,
    )

    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    payment_plan = models.CharField(
        max_length=20,
        choices=PaymentPlan.choices,
        default=PaymentPlan.FULL,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATED,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return self.order_number


# =========================================================
# PAYMENT TRANSACTION
# =========================================================

class PaymentTransaction(models.Model):

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="transactions",
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    razorpay_order_id = models.CharField(
        max_length=100,
        blank=True,
    )

    razorpay_payment_id = models.CharField(
        max_length=100,
        blank=True,
    )

    razorpay_signature = models.CharField(
        max_length=255,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATED,
    )

    failure_reason = models.TextField(
        blank=True,
    )

    paid_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )


# =========================================================
# INSTALLMENT PLAN
# =========================================================

class InstallmentPlan(models.Model):

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name="installment_plan",
    )

    total_installments = models.PositiveIntegerField()

    created_at = models.DateTimeField(
        auto_now_add=True,
    )


# =========================================================
# INSTALLMENT
# =========================================================

class Installment(models.Model):

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"
        CANCELLED = "cancelled", "Cancelled"

    plan = models.ForeignKey(
        InstallmentPlan,
        on_delete=models.CASCADE,
        related_name="installments",
    )

    installment_number = models.PositiveIntegerField()

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    due_date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    razorpay_payment_id = models.CharField(
        max_length=100,
        blank=True,
    )

    paid_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    overdue_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "installment_number"],
                name="unique_installment_number_per_plan",
            ),
        ]

    def __str__(self):
        return f"{self.plan.order.order_number} - {self.installment_number}"


# =========================================================
# ASSESSMENT
# =========================================================

class Assessment(models.Model):

    class AssessmentType(models.TextChoices):
        QUIZ = "quiz", "Quiz"
        ASSIGNMENT = "assignment", "Assignment"

    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name="assessments",
    )

    title = models.CharField(
        max_length=200,
    )

    description = models.TextField(
        blank=True,
    )

    assessment_type = models.CharField(
        max_length=20,
        choices=AssessmentType.choices,
        default=AssessmentType.QUIZ,
    )

    unlock_order = models.PositiveIntegerField(
        default=0,
    )

    total_marks = models.PositiveIntegerField(
        default=0,
    )

    pass_percentage = models.PositiveIntegerField(
        default=50,
    )

    due_date = models.DateTimeField(
        null=True,
        blank=True,
    )

    time_limit_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    attempts_allowed = models.PositiveIntegerField(
        default=1,
    )

    is_published = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return self.title


# =========================================================
# QUESTION
# =========================================================

class Question(models.Model):

    class QuestionType(models.TextChoices):
        MCQ = "mcq", "MCQ"
        TEXT = "text", "Text"
        FILE = "file", "File"

    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name="questions",
    )

    question_text = models.TextField()

    question_type = models.CharField(
        max_length=20,
        choices=QuestionType.choices,
        default=QuestionType.MCQ,
    )

    options = models.JSONField(
        default=list,
        blank=True,
    )

    correct_answer = models.TextField(
        blank=True,
    )

    marks = models.PositiveIntegerField(
        default=1,
    )

    explanation = models.TextField(
        blank=True,
    )

    order = models.PositiveIntegerField(
        default=0,
    )

    class Meta:
        ordering = ["order"]


# =========================================================
# SUBMISSION
# =========================================================

class Submission(models.Model):

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        GRADED = "graded", "Graded"
        RETURNED = "returned", "Returned"

    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name="submissions",
    )

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assessment_submissions",
    )

    answers = models.JSONField(
        default=dict,
        blank=True,
    )

    uploaded_file = models.FileField(
        upload_to="submissions/",
        blank=True,
        null=True,
    )

    score = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUBMITTED,
    )

    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="graded_submissions",
    )

    graded_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    submitted_at = models.DateTimeField(
        auto_now_add=True,
    )


# =========================================================
# DOUBT THREAD
# =========================================================

class DoubtThread(models.Model):

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In Progress"
        ANSWERED = "answered", "Answered"
        RESOLVED = "resolved", "Resolved"
        REOPENED = "reopened", "Reopened"
        CLOSED = "closed", "Closed"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="doubt_threads",
    )

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.CASCADE,
        related_name="doubt_threads",
    )

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="doubt_threads",
    )

    subject = models.CharField(
        max_length=200,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )

    assigned_instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_doubts",
        limit_choices_to={"role": User.Role.INSTRUCTOR},
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )


# =========================================================
# DOUBT MESSAGE
# =========================================================

class DoubtMessage(models.Model):

    thread = models.ForeignKey(
        DoubtThread,
        on_delete=models.CASCADE,
        related_name="messages",
    )

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="doubt_messages",
    )

    message = models.TextField()

    attachment = models.FileField(
        upload_to="doubts/",
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )


# =========================================================
# BATCH
# =========================================================

class Batch(models.Model):

    class Status(models.TextChoices):
        UPCOMING = "upcoming", "Upcoming"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="batches",
    )

    center = models.ForeignKey(
        Center,
        on_delete=models.PROTECT,
        related_name="batches",
    )

    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="batches_taught",
        limit_choices_to={"role": User.Role.INSTRUCTOR},
    )

    name = models.CharField(
        max_length=150,
    )

    start_date = models.DateField()

    end_date = models.DateField(
        null=True,
        blank=True,
    )

    capacity = models.PositiveIntegerField(
        default=0,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UPCOMING,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return self.name


# =========================================================
# BATCH SESSION
# =========================================================

class BatchSession(models.Model):

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="sessions",
    )

    title = models.CharField(
        max_length=200,
    )

    date = models.DateField()

    start_time = models.TimeField()

    end_time = models.TimeField()

    room = models.CharField(
        max_length=100,
        blank=True,
    )

    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="batch_sessions",
        limit_choices_to={"role": User.Role.INSTRUCTOR},
    )

    notes = models.TextField(
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )


# =========================================================
# ATTENDANCE
# =========================================================

class Attendance(models.Model):

    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"
        LATE = "late", "Late"
        EXCUSED = "excused", "Excused"

    session = models.ForeignKey(
        BatchSession,
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="attendance_records",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
    )

    remarks = models.TextField(
        blank=True,
    )

    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="attendance_marked",
    )

    marked_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "student"],
                name="unique_attendance_per_session_student",
            ),
        ]


# =========================================================
# NOTIFICATION
# =========================================================

class Notification(models.Model):

    class NotificationType(models.TextChoices):
        ENROLLMENT = "enrollment", "Enrollment"
        PAYMENT = "payment", "Payment"
        INSTALLMENT = "installment", "Installment"
        COURSE = "course", "Course"
        ASSESSMENT = "assessment", "Assessment"
        DOUBT = "doubt", "Doubt"
        BATCH = "batch", "Batch"
        CERTIFICATE = "certificate", "Certificate"
        SYSTEM = "system", "System"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    title = models.CharField(
        max_length=200,
    )

    message = models.TextField()

    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
    )

    is_read = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )


# =========================================================
# NOTIFICATION DELIVERY
# =========================================================

class NotificationDelivery(models.Model):

    class Channel(models.TextChoices):
        IN_APP = "in_app", "In App"
        EMAIL = "email", "Email"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )

    channel = models.CharField(
        max_length=20,
        choices=Channel.choices,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    attempts = models.PositiveIntegerField(
        default=0,
    )

    sent_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    error_message = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )


# =========================================================
# CONSULTATION BOOKING
# =========================================================

class ConsultationBooking(models.Model):

    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CLOSED = "closed", "Closed"

    name = models.CharField(
        max_length=150,
    )

    email = models.EmailField()

    phone = models.CharField(
        max_length=20,
    )

    preferred_date = models.DateTimeField(
        null=True,
        blank=True,
    )

    message = models.TextField(
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consultations_assigned",
    )

    internal_notes = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )


# =========================================================
# CERTIFICATE
# =========================================================

class Certificate(models.Model):

    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        REVOKED = "revoked", "Revoked"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="certificates",
    )

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="certificates",
    )

    certificate_number = models.CharField(
        max_length=100,
        unique=True,
    )

    verification_code = models.CharField(
        max_length=100,
        unique=True,
    )

    issued_at = models.DateTimeField(
        auto_now_add=True,
    )

    certificate_file = models.FileField(
        upload_to="certificates/",
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ISSUED,
    )

    def __str__(self):
        return self.certificate_number


# =========================================================
# SECURITY EVENT
# =========================================================

class SecurityEvent(models.Model):

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="security_events",
    )

    event_type = models.CharField(
        max_length=100,
    )

    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
        default=Severity.INFO,
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
    )

    user_agent = models.TextField(
        blank=True,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]


# =========================================================
# AUDIT LOG
# =========================================================

class AuditLog(models.Model):

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )

    action = models.CharField(
        max_length=100,
    )

    model_name = models.CharField(
        max_length=100,
    )

    object_id = models.CharField(
        max_length=100,
        blank=True,
    )

    changes = models.JSONField(
        default=dict,
        blank=True,
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]
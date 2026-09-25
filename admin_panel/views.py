from django.shortcuts import render


# ==================================================
# DASHBOARD
# ==================================================

def dashboard(request):
    return render(
        request,
        "dashboard.html",
    )


# ==================================================
# USERS
# ==================================================

def user_list(request):
    return render(
        request,
        "users/list.html",
    )


def user_form(request):
    return render(
        request,
        "users/form.html",
    )


# ==================================================
# COURSES
# ==================================================

def course_dashboard(request):
    return render(
        request,
        "courses/dashboard.html",
    )


def course_form(request):
    return render(
        request,
        "courses/form.html",
    )


# ==================================================
# SYLLABUS
# ==================================================

def syllabus_course_list(request):
    return render(
        request,
        "syllabus/courselist.html",
    )


def syllabus_curriculum(request):
    return render(
        request,
        "syllabus/curriculum.html",
    )


def syllabus_media_lesson(request):
    return render(
        request,
        "syllabus/media_lesson.html",
    )


# ==================================================
# ENROLLMENTS
# ==================================================

def enrollment_list(request):
    return render(
        request,
        "enrollments/enroll_list.html",
    )


# ==================================================
# PAYMENTS
# ==================================================

def payment_list(request):
    return render(
        request,
        "payments/list.html",
    )


def payment_installments(request):
    return render(
        request,
        "payments/installments.html",
    )


# ==================================================
# BATCHES
# ==================================================

def batch_list(request):
    return render(
        request,
        "batches/list.html",
    )


def batch_sessions(request):
    return render(
        request,
        "batches/sessions.html",
    )


def batch_attendance(request):
    return render(
        request,
        "batches/attendance.html",
    )


# ==================================================
# ASSESSMENTS
# ==================================================

def assessment_list(request):
    return render(
        request,
        "assessments/list.html",
    )


def assessment_questions(request):
    return render(
        request,
        "assessments/questions.html",
    )


def assessment_submissions(request):
    return render(
        request,
        "assessments/submissions.html",
    )


# ==================================================
# DOUBTS
# ==================================================

def doubt_list(request):
    return render(
        request,
        "doubts/list.html",
    )


# ==================================================
# NOTIFICATIONS
# ==================================================

def notification_list(request):
    return render(
        request,
        "notifications/list.html",
    )


# ==================================================
# CONSULTATIONS
# ==================================================

def consultation_list(request):
    return render(
        request,
        "consultations/list.html",
    )


# ==================================================
# CERTIFICATES
# ==================================================

def certificate_list(request):
    return render(
        request,
        "certificates/list.html",
    )


# ==================================================
# REPORTS
# ==================================================

def report_dashboard(request):
    return render(
        request,
        "reports/dashboard.html",
    )


# ==================================================
# SECURITY
# ==================================================

def security_dashboard(request):
    return render(
        request,
        "security/dashboard.html",
    )
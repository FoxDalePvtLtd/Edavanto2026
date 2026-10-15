from django.urls import path

from . import views


app_name = "admin_panel"


urlpatterns = [

    # DASHBOARD
    path("", views.dashboard, name="dashboard"),    

    # USERS
    path("users/", views.user_list, name="user_list"),
    path("users/add/", views.user_form, name="user_form"),
    path("users/<int:user_id>/edit/", views.user_form, name="user_edit"),
    path(
        "users/<int:user_id>/toggle-active/",
        views.user_toggle_active,
        name="user_toggle_active",
    ),

    # COURSES
    path("courses/", views.course_dashboard, name="course_dashboard"),
    path("courses/new/", views.course_form, name="course_create"),
    path(
        "courses/<int:course_id>/edit/",
        views.course_form,
        name="course_form",
    ),

    # SYLLABUS / CURRICULUM
    path(
        "syllabus/",
        views.syllabus_course_list,
        name="syllabus_course_list",
    ),
    path(
        "syllabus/course/<int:course_id>/",
        views.syllabus_curriculum,
        name="syllabus_curriculum",
    ),

    # ---------- Modules ----------
    path(
        "syllabus/course/<int:course_id>/modules/new/",
        views.module_create,
        name="module_create",
    ),
    path(
        "syllabus/course/<int:course_id>/modules/<int:module_id>/edit/",
        views.module_edit,
        name="module_edit",
    ),
    path(
        "syllabus/course/<int:course_id>/modules/<int:module_id>/delete/",
        views.module_delete,
        name="module_delete",
    ),

    # ---------- Lessons ----------
    path(
        "syllabus/course/<int:course_id>/modules/<int:module_id>/lessons/new/",
        views.lesson_create,
        name="lesson_create",
    ),
    path(
        "syllabus/course/<int:course_id>/modules/<int:module_id>"
        "/lessons/<int:lesson_id>/edit/",
        views.lesson_edit,
        name="lesson_edit",
    ),
    path(
        "syllabus/course/<int:course_id>/modules/<int:module_id>"
        "/lessons/<int:lesson_id>/delete/",
        views.lesson_delete,
        name="lesson_delete",
    ),

    # ---------- Lesson Media ----------
    path(
        "syllabus/course/<int:course_id>/modules/<int:module_id>"
        "/lessons/<int:lesson_id>/media/",
        views.syllabus_media_lesson,
        name="syllabus_media_lesson",
    ),

    # ENROLLMENTS
    path("enrollments/", views.enrollment_list, name="enrollment_list"),

    # PAYMENTS
    path("payments/", views.payment_list, name="payment_list"),
    path(
        "payments/installments/",
        views.payment_installments,
        name="payment_installments",
    ),

    # BATCHES
    path("batches/", views.batch_list, name="batch_list"),
    path("batches/sessions/", views.batch_sessions, name="batch_sessions"),
    path("batches/attendance/", views.batch_attendance, name="batch_attendance"),

    # ASSESSMENTS
    path("assessments/", views.assessment_list, name="assessment_list"),
    path(
        "assessments/questions/",
        views.assessment_questions,
        name="assessment_questions",
    ),
    path(
        "assessments/submissions/",
        views.assessment_submissions,
        name="assessment_submissions",
    ),

    path("doubts/", views.doubt_list, name="doubt_list"),

    # NOTIFICATIONS
    path("notifications/", views.notification_list, name="notification_list"),

    # CONSULTATIONS
    path("consultations/", views.consultation_list, name="consultation_list"),

    # CERTIFICATES
    path("certificates/", views.certificate_list, name="certificate_list"),

    # REPORTS
    path("reports/", views.report_dashboard, name="report_dashboard"),

    # SECURITY
    path("security/", views.security_dashboard, name="security_dashboard"),

    path(
        "syllabus/course/<int:course_id>/modules/<int:module_id>"
        "/lessons/<int:lesson_id>/materials/new/",
        views.lesson_material_create,
        name="lesson_material_create",
    ),
    path(
        "syllabus/course/<int:course_id>/modules/<int:module_id>"
        "/lessons/<int:lesson_id>/materials/<int:material_id>/delete/",
        views.lesson_material_delete,
        name="lesson_material_delete",
    ),

        # ---------- Video ----------
    path(
        "syllabus/course/<int:course_id>/modules/<int:module_id>"
        "/lessons/<int:lesson_id>/video/",
        views.lesson_video_upload,
        name="lesson_video_upload",
    ),
    path(
        "syllabus/course/<int:course_id>/modules/<int:module_id>"
        "/lessons/<int:lesson_id>/video/delete/",
        views.lesson_video_delete,
        name="lesson_video_delete",
    ),

    # ---------- Resource links ----------
    path(
        "syllabus/course/<int:course_id>/modules/<int:module_id>"
        "/lessons/<int:lesson_id>/links/new/",
        views.lesson_resource_create,
        name="lesson_resource_create",
    ),
    path(
        "syllabus/course/<int:course_id>/modules/<int:module_id>"
        "/lessons/<int:lesson_id>/links/<int:resource_id>/delete/",
        views.lesson_resource_delete,
        name="lesson_resource_delete",
    ),
]
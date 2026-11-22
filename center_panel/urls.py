from django.urls import path
from . import views

app_name = "center_panel"

urlpatterns = [
    # DASHBOARD
    path("", views.dashboard, name="dashboard"),

    # COURSES
    path("courses/", views.course_list, name="course_list"),
    path("courses/new/", views.course_create, name="course_create"),
    path("courses/<int:course_id>/edit/", views.course_edit, name="course_edit"),
    path("courses/<int:course_id>/submit-approval/", views.course_submit_approval, name="course_submit_approval"),
    path("courses/<int:course_id>/curriculum/", views.syllabus_curriculum, name="syllabus_curriculum"),

    # MODULES
    path("courses/<int:course_id>/modules/new/", views.module_create, name="module_create"),
    path("courses/<int:course_id>/modules/<int:module_id>/edit/", views.module_edit, name="module_edit"),
    path("courses/<int:course_id>/modules/<int:module_id>/delete/", views.module_delete, name="module_delete"),

    # LESSONS
    path("courses/<int:course_id>/modules/<int:module_id>/lessons/new/", views.lesson_create, name="lesson_create"),
    path("courses/<int:course_id>/modules/<int:module_id>/lessons/<int:lesson_id>/edit/", views.lesson_edit, name="lesson_edit"),
    path("courses/<int:course_id>/modules/<int:module_id>/lessons/<int:lesson_id>/delete/", views.lesson_delete, name="lesson_delete"),

    # INSTRUCTORS
    path("instructors/", views.instructor_list, name="instructor_list"),
    path("instructors/add/", views.instructor_add, name="instructor_add"),
    path("instructors/<int:membership_id>/toggle-active/", views.instructor_toggle_active, name="instructor_toggle_active"),

    # STUDENTS & ENROLLMENTS
    path("students/", views.student_list, name="student_list"),
    path("enrollments/", views.student_list, name="enrollment_list"),

    # BATCHES & ATTENDANCE
    path("batches/", views.batch_list, name="batch_list"),
    path("batches/new/", views.batch_create, name="batch_create"),
    path("attendance/", views.batch_attendance, name="batch_attendance"),

    # DOUBTS OVERVIEW (READ-ONLY)
    path("doubts/", views.doubt_overview, name="doubt_overview"),

    # SUBSCRIPTION & PROFILE
    path("subscription/", views.subscription_status, name="subscription_status"),
    path("profile/", views.profile, name="profile"),
]

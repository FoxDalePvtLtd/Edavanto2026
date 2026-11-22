from django.urls import path
from instructor_panel import views

app_name = "instructor_panel"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("courses/", views.course_list, name="course_list"),
    path("courses/<int:course_id>/lessons/", views.course_lessons, name="course_lessons"),
    path("doubts/", views.doubt_list, name="doubt_list"),
    path("doubts/<int:thread_id>/", views.doubt_detail, name="doubt_detail"),
    path("doubts/<int:thread_id>/resolve/", views.doubt_resolve, name="doubt_resolve"),
    path("assessments/", views.assessment_list, name="assessment_list"),
    path("assessments/<int:assessment_id>/submissions/", views.assessment_submissions, name="assessment_submissions"),
    path("assessments/submissions/<int:submission_id>/grade/", views.submission_grade, name="submission_grade"),
    path("batches/", views.batch_list, name="batch_list"),
    path("batches/<int:batch_id>/sessions/<int:session_id>/attendance/", views.session_attendance, name="session_attendance"),
    path("students/progress/", views.student_progress, name="student_progress"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/<int:notification_id>/read/", views.mark_notification_read, name="mark_notification_read"),
    path("profile/", views.profile, name="profile"),
]

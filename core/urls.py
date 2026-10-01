from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("courses/", views.courses, name="courses"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),

    path("login/", views.login_view, name="login"),
    path("sign-in/", views.sign_in, name="sign_in"),
    path("forgot-password/", views.forgot_password, name="forgot_password"),
    path("logout/", views.logout_view, name="logout"),

    path("course-details/<slug:slug>/", views.course_detail, name="course_detail"),
    path("course/<slug:slug>/payment/", views.payment, name="payment"),
    path("course/<slug:slug>/test-payment/", views.test_payment, name="test_payment"),
    path("course/<slug:slug>/offline-payment/", views.offline_payment_request, name="offline_payment_request"),

    path("dashboard/", views.dashboard, name="dashboard"),
    path("courses/<slug:slug>/", views.course_dashboard, name="course_dashboard"),

    path("register/", views.student_register, name="student_register"),
    path("verify-otp/", views.verify_otp_view, name="verify_otp"),

    path("dashboard/lesson/<int:lesson_id>/", views.lesson_view, name="lesson"),
    path("api/lesson/<int:lesson_id>/progress/", views.lesson_progress_api, name="lesson_progress_api"),
    path("api/lesson/<int:lesson_id>/complete/", views.lesson_complete_api, name="lesson_complete_api"),
]

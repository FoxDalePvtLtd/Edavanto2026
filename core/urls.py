from django.urls import path

from core.views_materials import (
    serve_lesson_material,
    material_note_api,
    serve_resource_file,
)
from core.views_video import stream_lesson_video

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
    path("reset-password/<uidb64>/<token>/", views.password_reset_confirm, name="password_reset_confirm"),
    path("logout/", views.logout_view, name="logout"),

    path("course-details/<slug:slug>/", views.course_detail, name="course_detail"),
    path("course/<slug:slug>/payment/", views.payment, name="payment"),
    path("course/<slug:slug>/payment/verify/", views.razorpay_verify, name="razorpay_verify"),
    path("payments/razorpay/webhook/", views.razorpay_webhook, name="razorpay_webhook"),
    path("course/<slug:slug>/test-payment/", views.test_payment, name="test_payment"),
    path("course/<slug:slug>/offline-payment/", views.offline_payment_request, name="offline_payment_request"),

    path("dashboard/", views.dashboard, name="dashboard"),
    path("courses/<slug:slug>/", views.course_dashboard, name="course_dashboard"),

    path("register/", views.student_register, name="student_register"),
    path("verify-otp/", views.verify_otp_view, name="verify_otp"),

    path("dashboard/lesson/<int:lesson_id>/", views.lesson_view, name="lesson"),
    path("api/lesson/<int:lesson_id>/progress/", views.lesson_progress_api, name="lesson_progress_api"),
    path("api/lesson/<int:lesson_id>/complete/", views.lesson_complete_api, name="lesson_complete_api"),
    path(
        "materials/<int:material_id>/view/", serve_lesson_material, name="serve_lesson_material",
    ),
    path(
        "materials/<int:material_id>/note/", material_note_api, name="material_note_api",
    ),
    path(
        "resources/<int:resource_id>/file/", serve_resource_file, name="serve_resource_file",
    ),
    path(
        "lesson/<int:lesson_id>/video/stream/", stream_lesson_video, name="stream_lesson_video",
    ),

    # CAREER CONSULTATION
    path("consultation/request/", views.career_consultation_request, name="career_consultation_request"),

    # DOUBT CLEARANCE
    path("dashboard/doubts/", views.student_doubts, name="student_doubts"),
    path("dashboard/lesson/<int:lesson_id>/doubt/create/", views.create_doubt, name="create_doubt"),
    path("dashboard/doubts/<int:thread_id>/", views.doubt_detail, name="doubt_detail"),
    path("dashboard/doubts/<int:thread_id>/reply/", views.doubt_reply, name="doubt_reply"),
    path("dashboard/doubts/<int:thread_id>/resolve/", views.doubt_resolve, name="doubt_resolve"),

    # ASSESSMENTS
    path("dashboard/assessments/", views.student_assessments, name="student_assessments"),
    path("dashboard/assessment/<int:assessment_id>/take/", views.take_assessment, name="take_assessment"),
    path("dashboard/assessment/submission/<int:submission_id>/result/", views.assessment_result, name="assessment_result"),

    # CENTER REGISTRATION & SUBSCRIPTION
    path("join-as-center/", views.join_as_center, name="join_as_center"),
    path("join-as-center/verify-otp/", views.center_verify_otp, name="center_verify_otp"),
    path("join-as-center/success/<int:application_id>/", views.center_registration_success, name="center_registration_success"),
    path("center-subscription/", views.center_subscription_select, name="center_subscription_select"),
    path("center-subscription/checkout/<int:plan_id>/", views.center_subscription_checkout, name="center_subscription_checkout"),
    path("center-subscription/verify/", views.center_subscription_verify, name="center_subscription_verify"),
    path("center-subscription/webhook/", views.center_subscription_webhook, name="center_subscription_webhook"),
]






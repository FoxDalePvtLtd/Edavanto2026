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
]
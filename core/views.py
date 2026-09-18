from django.shortcuts import render


def home(request):
    return render(request, "home.html")


def courses(request):
    return render(request, "courses.html")


def about(request):
    return render(request, "about.html")


def contact(request):
    return render(request, "contact.html")


def login_view(request):
    return render(request, "login.html")


def sign_in(request):
    return render(request, "sign-in.html")


def forgot_password(request):
    return render(request, "forgot-password.html")
from decimal import Decimal
from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from PIL import Image

from admin_panel.forms import AutoSlugFormMixin
from core.models import (
    Batch,
    Center,
    CenterInstructor,
    Course,
    Lesson,
    LessonMaterial,
    Module,
    Resource,
    User,
    VideoAsset,
)


class CenterCourseForm(AutoSlugFormMixin, forms.ModelForm):
    """
    Course creation and editing form strictly scoped to a Center.
    Reuses existing Course model fields.
    """
    class Meta:
        model = Course
        fields = [
            "title",
            "slug",
            "description",
            "category",
            "mode",
            "instructor",
            "price",
            "discounted_price",
            "duration_hours",
            "duration_weeks",
            "thumbnail",
            "requires_instructor_approval",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter course title"}),
            "slug": forms.TextInput(attrs={"class": "form-control", "placeholder": "course-slug"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 5, "placeholder": "Enter detailed course overview"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "mode": forms.Select(attrs={"class": "form-select"}),
            "instructor": forms.Select(attrs={"class": "form-select"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "discounted_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "duration_hours": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "duration_weeks": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "thumbnail": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "requires_instructor_approval": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, center=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.center = center

        # Scope instructor selection strictly to active instructors belonging to THIS center
        if self.center:
            instructor_ids = CenterInstructor.objects.filter(
                center=self.center,
                is_active=True,
            ).values_list("instructor_id", flat=True)
            self.fields["instructor"].queryset = User.objects.filter(
                id__in=instructor_ids,
                is_active=True,
            ).order_by("first_name", "last_name", "username")
        else:
            self.fields["instructor"].queryset = User.objects.none()

        self.fields["instructor"].required = False
        self.fields["thumbnail"].required = False

    def clean(self):
        cleaned_data = super().clean()
        mode = cleaned_data.get("mode")
        duration_hours = cleaned_data.get("duration_hours")
        duration_weeks = cleaned_data.get("duration_weeks")
        price = cleaned_data.get("price")
        discounted_price = cleaned_data.get("discounted_price")

        # Duration validation
        if mode == Course.Mode.ONLINE and not duration_hours:
            self.add_error("duration_hours", "Online courses require duration in hours.")
        elif mode == Course.Mode.OFFLINE and not duration_weeks:
            self.add_error("duration_weeks", "Offline courses require duration in weeks.")

        # Price validation
        if price is not None and discounted_price is not None:
            if discounted_price > price:
                self.add_error("discounted_price", "Discounted price cannot exceed normal price.")

        return cleaned_data

    def clean_thumbnail(self):
        thumbnail = self.cleaned_data.get("thumbnail")
        if thumbnail and hasattr(thumbnail, "file"):
            max_size_mb = 5
            if thumbnail.size > max_size_mb * 1024 * 1024:
                raise forms.ValidationError(f"Thumbnail image must be smaller than {max_size_mb}MB.")
            try:
                img = Image.open(thumbnail)
                img.verify()
            except Exception:
                raise forms.ValidationError("Uploaded file is not a valid image.")
        return thumbnail


class CenterModuleForm(forms.ModelForm):
    """
    Curriculum module form for center courses.
    """
    class Meta:
        model = Module
        fields = ["title", "description", "order", "duration_hours", "duration_weeks", "unlock_order"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Module 1: Introduction"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Module objectives"}),
            "order": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "duration_hours": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "duration_weeks": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "unlock_order": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        }


class CenterLessonForm(forms.ModelForm):
    """
    Lesson form for center curriculum.
    """
    class Meta:
        model = Lesson
        fields = ["title", "description", "order", "unlock_order", "duration_seconds"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Lesson title"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Lesson content"}),
            "order": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "unlock_order": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "duration_seconds": forms.NumberInput(attrs={"class": "form-control", "min": "0", "placeholder": "Estimated seconds"}),
        }


class CenterInstructorForm(forms.Form):
    """
    Form for registering or adding an instructor to the center.
    """
    first_name = forms.CharField(max_length=50, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "First Name"}))
    last_name = forms.CharField(max_length=50, required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Last Name"}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "instructor@example.com"}))
    phone = forms.CharField(max_length=20, required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "+91 9876543210"}))
    specialization = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Full Stack Python, UI/UX"}))
    password = forms.CharField(required=False, widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Initial password (optional)"}))
    profile_photo = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}))

    def clean_password(self):
        pwd = self.cleaned_data.get("password")
        if pwd:
            try:
                password_validation.validate_password(pwd)
            except ValidationError as exc:
                raise forms.ValidationError(exc.messages)
        return pwd


class CenterBatchForm(forms.ModelForm):
    """
    Batch creation/editing for a Center's courses.
    """
    class Meta:
        model = Batch
        fields = ["name", "course", "instructor", "start_date", "end_date", "capacity", "status"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Batch 2026-A"}),
            "course": forms.Select(attrs={"class": "form-select"}),
            "instructor": forms.Select(attrs={"class": "form-select"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "capacity": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, center=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.center = center
        if self.center:
            self.fields["course"].queryset = Course.objects.filter(center=self.center).order_by("title")
            instructor_ids = CenterInstructor.objects.filter(
                center=self.center,
                is_active=True,
            ).values_list("instructor_id", flat=True)
            self.fields["instructor"].queryset = User.objects.filter(
                id__in=instructor_ids,
                is_active=True,
            ).order_by("first_name", "last_name", "username")
        else:
            self.fields["course"].queryset = Course.objects.none()
            self.fields["instructor"].queryset = User.objects.none()

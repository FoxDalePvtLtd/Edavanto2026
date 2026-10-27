from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.core.exceptions import ValidationError
from core.models import *


class CourseAdminForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = [
            "title", "slug", "description", "category", "mode", "instructor",
            "price", "discounted_price", "duration_hours", "duration_weeks",
            "center", "thumbnail", "requires_instructor_approval",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter course title"}),
            "slug": forms.TextInput(attrs={"class": "form-control", "placeholder": "course-slug"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 6, "placeholder": "Enter course description"}),
            # "category": forms.TextInput(attrs={"class": "form-control", "placeholder": "Course category"}),
            "category": forms.Select(attrs={"class":"form-select"}),
            "mode": forms.Select(attrs={"class": "form-select"}),
            "instructor": forms.Select(attrs={"class": "form-select"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "discounted_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "duration_hours": forms.NumberInput(attrs={"class": "form-control", "min": "1", "step": "1"}),
            "duration_weeks": forms.NumberInput(attrs={"class": "form-control", "min": "1", "step": "1"}),
            "center": forms.Select(attrs={"class": "form-select"}),
            "thumbnail": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "requires_instructor_approval": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["instructor"].queryset = User.objects.filter(
            role=User.Role.INSTRUCTOR, is_active=True
        ).order_by("first_name", "last_name", "username")
        self.fields["center"].queryset = Center.objects.filter(is_active=True).order_by("name")
        self.fields["instructor"].required = False
        self.fields["center"].required = False
        self.fields["thumbnail"].required = False

    def clean_slug(self):
        slug = self.cleaned_data["slug"].strip().lower()
        if not slug:
            raise forms.ValidationError("Course slug is required.")
        return slug

    def clean(self):
        cleaned_data = super().clean()
        mode = cleaned_data.get("mode")
        price = cleaned_data.get("price")
        discounted_price = cleaned_data.get("discounted_price")
        center = cleaned_data.get("center")
        if discounted_price is not None and price is not None and discounted_price > price:
            self.add_error("discounted_price", "Discounted price cannot be greater than the course price.")
        if mode == Course.Mode.OFFLINE and center is None:
            self.add_error("center", "A center is required for an offline course.")
        duration_hours = cleaned_data.get("duration_hours")
        duration_weeks = cleaned_data.get("duration_weeks")
        if mode == Course.Mode.ONLINE and duration_hours is not None and duration_hours < 1:
            self.add_error("duration_hours", "Duration must be at least 1 hour.")
        if mode == Course.Mode.OFFLINE and duration_weeks is not None and duration_weeks < 1:
            self.add_error("duration_weeks", "Duration must be at least 1 week.")
        return cleaned_data


# Only these non-privileged roles may be assigned through this UI.
MANAGEABLE_ROLE_CHOICES = tuple(
    choice for choice in User.Role.choices if choice[0] != User.Role.ADMIN
)


class UserAdminFormBase(forms.ModelForm):
    """Shared user form: email is the login identifier; username stays internal."""

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={"class": "form-control", "autocomplete": "email"}
        ),
    )
    role = forms.ChoiceField(
        choices=MANAGEABLE_ROLE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = User
        fields = (
            "first_name", "last_name", "email", "phone",
            "role", "bio", "profile_photo",
        )
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control", "autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "autocomplete": "family-name"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "autocomplete": "tel"}),
            "bio": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "profile_photo": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if not email:
            raise ValidationError("Email address is required.")

        duplicate_email = User.objects.filter(email__iexact=email)
        username_conflict = User.objects.filter(username__iexact=email)
        if self.instance.pk:
            duplicate_email = duplicate_email.exclude(pk=self.instance.pk)
            username_conflict = username_conflict.exclude(pk=self.instance.pk)

        if duplicate_email.exists():
            raise ValidationError("A user with this email address already exists.")
        # With Django's default ModelBackend, the login form's email value is
        # looked up against username. Avoid taking another account's username.
        if username_conflict.exists():
            raise ValidationError(
                "This email conflicts with an existing account's login username. "
                "Resolve that account conflict before using this email."
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data["email"]
        user.email = email
        user.username = email
        if commit:
            user.save()
            self.save_m2m()
        return user


class ModuleAdminForm(forms.ModelForm):
    """
    Admin form for managing modules belonging to a selected course.

    The course itself is intentionally not exposed as an editable field.
    The parent course is controlled by the URL/view to prevent
    cross-course reassignment through POST data.
    """

    class Meta:
        model = Module
        fields = [
            "title",
            "description",
            "order",
            "duration_hours",
            "duration_weeks",
            "unlock_order",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter module title",
                    "maxlength": "200",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 5,
                    "placeholder": "Enter module description",
                }
            ),
            "order": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0",
                    "step": "1",
                }
            ),
            "duration_hours": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                    "step": "1",
                }
            ),
            "duration_weeks": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                    "step": "1",
                }
            ),
            "unlock_order": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0",
                    "step": "1",
                }
            ),
        }

    def __init__(self, *args, course=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.course = course

        self.fields["description"].required = False
        self.fields["duration_hours"].required = False
        self.fields["duration_weeks"].required = False

        if course and course.mode == Course.Mode.ONLINE:
            self.fields["duration_hours"].help_text = (
                "Estimated module duration in hours."
            )
            self.fields["duration_weeks"].help_text = (
                "Not used for online courses."
            )
        elif course and course.mode == Course.Mode.OFFLINE:
            self.fields["duration_hours"].help_text = (
                "Not used for offline courses."
            )
            self.fields["duration_weeks"].help_text = (
                "Planned module duration in weeks."
            )

    def clean(self):
        cleaned_data = super().clean()

        if not self.course:
            raise forms.ValidationError(
                "A valid parent course is required."
            )

        mode = self.course.mode

        duration_hours = cleaned_data.get("duration_hours")
        duration_weeks = cleaned_data.get("duration_weeks")

        if duration_hours is not None and duration_hours < 1:
            self.add_error(
                "duration_hours",
                "Duration must be at least 1 hour.",
            )

        if duration_weeks is not None and duration_weeks < 1:
            self.add_error(
                "duration_weeks",
                "Duration must be at least 1 week.",
            )

        # Keep the course's duration unit consistent.
        if mode == Course.Mode.ONLINE:
            cleaned_data["duration_weeks"] = None

        elif mode == Course.Mode.OFFLINE:
            cleaned_data["duration_hours"] = None

        return cleaned_data

class UserAdminCreateForm(UserAdminFormBase):
    password1 = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirm password", strip=False, widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}))

    class Meta(UserAdminFormBase.Meta):
        fields = UserAdminFormBase.Meta.fields

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")
        if password1:
            try:
                password_validation.validate_password(password1, self.instance)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        # Never accept privilege flags from submitted POST data.
        user.is_superuser = False
        user.is_staff = False
        user.is_active = True
        if commit:
            user.save()
            self.save_m2m()
        return user


class UserAdminUpdateForm(UserAdminFormBase):
    class Meta(UserAdminFormBase.Meta):
        fields = UserAdminFormBase.Meta.fields

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["profile_photo"].required = False


# ---------- Append to admin_panel/forms.py ----------

class LessonAdminForm(forms.ModelForm):
    """
    Admin form for lessons belonging to a selected module.

    The parent module (and therefore the parent course) is controlled by
    the URL/view and is never accepted from POST data.
    """

    class Meta:
        model = Lesson
        fields = [
            "title",
            "description",
            "order",
            "unlock_order",
            "duration_seconds",
            "status",
            "is_published",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter lesson title",
                    "maxlength": "200",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 5,
                    "placeholder": "Enter lesson description",
                }
            ),
            "order": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "step": "1"}
            ),
            "unlock_order": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "step": "1"}
            ),
            "duration_seconds": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "step": "1"}
            ),
            "status": forms.Select(attrs={"class": "form-select"}),
            "is_published": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
        }

    def __init__(self, *args, module=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.module = module

        self.fields["description"].required = False
        self.fields["duration_seconds"].required = False
        self.fields["unlock_order"].required = False

        if module is not None and module.course.mode == Course.Mode.ONLINE:
            self.fields["duration_seconds"].help_text = (
                "Video duration in seconds (online lessons)."
            )

    def clean(self):
        cleaned_data = super().clean()
        if self.module is None:
            raise forms.ValidationError("A valid parent module is required.")
        status = cleaned_data.get("status")
        is_published = cleaned_data.get("is_published")
        if status == Lesson.Status.PUBLISHED or is_published:
            cleaned_data["status"] = Lesson.Status.PUBLISHED
            cleaned_data["is_published"] = True
        elif status == Lesson.Status.DRAFT:
            cleaned_data["is_published"] = False
        return cleaned_data



ALLOWED_MATERIAL_EXTENSIONS = {
    ".pdf", ".ppt", ".pptx",
    ".doc", ".docx",
    ".xls", ".xlsx",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".txt", ".md", ".csv",
}
MAX_MATERIAL_SIZE = 50 * 1024 * 1024  # 50 MB


class LessonMaterialAdminForm(forms.ModelForm):
    class Meta:
        model = LessonMaterial
        fields = [
            "title",
            "material_type",
            "file",
            "original_filename",
            "content_type",
            "allow_printing",
            "watermark_text",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "material_type": forms.Select(attrs={"class": "form-select"}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "original_filename": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Leave blank to use the uploaded file name",
                }
            ),
            "content_type": forms.TextInput(attrs={"class": "form-control"}),
            "allow_printing": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "watermark_text": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # original_filename and content_type are optional; auto-derived.
        self.fields["original_filename"].required = False
        self.fields["content_type"].required = False

    def clean_file(self):
        f = self.cleaned_data.get("file")
        if not f:
            return f
        name = f.name.lower()
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        if ext not in ALLOWED_MATERIAL_EXTENSIONS:
            raise forms.ValidationError(f"Unsupported file type: {ext}")
        if f.size > MAX_MATERIAL_SIZE:
            raise forms.ValidationError(
                f"File too large ({f.size} bytes). Max is {MAX_MATERIAL_SIZE} bytes."
            )
        return f

    def clean(self):
        cleaned = super().clean()

        # If the admin left original_filename blank, derive it from the upload.
        uploaded = cleaned.get("file")
        if uploaded and not cleaned.get("original_filename"):
            cleaned["original_filename"] = uploaded.name

        # Same for content_type.
        if uploaded and not cleaned.get("content_type"):
            cleaned["content_type"] = (
                getattr(uploaded, "content_type", "")
                or "application/octet-stream"
            )

        return cleaned

    # -------------------------------------------------------------------
# Video asset form (one per lesson — create or replace)
# -------------------------------------------------------------------

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
MAX_VIDEO_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB


class VideoAssetAdminForm(forms.ModelForm):
    """
    Create or replace the single VideoAsset attached to a lesson.

    `duration_seconds` and `resolution` are NOT admin inputs — they are
    computed automatically by ffprobe when the file is uploaded.
    """

    class Meta:
        model = VideoAsset
        fields = [
            "original_file",
            "processing_status",
            "processing_error",
        ]
        widgets = {
            "original_file": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": "video/*"}
            ),
            "processing_status": forms.Select(attrs={"class": "form-select"}),
            "processing_error": forms.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["processing_error"].required = False
        # Lock the status dropdown to "Processing" once a file is submitted.
        # Admin can still set Ready/Failed manually after inspection.
        if self.instance and self.instance.pk:
            # Editing an existing video: keep whatever status is stored.
            pass

    def clean_original_file(self):
        f = self.cleaned_data.get("original_file")
        if not f:
            return f
        if hasattr(f, "size"):
            name = getattr(f, "name", "") or ""
            ext = "." + name.lower().rsplit(".", 1)[-1] if "." in name else ""
            if ext and ext not in ALLOWED_VIDEO_EXTENSIONS:
                raise forms.ValidationError(
                    f"Unsupported video type: {ext}. "
                    f"Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
                )
            if f.size > MAX_VIDEO_SIZE:
                raise forms.ValidationError(
                    f"Video too large ({f.size} bytes). Max is {MAX_VIDEO_SIZE} bytes."
                )
        return f


# -------------------------------------------------------------------
# Resource form (file OR external URL)
# -------------------------------------------------------------------

ALLOWED_RESOURCE_EXTENSIONS = {
    ".pdf", ".ppt", ".pptx", ".doc", ".docx",
    ".xls", ".xlsx", ".csv", ".txt", ".md", ".zip",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
}
MAX_RESOURCE_SIZE = 50 * 1024 * 1024  # 50 MB


class ResourceAdminForm(forms.ModelForm):
    """
    Create a Resource link. Accepts either a file upload OR an
    external URL. Exactly one is required.
    """

    class Meta:
        model = Resource
        fields = [
            "title",
            "resource_type",
            "file",
            "external_url",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "resource_type": forms.Select(attrs={"class": "form-select"}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "external_url": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://…"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].required = False
        self.fields["external_url"].required = False

    def clean_file(self):
        f = self.cleaned_data.get("file")
        if not f:
            return f
        if hasattr(f, "size"):
            name = getattr(f, "name", "") or ""
            ext = "." + name.lower().rsplit(".", 1)[-1] if "." in name else ""
            if ext and ext not in ALLOWED_RESOURCE_EXTENSIONS:
                raise forms.ValidationError(f"Unsupported file type: {ext}")
            if f.size > MAX_RESOURCE_SIZE:
                raise forms.ValidationError(
                    f"File too large ({f.size} bytes). Max is {MAX_RESOURCE_SIZE} bytes."
                )
        return f

    def clean_external_url(self):
        url = self.cleaned_data.get("external_url")
        if url:
            low = url.lower()
            if "/admin-panel" in low or "admin_panel" in low:
                raise forms.ValidationError(
                    "Resource reference links cannot point to internal admin panel management URLs."
                )
        return url

    def clean(self):
        cleaned = super().clean()
        file_obj = cleaned.get("file")
        url = (cleaned.get("external_url") or "").strip()

        # On edit, allow keeping the existing value untouched.
        if not self.instance.pk:
            if not file_obj and not url:
                raise forms.ValidationError(
                    "Provide either a file upload or an external URL."
                )
            if file_obj and url:
                raise forms.ValidationError(
                    "Provide only one of: file upload or external URL."
                )
        return cleaned
from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.core.exceptions import ValidationError
from core.models import Center, Course, User


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

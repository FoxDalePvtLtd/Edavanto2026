from django import forms

from core.models import *

class CourseAdminForm(forms.ModelForm):

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
            "center",
            "thumbnail",
            "status",
            "requires_instructor_approval",
        ]

        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter course title",
                }
            ),

            "slug": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "course-slug",
                }
            ),

            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 6,
                    "placeholder": "Enter course description",
                }
            ),

            "category": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Course category",
                }
            ),

            "mode": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "instructor": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "price": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                }
            ),

            "discounted_price": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                }
            ),

            "center": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "thumbnail": forms.ClearableFileInput(
                attrs={
                    "class": "form-control",
                    "accept": "image/*",
                }
            ),

            "status": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),

            "requires_instructor_approval": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Only active instructors should appear
        # in the instructor dropdown.
        self.fields["instructor"].queryset = (
            User.objects
            .filter(
                role=User.Role.INSTRUCTOR,
                is_active=True,
            )
            .order_by(
                "first_name",
                "last_name",
                "username",
            )
        )

        # Only active centers should appear.
        self.fields["center"].queryset = (
            Center.objects
            .filter(is_active=True)
            .order_by("name")
        )

        # These are optional at course creation.
        self.fields["instructor"].required = False
        self.fields["center"].required = False

        # Thumbnail is optional, especially during editing.
        self.fields["thumbnail"].required = False

    def clean_slug(self):
        slug = self.cleaned_data["slug"].strip().lower()

        if not slug:
            raise forms.ValidationError(
                "Course slug is required."
            )

        return slug

    def clean(self):
        cleaned_data = super().clean()

        mode = cleaned_data.get("mode")
        price = cleaned_data.get("price")
        discounted_price = cleaned_data.get("discounted_price")
        center = cleaned_data.get("center")

        # --------------------------------------------------
        # DISCOUNT PRICE VALIDATION
        # --------------------------------------------------

        if (
            discounted_price is not None
            and price is not None
            and discounted_price > price
        ):
            self.add_error(
                "discounted_price",
                "Discounted price cannot be greater than the course price.",
            )

        # --------------------------------------------------
        # OFFLINE COURSE VALIDATION
        # --------------------------------------------------

        if (
            mode == Course.Mode.OFFLINE
            and center is None
        ):
            self.add_error(
                "center",
                "A center is required for an offline course.",
            )

        return cleaned_data
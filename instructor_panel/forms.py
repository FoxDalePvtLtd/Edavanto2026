from django import forms
from core.models import Attendance, DoubtMessage, Submission, User


class InstructorProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "bio", "profile_photo"]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "bio": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "profile_photo": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }


class DoubtReplyForm(forms.ModelForm):
    class Meta:
        model = DoubtMessage
        fields = ["message", "attachment"]
        widgets = {
            "message": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Type your detailed explanation or answer here...",
                    "required": True,
                }
            ),
            "attachment": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }


class SubmissionGradeForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = ["score", "status"]
        widgets = {
            "score": forms.NumberInput(attrs={"class": "form-control", "step": "0.1", "min": "0"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, max_score=100, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_score = max_score
        self.fields["score"].help_text = f"Maximum score allowed: {max_score}"

    def clean_score(self):
        score = self.cleaned_data.get("score")
        if score is not None and score > self.max_score:
            raise forms.ValidationError(f"Score cannot exceed maximum total marks ({self.max_score}).")
        if score is not None and score < 0:
            raise forms.ValidationError("Score cannot be negative.")
        return score

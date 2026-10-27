from django import forms
from django.utils import timezone
from core.models import ConsultationBooking, DoubtThread, DoubtMessage


class CareerConsultationForm(forms.ModelForm):
    phone = forms.CharField(
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your phone number with country code",
            "id": "consultPhone"
        })
    )
    preferred_date = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={
            "class": "form-control",
            "type": "datetime-local",
            "id": "consultPreferredDate"
        })
    )
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 4,
            "placeholder": "Tell us about your learning goals, target roles, or specific questions...",
            "id": "consultMessage"
        })
    )

    class Meta:
        model = ConsultationBooking
        fields = ["phone", "preferred_date", "message"]

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "").strip()
        if len(phone) < 7:
            raise forms.ValidationError("Please provide a valid phone number (at least 7 digits).")
        return phone


class StudentDoubtThreadForm(forms.ModelForm):
    subject = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Summarize your doubt in one line (e.g. Question on Flexbox alignment)",
        })
    )
    message = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 4,
            "placeholder": "Explain your doubt in detail. Mention what you tried and what error occurred...",
        })
    )
    attachment = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            "class": "form-control",
            "accept": "image/*,.pdf,.zip,.py,.js,.html,.txt"
        })
    )

    class Meta:
        model = DoubtThread
        fields = ["subject"]


class DoubtMessageForm(forms.ModelForm):
    message = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 3,
            "placeholder": "Write your reply or clarification here...",
        })
    )
    attachment = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            "class": "form-control",
            "accept": "image/*,.pdf,.zip,.py,.js,.html,.txt"
        })
    )

    class Meta:
        model = DoubtMessage
        fields = ["message", "attachment"]

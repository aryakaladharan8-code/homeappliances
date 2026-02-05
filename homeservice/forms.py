from django import forms
from django.contrib.auth.models import User
from .models import Technician, SKILL_CHOICES


class LoginForm(forms.Form):
    username_or_email = forms.CharField(
        label="Username or Email",
        max_length=254,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Username or email"}),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Password"}),
    )


class TechnicianSignupForm(forms.ModelForm):
    # Extra fields not part of the Technician model but required for signup
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    custom_skill = forms.CharField(
        max_length=100, 
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Please specify your skill'})
    )

    class Meta:
        model = Technician
        fields = ['name', 'email', 'phone', 'skill', 'address', 'service_locations', 'experience_years', 'idproof', 'experience_certificate', 'photo']

        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'pattern': '\\d{10}', 'maxlength': '10', 'inputmode': 'numeric', 'placeholder': '10-digit phone number'}),
            'photo': forms.FileInput(attrs={'class': 'form-control'}),

            # SKILL DROPDOWN
            'skill': forms.Select(
                choices=SKILL_CHOICES,
                attrs={'class': 'form-control', 'id': 'id_skill'}
            ),

            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your home address'}),
            'service_locations': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Eg: Perumbavoor, Aluva, Muvattupuzha'}),
            'experience_years': forms.NumberInput(attrs={'class': 'form-control'}),
            'idproof': forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,application/pdf,image/*'}),
            'experience_certificate': forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,application/pdf,image/*'}),
        }

    def clean_experience_certificate(self):
        f = self.cleaned_data.get('experience_certificate')
        if f:
            # Validate content type (server-side) and size
            allowed = ['application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp']
            content_type = getattr(f, 'content_type', '')
            if content_type and content_type not in allowed:
                raise forms.ValidationError("Experience certificate must be a PDF or an image (jpg/png/gif/webp).")
            if f.size > 5 * 1024 * 1024:
                raise forms.ValidationError("Experience certificate must be under 5MB.")
        return f

    def clean_idproof(self):
        f = self.cleaned_data.get('idproof')
        if f:
            allowed = ['application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp']
            content_type = getattr(f, 'content_type', '')
            if content_type and content_type not in allowed:
                raise forms.ValidationError("ID proof must be a PDF or an image (jpg/png/gif/webp).")
            if f.size > 5 * 1024 * 1024:
                raise forms.ValidationError("ID proof must be under 5MB.")
        return f

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        skill = cleaned_data.get("skill")
        custom_skill = cleaned_data.get("custom_skill")

        if password != confirm_password:
            raise forms.ValidationError("Passwords do not match")
        
        # Handle custom skill
        if skill == "Others":
            if not custom_skill:
                raise forms.ValidationError("Please specify your skill when selecting 'Others'")
            # Store the custom skill in the skill field
            cleaned_data['skill'] = custom_skill

        return cleaned_data

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '') or ''
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if len(digits) != 10:
            raise forms.ValidationError("Enter a valid 10-digit phone number.")
        return digits

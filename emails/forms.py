from django import forms
from .models import PrioritySender, EmailPriority

class PrioritySenderForm(forms.ModelForm):
    class Meta:
        model = PrioritySender
        fields = ['display_name', 'email_address', 'priority', 'is_important', 'notification_enabled']
        widgets = {
            'display_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. HOD College or Company HR',
                'required': True
            }),
            'email_address': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. hod@college.edu',
                'required': True
            }),
            'priority': forms.Select(attrs={
                'class': 'form-select'
            }),
            'is_important': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'notification_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

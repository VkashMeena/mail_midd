from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from .models import UserProfile, validate_avatar_file

User = get_user_model()

class UserLoginForm(AuthenticationForm):
    """
    Login form accepting email or username as the identifier.
    Uses generic error message to prevent account enumeration.
    """
    username = forms.CharField(
        label="Email or Username",
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'name@company.com or username',
            'autocomplete': 'email',
            'id': 'loginIdentifier'
        })
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': '••••••••',
            'autocomplete': 'current-password',
            'id': 'loginPassword'
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'rememberMe'})
    )

    error_messages = {
        'invalid_login': "Invalid email or password.",
        'inactive': "This account is inactive.",
    }


class UserRegistrationForm(forms.ModelForm):
    """
    Registration form with email as unique identifier, full name, and password confirmation.
    Validates password strength via Django's configured password validators.
    """
    full_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'John Doe',
            'autocomplete': 'name',
            'id': 'fullName'
        })
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'name@company.com',
            'autocomplete': 'email',
            'id': 'regEmail'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': '••••••••',
            'autocomplete': 'new-password',
            'id': 'regPassword'
        })
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': '••••••••',
            'autocomplete': 'new-password',
            'id': 'regConfirmPassword'
        })
    )

    class Meta:
        model = User
        fields = ['email']

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password:
            if password != confirm_password:
                self.add_error('confirm_password', "Passwords do not match.")
            else:
                # Apply Django password validators
                temp_user = User(email=cleaned_data.get('email', ''))
                try:
                    password_validation.validate_password(password, temp_user)
                except forms.ValidationError as err:
                    self.add_error('password', err)

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data['email']
        user.email = email
        # Generate safe username from email prefix or fallback
        base_username = email.split('@')[0]
        username = base_username
        counter = 1
        while User.objects.filter(username__iexact=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1
        user.username = username

        user.set_password(self.cleaned_data['password'])
        full_name = self.cleaned_data.get('full_name', '').strip()
        if ' ' in full_name:
            user.first_name, user.last_name = full_name.split(' ', 1)
        else:
            user.first_name = full_name

        if commit:
            user.save()
            if hasattr(user, 'profile'):
                user.profile.display_name = full_name
                user.profile.save()
        return user


class UserProfileEditForm(forms.ModelForm):
    """
    Profile management form for updating display name, timezone, theme, and avatar.
    Email is read-only to preserve identity integrity.
    """
    display_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    timezone = forms.CharField(
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. UTC, Asia/Kolkata, America/New_York'})
    )
    theme = forms.ChoiceField(
        choices=UserProfile.THEME_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    avatar = forms.ImageField(
        required=False,
        validators=[validate_avatar_file],
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'})
    )

    class Meta:
        model = UserProfile
        fields = ['display_name', 'timezone', 'theme', 'avatar']


class CustomPasswordChangeForm(PasswordChangeForm):
    """
    Standard Django secure password change form with Bootstrap 5 input classes.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

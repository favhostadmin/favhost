from django import forms
from .models import Task
from property.models import Property
from accounts.utils import get_visible_user_ids

class TaskForm(forms.ModelForm):
    property = forms.ModelChoiceField(queryset=Property.objects.none(), empty_label="Select a listing", required=True, widget=forms.Select(attrs={'class': 'form-control property-select'}))

    class Meta:
        model = Task
        fields = [
            'property', 'title', 'details', 'date', 'time', 'repeat', 'repeat_till',
            'task_type', 'other_explanation', 'assigned_to', 'phone', 'country_code',
            'email',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'id': 'taskTitle',
                'placeholder': 'Enter task title',
                'maxlength': '100',
            }),
            'details': forms.Textarea(attrs={
                'placeholder': 'Briefly describe the task',
                'id': 'taskDetails',
                'rows': 3,
            }),
            'date': forms.DateInput(attrs={'type': 'date', 'id': 'taskDate'}),
            'time': forms.TimeInput(attrs={'type': 'hidden', 'id': 'task_time_input'}),
            'repeat': forms.Select(attrs={'id': 'repeatOption', 'class': 'custom-select', 'style': 'padding-right:2.5rem;'}),
            'repeat_till': forms.DateInput(attrs={'type': 'date', 'id': 'repeatTill'}),
            'task_type': forms.Select(attrs={'id': 'taskType', 'class': 'custom-select', 'style': 'padding-right:2.5rem;'}),
            'other_explanation': forms.TextInput(attrs={
                'id': 'otherExplanation',
                'placeholder': "Explain if type is 'Other'"
            }),
            'assigned_to': forms.TextInput(attrs={'id': 'assignedTo', 'placeholder': 'Enter name'}),
            'phone': forms.TextInput(attrs={'type': 'tel', 'id': 'phone', 'placeholder': 'Phone number'}),
            'country_code': forms.HiddenInput(attrs={'id': 'id_country_code'}),
            'email': forms.EmailInput(attrs={'id': 'taskEmail', 'placeholder': 'Enter email'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        is_instance = self.instance and self.instance.pk
        if is_instance and self.instance.repeat != 'None':
            # These fields are disabled in the template for editing, so they won't be in POST data.
            # We make them not required and disabled in the form to prevent validation errors.
            self.fields['property'].widget.attrs['disabled'] = True
            self.fields['property'].required = False
            self.fields['date'].widget.attrs['disabled'] = True
            self.fields['date'].required = False
            self.fields['repeat'].widget.attrs['disabled'] = True
            self.fields['repeat'].required = False
            self.fields['task_type'].widget.attrs['disabled'] = True
            self.fields['task_type'].required = False


        if user: # Filter properties by the logged-in user
            self.fields['property'].queryset = Property.objects.filter(created_by__in=get_visible_user_ids(user), status='Active')

        # Make fields not required by the model as optional in the form
        self.fields['title'].required = False
        self.fields['title'].max_length = 100
        self.fields['repeat_till'].required = False
        self.fields['other_explanation'].required = False
        self.fields['email'].required = False

        # Set a more user-friendly empty label for select fields
        # For ChoiceFields (not ModelChoiceField) ensure a visible empty option labeled 'Select'
        for fname in ('repeat', 'task_type'):
            field = self.fields.get(fname)
            if field and getattr(field, 'choices', None):
                choices = list(field.choices)
                if choices and choices[0][0] == '':
                    # replace the existing blank option label
                    choices[0] = ('', 'Select')
                else:
                    # ensure there's a blank top option labeled 'Select'
                    choices.insert(0, ('', 'Select'))
                field.choices = choices

    def save(self, commit=True):
        # When editing, disabled fields are not in the POST data.
        # We need to restore them from the original instance.
        if self.instance and self.instance.pk:
            # These are the fields disabled in the template.
            disabled_fields = ['property', 'date', 'repeat', 'repeat_till', 'task_type']
            for field_name in disabled_fields:
                if field_name not in self.cleaned_data:
                    # If the field is disabled, it won't be in the POST data.
                    # We restore its value from the original instance and add it
                    # to cleaned_data before the parent save() is called.
                    self.cleaned_data[field_name] = getattr(self.instance, field_name)
        
        return super().save(commit=commit)
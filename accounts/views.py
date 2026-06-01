from django.shortcuts import render
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import reverse_lazy
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required


class CustomLoginView(LoginView):
    template_name = 'frontend/auth/login.html'
    redirect_authenticated_user = True

    def form_valid(self, form):
        # Set session to expire based on the settings.
        # With SESSION_SAVE_EVERY_REQUEST=True, this creates an inactivity timeout.
        self.request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        return super().form_valid(form)

    def get_success_url(self):
        next_url = self.request.GET.get('next') or self.request.POST.get('next')
        if next_url:
            return next_url
        return reverse_lazy('dashboard')

    def form_invalid(self, form):
        """If the form is invalid, show the errors to the user via messages."""
        for error in form.non_field_errors():
            messages.error(self.request, error)
        return super().form_invalid(form)


@login_required
def profile_view(request):
    return render(request, 'frontend/auth/profile.html', {'user': request.user})
    

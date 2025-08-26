import logging
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import user_passes_test

from accounts.models import Parent, Student

logger = logging.getLogger(__name__)

def student_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Please login to access this page.')
            return redirect('login')
        try:
            student = Student.objects.get(user=request.user, is_active=True)
        except Student.DoesNotExist:
            messages.error(request, 'Access denied. Student account required.')
            return redirect('dashboard')
        except Student.MultipleObjectsReturned:
            messages.error(request, 'Configuration error: Multiple student accounts detected.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper

def teacher_required(view_func):
    """
    Decorator to ensure the user is a teacher (has a linked Teacher instance).
    Redirects to login if unauthenticated, or to dashboard with an error if not a teacher.
    """
    @login_required(login_url='login')
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        logger.debug(f"Checking teacher role for user: {request.user.username}")
        if hasattr(request.user, 'teacher'):
            return view_func(request, *args, **kwargs)
        logger.warning(f"User {request.user.username} is not a teacher")
        messages.error(request, "You must be a teacher to access this page.")
        return redirect('dashboard')
    return wrapper

def parent_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Please login to access this page.')
            return redirect('login')
        try:
            parent = Parent.objects.get(user=request.user)
            if not parent.is_active:
                messages.error(request, 'Parent account is inactive.')
                return redirect('login')
        except Parent.DoesNotExist:
            messages.error(request, 'Access denied. Parent account required.')
            return redirect('dashboard')
        except Parent.MultipleObjectsReturned:
            messages.error(request, 'Configuration error: Multiple parent accounts detected.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper

def admin_required(view_func):
    """
    Decorator to ensure the user is an admin (is_staff is True).
    Redirects to login if unauthenticated, or to dashboard with an error if not an admin.
    """
    @login_required(login_url='login')
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        logger.debug(f"Checking admin role for user: {request.user.username}")
        if request.user.is_staff:
            return view_func(request, *args, **kwargs)
        logger.warning(f"User {request.user.username} is not an admin")
        messages.error(request, "You must be an admin to access this page.")
        return redirect('dashboard')
    return wrapper

def group_required(*group_names):
    def check_group(user):
        if not user.is_authenticated:
            return False
        return user.groups.filter(name__in=group_names).exists()
    return user_passes_test(check_group, login_url='login')
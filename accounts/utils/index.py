from datetime import date
import logging

from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings

from accounts.models import Session, TermConfiguration

logger = logging.getLogger(__name__)

def get_current_session_term():
    """
    Determines the current session and term based on TermConfiguration settings.
    Falls back to default logic if no configuration is found.
    """
    current_date = timezone.now().date()
    current_year = current_date.year
    current_month = current_date.month
    current_day = current_date.day

    
    try:
        current_session = Session.objects.get(is_active=True)
    except ObjectDoesNotExist:
        
        session_year = current_year if current_month >= 9 else current_year - 1
        session_name = f"{session_year}/{session_year + 1}"
        current_session, _ = Session.objects.get_or_create(
            name=session_name,
            defaults={'start_year': session_year, 'end_year': session_year + 1, 'is_active': True}
        )

    
    term_configs = TermConfiguration.objects.filter(session=current_session).order_by('start_month')
    if not term_configs:
        
        term_configs = TermConfiguration.objects.filter(session__isnull=True).order_by('start_month')

    if term_configs:
        for config in term_configs:
            start_date = timezone.datetime(current_year, config.start_month, config.start_day).date()
            end_date = timezone.datetime(current_year, config.end_month, config.end_day).date()

            
            if config.start_month > config.end_month:
                if current_month <= config.end_month:
                    start_date = start_date.replace(year=current_year - 1)
                else:
                    end_date = end_date.replace(year=current_year + 1)

            if start_date <= current_date <= end_date:
                return current_session, config.term

        
        first_term = term_configs.first()
        return current_session, first_term.term if first_term else '1'

    
    session_year = current_year if current_month >= 9 else current_year - 1
    session_name = f"{session_year}/{session_year + 1}"
    term = '1' if 9 <= current_month <= 12 else '2' if 1 <= current_month <= 4 else '3'

    current_session, _ = Session.objects.get_or_create(
        name=session_name,
        defaults={'start_year': session_year, 'end_year': session_year + 1, 'is_active': True}
    )

    return current_session, term

def get_ordinal_suffix(n):
    """
    Returns the ordinal suffix for a given number (e.g., 1 -> 'st', 2 -> 'nd', 3 -> 'rd', 4 -> 'th').
    """
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return suffix

def get_next_term_start_date(current_session, current_term):
    """
    Returns the start date of the next term based on TermConfiguration.
    """
    current_year = timezone.now().year
    term_configs = TermConfiguration.objects.filter(session=current_session).order_by('start_month')
    if not term_configs:
        term_configs = TermConfiguration.objects.filter(session__isnull=True).order_by('start_month')

    if term_configs:
        term_list = list(term_configs)
        for i, config in enumerate(term_list):
            if config.term == current_term:
                next_term_index = (i + 1) % len(term_list)
                next_term_config = term_list[next_term_index]
                next_term_start = date(
                    current_year if next_term_config.start_month >= config.start_month else current_year + 1,
                    next_term_config.start_month,
                    next_term_config.start_day
                )
                return next_term_start

        first_term = term_configs.first()
        return date(current_year, first_term.start_month, first_term.start_day)

    if current_term == '1':
        return date(current_session.start_year + 1, 1, 1)
    elif current_term == '2':
        return date(current_year, 4, 1)
    elif current_term == '3':
        return date(current_session.start_year + 1, 9, 1)
    return "TBD"



def send_teacher_credentials_email(teacher, password):
    """
    Send login credentials to newly registered teacher
    """
    subject = f'Welcome to {getattr(settings, "SCHOOL_NAME", "School")} - Your Login Credentials'
    
    # Create email content
    context = {
        'teacher_name': teacher.full_name,
        'school_name': getattr(settings, 'SCHOOL_NAME', 'School'),
        'username': teacher.school_email,
        'password': password,
        'login_url': getattr(settings, 'LOGIN_URL', '/login/'),
        'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@school.com')
    }
    
    # HTML email template
    html_message = render_to_string('emails/teacher_credentials.html', context)
    
    # Plain text fallback
    plain_message = f"""
    Welcome to {context['school_name']}!

    Dear {teacher.full_name},

    Your teacher account has been successfully created. Here are your login credentials:

    Username: {teacher.school_email}
    Password: {password}

    Please log in at: {context['login_url']}

    IMPORTANT: Please change your password after your first login for security purposes.

    If you have any questions, please contact us at: {context['support_email']}

    Best regards,
    {context['school_name']} Administration Team
    """
    
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[teacher.school_email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"Credentials email sent successfully to {teacher.school_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send credentials email to {teacher.school_email}: {str(e)}")
        raise e


def send_password_reset_email(teacher, new_password):
    """
    Send new password when admin resets teacher password
    """
    subject = f'{getattr(settings, "SCHOOL_NAME", "School")} - Password Reset'
    
    context = {
        'teacher_name': teacher.full_name,
        'school_name': getattr(settings, 'SCHOOL_NAME', 'School'),
        'username': teacher.school_email,
        'new_password': new_password,
        'login_url': getattr(settings, 'LOGIN_URL', '/login/'),
        'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@school.com')
    }
    
    html_message = render_to_string('emails/teacher_password_reset.html', context)
    
    plain_message = f"""
    Password Reset - {context['school_name']}

    Dear {teacher.full_name},

    Your password has been reset by the administrator. Here are your new login credentials:

    Username: {teacher.school_email}
    New Password: {new_password}

    Please log in at: {context['login_url']}

    IMPORTANT: Please change your password after logging in for security purposes.

    If you did not request this password reset, please contact us immediately at: {context['support_email']}

    Best regards,
    {context['school_name']} Administration Team
    """
    
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[teacher.school_email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"Password reset email sent successfully to {teacher.school_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send password reset email to {teacher.school_email}: {str(e)}")
        raise e
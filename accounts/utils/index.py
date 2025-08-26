from datetime import date

from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist

from accounts.models import Session, TermConfiguration

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
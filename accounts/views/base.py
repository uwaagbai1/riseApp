import uuid
import logging
import re
import aiohttp
from weasyprint import HTML

from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.template import TemplateDoesNotExist, TemplateSyntaxError
from django.core.paginator import Paginator
from django.db import transaction
from django.template.loader import render_to_string
from django.http import HttpResponse, JsonResponse
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import Student, Teacher, Payment, Notification, Session, ClassSection
from accounts.utils.index import get_current_session_term

logger = logging.getLogger(__name__)

async def async_post_request(url, data):
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as response:
            return await response.json(), response.status
        
# def get_current_session_term():
#     current_year = timezone.now().year
#     current_month = timezone.now().month
#     session_year = current_year if current_month >= 9 else current_year - 1
#     session_name = f"{session_year}/{session_year + 1}"
#     term = '1' if 9 <= current_month <= 12 else '2' if 1 <= current_month <= 4 else '3'
    
#     session, _ = Session.objects.get_or_create(
#         name=session_name,
#         defaults={'start_year': session_year, 'end_year': session_year + 1, 'is_active': True}
#     )
    
#     return session, term

def get_user_context(request):
    if not request.user.is_authenticated:
        return None
    context = {'role': 'admin'}  
    try:
        if hasattr(request.user, 'student') and request.user.student:
            context.update({
                'role': 'student',
                'student': request.user.student,
            })
        elif hasattr(request.user, 'teacher') and request.user.teacher:
            context.update({
                'role': 'teacher',
                'teacher': request.user.teacher,
            })
        elif request.user.parent.exists():
            parent = request.user.parent.first()
            if parent:
                context.update({
                    'role': 'parent',
                    'parent': parent,
                })
            else:
                logger.warning(f"No active Parent found for user {request.user.username}")
        else:
            logger.debug(f"User {request.user.username} is admin")
    except Exception as e:
        logger.error(f"Error in get_user_context for {request.user.username}: {str(e)}")
    return context

def get_teacher_students(teacher):
    current_session, _ = get_current_session_term()
    teacher_sections = ClassSection.objects.filter(
        teachers=teacher,
        session=current_session
    )
    return Student.objects.filter(
        current_section__in=teacher_sections,
        is_active=True
    ).select_related('current_class', 'current_section')

def get_class_sections(request):
    class_id = request.GET.get('class_id')
    if not class_id:
        return JsonResponse({'sections': []})
    
    sections = ClassSection.objects.filter(
        school_class_id=class_id,
        session__is_active=True
    ).values('id', 'suffix')
    
    return JsonResponse({
        'sections': list(sections)
    })

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        login_type = request.POST.get('login_type')
        
        if login_type == 'parent':
            phone_number = request.POST.get('phone_number', '').strip()
            password = request.POST.get('password', '').strip()
            
            user = authenticate(request, phone_number=phone_number, password=password)
            if user and hasattr(user, 'parent'):
                login(request, user)
                logger.info(f"Parent logged in: {phone_number}")
                return redirect('dashboard')
            messages.error(request, 'Invalid phone number or password.')
            return render(request, 'account/login.html', {'login_type': 'parent'})
        else:
            username = request.POST.get('username', '').strip().lower()
            password = request.POST.get('password', '').strip()
            
            user = authenticate(request, username=username, password=password)
            if user:
                if (hasattr(user, 'student') and not user.student.is_active) or \
                   (hasattr(user, 'teacher') and not user.teacher.is_active):
                    messages.error(request, 'Your account is deactivated. Please contact the administrator.')
                    logger.warning(f"Deactivated user {username} attempted login")
                    return render(request, 'account/login.html')
                
                login(request, user)
                logger.info(f"User {username} logged in successfully")
                return redirect('dashboard')
            
            messages.error(request, 'Invalid admission number/token or username/password')
            logger.warning(f"Failed login attempt for {username}")
            return render(request, 'account/login.html')
    
    return render(request, 'account/login.html')

@login_required
def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('login')

def test_session_term(request):
    session, term = get_current_session_term()
    return HttpResponse(f"Session: {session.name}, Term: {term}")

def dashboard(request):
    context = get_user_context(request)
    if not context:
        return redirect('login')

    role = context.get('role')
    if role == 'student':
        student = context.get('student')
        if student:
            context.update({
                'student': student,
            })
        else:
            logger.warning(f"No student instance for user {request.user.username}")
    elif role == 'teacher':
        teacher = context.get('teacher')
        if teacher:
            context.update({
                'teacher': teacher,
            })
        else:
            logger.warning(f"No teacher instance for user {request.user.username}")
    elif role == 'parent':
        parent = context.get('parent')
        if parent:
            try:
                children = parent.students.all().select_related('current_class', 'current_section').filter(is_active=True)
                children_count = children.count()
                payments = parent.payments.all().order_by('-created_at')
                for child in children:
                    if not child.admission_number:
                        logger.warning(f"Invalid student with empty admission_number for parent {parent.phone_number}")
                context.update({
                    'parent': parent,
                    'children': children,
                    'children_count': children_count,
                    'payments': payments,
                })
            except Exception as e:
                logger.error(f"Error accessing parent.students for {parent.phone_number}: {str(e)}")
                context.update({
                    'parent': parent,
                    'children': [],
                    'children_count': 0,
                    'payments': [],
                })
        else:
            logger.warning(f"No parent instance for user {request.user.username}")
            context.update({
                'parent': None,
                'children': [],
                'children_count': 0,
                'payments': [],
            })
    else:  
        context.update({
            'students_count': Student.objects.count(),
            'teachers_count': Teacher.objects.count(),
        })

    return render(request, 'account/dashboard.html', context)

@login_required
def student_detail(request, admission_number):
    try:
        student = Student.objects.get(admission_number=admission_number)
    except Student.DoesNotExist:
        messages.error(request, 'Student not found')
        logger.error(f"Student with admission_number {admission_number} not found")
        context = get_user_context(request)
        if context and context['role'] == 'admin':
            return redirect('admin_student_management')
        elif context and context['role'] == 'teacher':
            return redirect('teacher_view_students')
        else:
            return redirect('dashboard')

    context = get_user_context(request)
    if not context:
        logger.error(f"Invalid user context for user {request.user.username}")
        return redirect('login')

    
    if context['role'] == 'student' and request.user != student.user:
        messages.error(request, 'You are not authorized to view this student’s details.')
        return redirect('dashboard')
    elif context['role'] == 'teacher' and (not student.current_section or request.user.teacher not in student.current_section.teachers.all()):
        messages.error(request, 'You are not authorized to view this student’s details.')
        return redirect('teacher_view_students')

    
    payments = Payment.objects.all()
    paginator = Paginator(payments, 10)
    page_number = request.GET.get('payment_page', 1)
    payment_page_obj = paginator.get_page(page_number)

    can_update_results = (
        context['role'] == 'teacher' and
        student.current_section and
        request.user.teacher in student.current_section.teachers.all()
    )

    context.update({
        'student': student,
        'payments': payment_page_obj.object_list,
        'payment_page_obj': payment_page_obj,
        'sessions': Session.objects.all(),
        'can_update_results': can_update_results,
        'class_sections': ClassSection.objects.filter(session__is_active=True) if context['role'] == 'admin' else [],
    })
    return render(request, 'account/student_detail.html', context)

@login_required
def profile(request):
    context = get_user_context(request)
    if not context:
        logger.error(f"Invalid user context for user {request.user.username}")
        return redirect('login')

    current_session, _ = get_current_session_term()
    
    context.update({
        'session': current_session.name,
        'notifications': Notification.objects.filter(user=request.user, read=False),
    })

    if request.method == 'POST':
        try:
            with transaction.atomic():
                if context['role'] == 'student':
                    student = context['student']
                    student.full_name = request.POST.get('full_name', student.full_name)
                    student.address = request.POST.get('address', student.address)
                    student.parent_phone = request.POST.get('parent_phone', student.parent_phone)
                    if request.FILES.get('photo'):
                        student.photo = request.FILES.get('photo')
                    
                    if not student.full_name:
                        raise ValidationError('Full name is required.')
                    if not student.address:
                        raise ValidationError('Address is required.')
                    if not student.parent_phone or not re.match(r'^\+?\d{10,15}$', student.parent_phone):
                        raise ValidationError('Invalid phone number format.')
                    if student.parent and student.parent_phone != student.parent.phone_number:
                        raise ValidationError('Parent phone must match the linked parent’s phone number.')
                    
                    student.save()
                    student.user.first_name = student.full_name.split()[0]
                    student.user.last_name = ' '.join(student.full_name.split()[1:]) if len(student.full_name.split()) > 1 else ''
                    student.user.save()
                    messages.success(request, 'Student profile updated successfully.')
                    logger.info(f"Student {request.user.username} updated profile")
                
                elif context['role'] == 'teacher':
                    teacher = context['teacher']
                    teacher.full_name = request.POST.get('full_name', teacher.full_name)
                    teacher.school_email = request.POST.get('school_email', teacher.school_email)
                    if request.FILES.get('photo'):
                        teacher.photo = request.FILES.get('photo')
                    
                    if not teacher.full_name:
                        raise ValidationError('Full name is required.')
                    if not teacher.school_email or not re.match(r'^[^@]+@[^@]+\.[^@]+$', teacher.school_email):
                        raise ValidationError('Invalid email format.')
                    if Teacher.objects.filter(school_email=teacher.school_email).exclude(id=teacher.id).exists():
                        raise ValidationError('This email is already in use by another teacher.')
                    
                    teacher.save()
                    teacher.user.first_name = teacher.full_name.split()[0]
                    teacher.user.last_name = ' '.join(teacher.full_name.split()[1:]) if len(teacher.full_name.split()) > 1 else ''
                    teacher.user.email = teacher.school_email
                    teacher.user.save()
                    messages.success(request, 'Teacher profile updated successfully.')
                    logger.info(f"Teacher {request.user.username} updated profile")
                
                elif context['role'] == 'parent':
                    parent = context['parent']
                    parent.full_name = request.POST.get('full_name', parent.full_name)
                    parent.phone_number = request.POST.get('phone_number', parent.phone_number)
                    if request.FILES.get('photo'):
                        parent.photo = request.FILES.get('photo')
                    
                    if not parent.full_name:
                        raise ValidationError('Full name is required.')
                    if not parent.phone_number or not re.match(r'^\+?\d{10,15}$', parent.phone_number):
                        raise ValidationError('Invalid phone number format.')
                    if User.objects.filter(username=parent.phone_number).exclude(id=parent.user.id).exists():
                        raise ValidationError('This phone number is already in use.')
                    
                    parent.save()
                    parent.user.first_name = parent.full_name.split()[0]
                    parent.user.last_name = ' '.join(parent.full_name.split()[1:]) if len(parent.full_name.split()) > 1 else ''
                    parent.user.username = parent.phone_number
                    parent.user.save()
                    messages.success(request, 'Parent profile updated successfully.')
                    logger.info(f"Parent {request.user.username} updated profile")
                
                elif context['role'] == 'admin':
                    request.user.first_name = request.POST.get('first_name', request.user.first_name)
                    request.user.last_name = request.POST.get('last_name', request.user.last_name)
                    
                    if not request.user.first_name:
                        raise ValidationError('First name is required.')
                    
                    request.user.save()
                    messages.success(request, 'Admin profile updated successfully.')
                    logger.info(f"Admin {request.user.username} updated profile")
                
                if context['role'] in ['teacher', 'parent'] and request.POST.get('change_password'):
                    current_password = request.POST.get('current_password')
                    new_password = request.POST.get('new_password')
                    confirm_password = request.POST.get('confirm_password')
                    
                    if not current_password or not new_password or not confirm_password:
                        raise ValidationError('All password fields are required.')
                    if new_password != confirm_password:
                        raise ValidationError('New passwords do not match.')
                    if len(new_password) < 8:
                        raise ValidationError('New password must be at least 8 characters long.')
                    
                    user = authenticate(username=request.user.username, password=current_password)
                    if not user:
                        raise ValidationError('Current password is incorrect.')
                    
                    request.user.set_password(new_password)
                    request.user.save()
                    messages.success(request, 'Password changed successfully. Please log in again.')
                    logger.info(f"{context['role'].capitalize()} {request.user.username} changed password")
                    return redirect('logout')
        
        except ValidationError as e:
            messages.error(request, f'Error: {str(e)}')
            logger.error(f"Validation error updating profile for user {request.user.username}: {str(e)}")
        except Exception as e:
            messages.error(request, 'An unexpected error occurred.')
            logger.error(f"Unexpected error updating profile for user {request.user.username}: {str(e)}")

    if context['role'] == 'student':
        context['student'] = context['student']
    elif context['role'] == 'teacher':
        context['teacher'] = context['teacher']
        context['assigned_sections'] = ClassSection.objects.filter(
            teachers=context['teacher'],
            session=current_session
        ).select_related('school_class')
    elif context['role'] == 'parent':
        context['parent'] = context['parent']
        context['children_count'] = context['parent'].students.filter(is_active=True).count()
    elif context['role'] == 'admin':
        context['admin_user'] = request.user

    return render(request, 'account/profile.html', context)

@login_required
def generate_payment_receipt(request, payment_id):
    logger.info('Generating receipt for payment_id=%s, user=%s (is_staff=%s)', 
                payment_id, request.user.username, request.user.is_staff)
    payment = get_object_or_404(Payment, id=payment_id)

    if not payment.transaction_id:
        logger.warning('Payment %s has no transaction_id, generating new one', payment_id)
        payment.transaction_id = str(uuid.uuid4())
        payment.save()

    user_parent = request.user.parent.first()
    has_parent = user_parent is not None
    is_parent_match = has_parent and user_parent == payment.parent
    has_access = request.user.is_staff or is_parent_match
    if not has_access:
        logger.warning('Unauthorized access attempt: user=%s, payment_id=%s, user_parent_id=%s, payment_parent_id=%s, has_parent=%s, is_parent_match=%s',
                       request.user.username, payment_id, 
                       user_parent.id if has_parent else None, 
                       payment.parent.id, has_parent, is_parent_match)
        return HttpResponse("Unauthorized", status=403)

    try:
        context = {
            'payment': payment,
            'school_name': "Rehoboth International School of Excellence",
            'school_address': "798 Rues Des Cormiers Qt Hedzranawoe, Lome Togo",
            'school_contact': "+22890165089, +22890016077, +22897412298",
        }

        html_string = render_to_string('account/payment_receipt.html', context)
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="receipt_{payment.transaction_id}.pdf"'
        HTML(string=html_string).write_pdf(response)
        logger.info('Receipt generated successfully: payment_id=%s, transaction_id=%s', 
                    payment_id, payment.transaction_id)
        return response

    except TemplateSyntaxError as e:
        logger.exception('Template syntax error in receipt generation: payment_id=%s, error=%s', payment_id, str(e))
        return HttpResponse(f"Template error: {str(e)} (Check custom filters like 'subtract')", status=500)
    except Exception as e:
        logger.exception('Error generating receipt: payment_id=%s, error=%s', payment_id, str(e))
        return HttpResponse(f"Error generating receipt: {str(e)}", status=500)


def handler400(request, exception):
    logger.error(f"Bad request: {exception}")
    try:
        return render(request, 'account/errors/400.html', status=400)
    except TemplateDoesNotExist:
        logger.error("Template 'account/errors/400.html' not found")
        return HttpResponse("Bad Request", status=400)

def handler403(request, exception):
    logger.error(f"Permission denied: {exception}")
    try:
        return render(request, 'account/errors/403.html', status=403)
    except TemplateDoesNotExist:
        logger.error("Template 'account/errors/403.html' not found")
        return HttpResponse("Forbidden", status=403)

def handler404(request, exception):
    logger.error(f"Page not found: {exception}")
    try:
        return render(request, 'account/errors/404.html', status=404)
    except TemplateDoesNotExist:
        logger.error("Template 'account/errors/404.html' not found")
        return HttpResponse("Not Found", status=404)

def handler500(request):
    logger.error("Server error occurred", exc_info=True)
    try:
        return render(request, 'account/errors/500.html', status=500)
    except TemplateDoesNotExist:
        logger.error("Template 'account/errors/500.html' not found")
        return HttpResponse("Internal Server Error", status=500)
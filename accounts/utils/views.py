from datetime import datetime
from itertools import groupby
from urllib.parse import urlencode
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth import update_session_auth_hash
from django.template import TemplateSyntaxError
from django.utils.crypto import get_random_string
from django.db.models import Prefetch
from weasyprint import HTML
from django.template.loader import render_to_string
from accounts.utils.index import get_next_term_start_date, get_ordinal_suffix
from accounts.decorators import student_required, teacher_required, parent_required, admin_required
from accounts.models import FeeStructure, ResultAccessRequest, Student, Teacher, Result, Payment, SchoolClass, Subject, Notification, Session, ClassSection, TERM_CHOICES, StudentSubject, Parent
from django.conf import settings
import uuid
from django.http import Http404, HttpResponse, JsonResponse
import logging
from django.core.exceptions import ValidationError
import re
from django.utils import timezone
from django.db.models import Avg, Sum, Q, Count
import aiohttp
import asyncio
from django.core.paginator import Paginator
from django.urls import reverse, NoReverseMatch
from decimal import Decimal, InvalidOperation
from django.db import IntegrityError, transaction
from django.core import management
from django.views.decorators.csrf import csrf_exempt
from accounts.utils.pdf_generator import generate_result_pdf


logger = logging.getLogger(__name__)

async def async_post_request(url, data):
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as response:
            return await response.json(), response.status
        
def get_current_session_term():
    current_year = timezone.now().year
    current_month = timezone.now().month
    session_year = current_year if current_month >= 9 else current_year - 1
    session_name = f"{session_year}/{session_year + 1}"
    term = '1' if 9 <= current_month <= 12 else '2' if 1 <= current_month <= 4 else '3'
    
    session, _ = Session.objects.get_or_create(
        name=session_name,
        defaults={'start_year': session_year, 'end_year': session_year + 1, 'is_active': True}
    )
    
    return session, term

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
            phone_number = request.POST.get('phone_number')
            password = request.POST.get('password')
            user = authenticate(request, phone_number=phone_number, password=password)
            if user and hasattr(user, 'parent'):
                login(request, user)
                logger.info(f"Parent logged in: {phone_number}")
                return redirect('dashboard')
            messages.error(request, 'Invalid phone number or password.')
            return render(request, 'account/login.html', {'login_type': 'parent'})
        else:
            username = request.POST.get('username')
            password = request.POST.get('password')
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
@admin_required
def admin_student_management(request):
    context = get_user_context(request)
    if not context:
        return redirect('login')

    current_session, _ = get_current_session_term()
    students = Student.objects.all().select_related('current_class', 'current_section')
    class_sections = ClassSection.objects.filter(session=current_session).select_related('school_class').order_by('school_class__level')
    form_data = {}
    form_errors = []

    if request.method == 'POST':
        try:
            with transaction.atomic():
                first_name = request.POST.get('first_name')
                middle_name = request.POST.get('middle_name')
                surname = request.POST.get('surname')
                date_of_birth = request.POST.get('date_of_birth')
                nationality = request.POST.get('nationality')
                address = request.POST.get('address')
                parent_phone = request.POST.get('parent_phone')
                gender = request.POST.get('gender')
                enrollment_year = request.POST.get('enrollment_year')
                class_id = request.POST.get('class')
                section_id = request.POST.get('section')
                photo = request.FILES.get('photo')

                form_data = {
                    'first_name': first_name,
                    'middle_name': middle_name,
                    'surname': surname,
                    'date_of_birth': date_of_birth,
                    'nationality': nationality,
                    'address': address,
                    'parent_phone': parent_phone,
                    'gender': gender,
                    'enrollment_year': enrollment_year,
                    'class': class_id,
                    'section': section_id,
                }

                if not first_name:
                    form_errors.append('First name is required.')
                if not surname:
                    form_errors.append('Surname is required.')
                if not date_of_birth:
                    form_errors.append('Date of birth is required.')
                if not nationality:
                    form_errors.append('Nationality is required.')
                if not address:
                    form_errors.append('Address is required.')
                if not parent_phone:
                    form_errors.append('Parent phone is required.')
                if not gender:
                    form_errors.append('Gender is required.')
                if not enrollment_year:
                    form_errors.append('Enrollment year is required.')
                if not class_id:
                    form_errors.append('Class is required.')

                if form_errors:
                    raise ValidationError('Missing required fields')

                if not re.match(r'^\d{4}$', enrollment_year):
                    form_errors.append('Enrollment year must be a four-digit number.')
                    raise ValidationError('Invalid enrollment year format')
                current_year = timezone.now().year
                if int(enrollment_year) > current_year:
                    form_errors.append('Enrollment year cannot be in the future.')
                    raise ValidationError('Future enrollment year')
                if int(enrollment_year) < 1900:
                    form_errors.append('Enrollment year is too far in the past.')
                    raise ValidationError('Invalid enrollment year')

                if not re.match(r'^\+?\d{10,15}$', parent_phone):
                    form_errors.append('Invalid phone number format.')
                    raise ValidationError('Invalid phone number format')
                if gender not in ['M', 'F']:
                    form_errors.append('Invalid gender.')
                    raise ValidationError('Invalid gender')

                school_class = SchoolClass.objects.get(id=class_id)
                class_section = ClassSection.objects.get(id=section_id) if section_id else None

                student = Student(
                    first_name=first_name,
                    middle_name=middle_name,
                    surname=surname,
                    date_of_birth=date_of_birth,
                    nationality=nationality,
                    address=address,
                    parent_phone=parent_phone,
                    gender=gender,
                    enrollment_year=enrollment_year,
                    current_class=school_class,
                    current_section=class_section,
                    photo=photo,
                    is_active=True
                )

                
                parent, created = Parent.objects.get_or_create(
                    phone_number=parent_phone,
                    defaults={
                        'full_name': f"Parent of {first_name} {surname}",
                        'user': User.objects.create_user(
                            username=parent_phone,
                            password=parent_phone,
                            is_active=True
                        ) if not User.objects.filter(username=parent_phone).exists() else User.objects.get(username=parent_phone),
                    }
                )
                student.parent = parent
                student.save()

                if created:
                    Notification.objects.create(
                        user=parent.user,
                        message=f"Parent account created for {parent_phone}. Use phone number as password to login."
                    )
                    logger.info(f"Created parent account for {parent_phone} linked to student {student.full_name}")

                messages.success(
                    request,
                    f'Student {student.full_name} registered with admission number {student.admission_number}. '
                    f'Use admission number as username and token as password to login.'
                )
                Notification.objects.create(
                    user=request.user,
                    message=f"Student {student.full_name} registered with admission number {student.admission_number}."
                )
                logger.info(f"Admin {request.user.username} registered student {student.full_name}")
                return redirect('admin_student_management')

        except IntegrityError as e:
            form_errors.append(
                'Failed to register student due to a duplicate admission number or username. '
                'Try a different enrollment year or contact support.'
            )
            messages.error(request, f'Error: {", ".join(form_errors)}')
            logger.error(f"IntegrityError registering student for parent {parent_phone}: {str(e)}")
        except (SchoolClass.DoesNotExist, ClassSection.DoesNotExist) as e:
            form_errors.append(str(e))
            messages.error(request, f'Error: {", ".join(form_errors)}')
            logger.error(f"Error registering student: {str(e)}")
        except ValidationError as e:
            form_errors.append(str(e))
            messages.error(request, f'Error: {", ".join(form_errors)}')
            logger.error(f"ValidationError registering student for parent {parent_phone}: {str(e)}")
        except Exception as e:
            form_errors.append('An unexpected error occurred. Please contact support.')
            messages.error(request, f'Error: {", ".join(form_errors)}')
            logger.error(f"Unexpected error registering student for parent {parent_phone}: {str(e)}")

    paginator = Paginator(students, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context.update({
        'page_obj': page_obj,
        'students': page_obj.object_list,
        'students_count': students.count(),
        'classes': SchoolClass.objects.all(),
        'class_sections': class_sections,
        'genders': Student._meta.get_field('gender').choices,
        'form_data': form_data,
        'form_errors': form_errors,
    })
    return render(request, 'account/admin/admin_student_management.html', context)

@login_required
@admin_required
def filter_students(request):
    try:
        class_id = request.GET.get('class_id')
        name = request.GET.get('name')
        gender = request.GET.get('gender')
        enrollment_year = request.GET.get('enrollment_year')
        page_number = request.GET.get('page', 1)
        students = Student.objects.select_related('current_class', 'current_section')

        if class_id:
            try:
                students = students.filter(current_class__id=class_id)
            except ValueError:
                logger.error(f"Invalid class_id: {class_id}")
                return JsonResponse({'students': [], 'error': 'Invalid class ID'}, status=400)
        if name:
            students = students.filter(
                Q(first_name__icontains=name) |
                Q(middle_name__icontains=name) |
                Q(surname__icontains=name)
            )
        if gender:
            students = students.filter(gender=gender)
        if enrollment_year:
            students = students.filter(enrollment_year=enrollment_year)

        paginator = Paginator(students, 25)
        page_obj = paginator.get_page(page_number)
        data = {
            'students': [
                {
                    'admission_number': s.admission_number,
                    'first_name': s.first_name,
                    'middle_name': s.middle_name or '',
                    'surname': s.surname,
                    'nationality': s.nationality,
                    'current_class': str(s.current_class) if s.current_class else 'N/A',
                    'current_section': str(s.current_section) if s.current_section else 'N/A',
                    'gender_display': s.get_gender_display(),
                    'parent_phone': s.parent_phone,
                    'enrollment_year': s.enrollment_year,
                    'is_active': s.is_active
                } for s in page_obj.object_list
            ],
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'page': page_obj.number,
            'total_pages': paginator.num_pages
        }
        return JsonResponse(data)
    except Exception as e:
        logger.error(f"Error in filter_students: {str(e)}")
        return JsonResponse({'students': [], 'error': str(e)}, status=500)

@login_required
@admin_required
def admin_teacher_management(request):
    context = get_user_context(request)
    if not context:
        return redirect('login')

    current_session, _ = get_current_session_term()
    name = request.GET.get('name')
    email = request.GET.get('email')
    gender = request.GET.get('gender')
    is_active = request.GET.get('is_active')
    
    teachers = Teacher.objects.all().select_related('user')
    
    if name:
        teachers = teachers.filter(
            Q(first_name__icontains=name) |
            Q(middle_name__icontains=name) |
            Q(surname__icontains=name)
        )
    if email:
        teachers = teachers.filter(school_email__icontains=email)
    if gender:
        teachers = teachers.filter(gender=gender)
    if is_active in ['true', 'false']:
        teachers = teachers.filter(is_active=(is_active == 'true'))
    
    teachers = teachers.prefetch_related(
        Prefetch(
            'assigned_sections',
            queryset=ClassSection.objects.filter(session=current_session).select_related('school_class'),
            to_attr='current_sections'
        )
    )

    form_data = {}
    form_errors = []

    if request.method == 'POST':
        try:
            first_name = request.POST.get('first_name')
            middle_name = request.POST.get('middle_name')
            surname = request.POST.get('surname')
            school_email = request.POST.get('school_email')
            gender = request.POST.get('gender')
            nationality = request.POST.get('nationality')
            photo = request.FILES.get('photo')

            form_data = {
                'first_name': first_name,
                'middle_name': middle_name,
                'surname': surname,
                'school_email': school_email,
                'gender': gender,
                'nationality': nationality,
            }

            if not first_name:
                form_errors.append('First name is required.')
            if not surname:
                form_errors.append('Surname is required.')
            if not school_email:
                form_errors.append('School email is required.')
            if not gender:
                form_errors.append('Gender is required.')
            if not nationality:
                form_errors.append('Nationality is required.')

            if form_errors:
                raise ValidationError('Missing required fields')

            if not re.match(r'^[^@]+@[^@]+\.[^@]+$', school_email):
                form_errors.append('Invalid email format.')
                raise ValidationError('Invalid email format')

            if gender not in ['M', 'F']:
                form_errors.append('Invalid gender.')
                raise ValidationError('Invalid gender')

            if Teacher.objects.filter(school_email=school_email).exists():
                form_errors.append('A teacher with this email already exists.')
                raise ValidationError('Email already exists')

            username = school_email.split('@')[0]
            password = get_random_string(12)
            
            user = User.objects.create_user(
                username=username,
                email=school_email,
                password=password,
                first_name=first_name,
                last_name=surname
            )

            teacher = Teacher(
                user=user,
                first_name=first_name,
                middle_name=middle_name,
                surname=surname,
                school_email=school_email,
                gender=gender,
                nationality=nationality,
                photo=photo,
                is_active=True
            )
            teacher.save()

            messages.success(
                request,
                f'Teacher {teacher.full_name} registered with email {school_email}. '
                f'Username: {username}, Password: {password}'
            )
            Notification.objects.create(
                user=request.user,
                message=f"Teacher {teacher.full_name} registered."
            )
            logger.info(f"Admin {request.user.username} registered teacher {teacher.full_name}")
            return redirect('admin_teacher_management')
        except ValidationError as e:
            if not form_errors:
                form_errors.append(str(e))
            messages.error(request, f'Error: {", ".join(form_errors)}')
            logger.error(f"Error registering teacher: {str(e)}")
        except Exception as e:
            form_errors.append('An unexpected error occurred.')
            messages.error(request, 'An unexpected error occurred.')
            logger.error(f"Unexpected error registering teacher: {str(e)}")

    paginator = Paginator(teachers, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context.update({
        'page_obj': page_obj,
        'teachers': page_obj.object_list,
        'form_data': form_data,
        'form_errors': form_errors,
        'current_session': current_session,
        'filter_name': name or '',
        'filter_email': email or '',
        'filter_gender': gender or '',
        'filter_is_active': is_active or '',
    })
    return render(request, 'account/admin/admin_teacher_management.html', context)

@login_required
@admin_required
def filter_teachers(request):
    try:
        name = request.GET.get('name')
        email = request.GET.get('email')
        gender = request.GET.get('gender')
        is_active = request.GET.get('is_active')
        page_number = request.GET.get('page', 1)
        
        current_session, _ = get_current_session_term()
        teachers = Teacher.objects.all().select_related('user')
        
        if name:
            teachers = teachers.filter(
                Q(first_name__icontains=name) |
                Q(middle_name__icontains=name) |
                Q(surname__icontains=name)
            )
        if email:
            teachers = teachers.filter(school_email__icontains=email)
        if gender:
            teachers = teachers.filter(gender=gender)
        if is_active in ['true', 'false']:
            teachers = teachers.filter(is_active=(is_active == 'true'))
            
        teachers = teachers.prefetch_related(
            Prefetch(
                'assigned_sections',
                queryset=ClassSection.objects.filter(session=current_session).select_related('school_class'),
                to_attr='current_sections'
            )
        )

        paginator = Paginator(teachers, 25)
        page_obj = paginator.get_page(page_number)
        
        data = {
            'teachers': [
                {
                    'id': t.id,
                    'first_name': t.first_name,
                    'middle_name': t.middle_name or '',
                    'surname': t.surname,
                    'school_email': t.school_email,
                    'gender': t.gender,
                    'gender_display': t.get_gender_display(),
                    'nationality': t.nationality,
                    'is_active': t.is_active,
                    'sections': [str(s) for s in t.current_sections]
                } for t in page_obj.object_list
            ],
            'pagination': {
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
                'previous_page': page_obj.previous_page_number() if page_obj.has_previous() else None,
            }
        }
        return JsonResponse(data)
    except Exception as e:
        logger.error(f"Error in filter_teachers: {str(e)}")
        return JsonResponse({'teachers': [], 'error': str(e)}, status=500)
    
@login_required
@admin_required
def promote_students(request):
    if request.method == 'POST':
        try:
            management.call_command('promote_students')
            messages.success(request, 'Student promotion completed successfully.')
        except Exception as e:
            messages.error(request, f'Error during promotion: {str(e)}')
        return redirect('admin_student_management')

    students = Student.objects.filter(is_active=True).exclude(current_class__level='SS 3')
    context = {
        'user': request.user,
        'students': students,
        'students_count': students.count(),
        'role': 'admin'
    }
    return render(request, 'account/admin/promote_students.html', context)

@login_required
@admin_required
def admin_view_student_results(request, admission_number, session_id, term):
    try:
        student = Student.objects.get(admission_number=admission_number)
        session = Session.objects.get(id=session_id)
    except Student.DoesNotExist:
        messages.error(request, 'Student not found')
        logger.error(f"Student with admission_number {admission_number} not found")
        return redirect('admin_manage_result_access_requests')
    except Session.DoesNotExist:
        messages.error(request, 'Session not found')
        logger.error(f"Session with id {session_id} not found")
        return redirect('admin_manage_result_access_requests')

    from accounts.models import TERM_CHOICES
    if term not in [t[0] for t in TERM_CHOICES]:
        messages.error(request, 'Invalid term')
        logger.error(f"Invalid term {term}")
        return redirect('admin_manage_result_access_requests')
    
    is_nursery = student.current_class and student.current_class.section == 'Nursery'
    is_primary = student.current_class and student.current_class.section == 'Primary'
    
    student_subjects = StudentSubject.objects.filter(
        student=student,
        session=session,
        term=term
    ).select_related('subject')
    subject_ids = list(student_subjects.values_list('subject__id', flat=True))

    
    results = Result.objects.filter(
        student=student,
        session=session,
        term=term,
        subject__id__in=subject_ids
    ).select_related('subject').order_by('subject__id')

    
    valid_results = [r for r in results if r.total_score > 0]
    average_score = sum(r.total_score for r in valid_results) / len(valid_results) if valid_results else 0.0
    average_grade_point = (
        sum(r.grade_point for r in valid_results if r.grade_point is not None) / len(valid_results)
        if valid_results and any(r.grade_point is not None for r in valid_results) else 0.0
    )
    class_position_marks = valid_results[0].class_position if valid_results else '-'
    class_position_gp = valid_results[0].class_position_gp if valid_results and not (is_nursery or is_primary) else '-'
    total_in_section = student.current_section.students.count() if student.current_section else 0

    context = {
        'student': student,
        'session': session,
        'term': term,
        'term_display': dict(TERM_CHOICES).get(term, term),
        'results': results,
        'is_nursery': is_nursery,
        'is_primary': is_primary,
        'average_score': average_score,
        'average_grade_point': average_grade_point,
        'class_position_marks': class_position_marks,
        'class_position_gp': class_position_gp,
        'total_in_section': total_in_section,
    }

    logger.debug(f"Rendering admin_view_student_results for {student.full_name}, session {session.name}, term {term}")
    return render(request, 'account/admin/admin_view_student_results.html', context)

@login_required
@admin_required
def assign_teacher_to_section(request, teacher_id):
    try:
        teacher = Teacher.objects.get(id=teacher_id)
    except Teacher.DoesNotExist:
        messages.error(request, 'Teacher not found')
        return redirect('admin_teacher_management')

    context = get_user_context(request)
    if not context:
        return redirect('login')

    current_session, _ = get_current_session_term()
    all_sections = ClassSection.objects.filter(session=current_session).select_related('school_class').order_by('school_class_id')
    assigned_sections = teacher.assigned_sections.filter(session=current_session)

    if request.method == 'POST':
        try:
            section_ids = request.POST.getlist('sections')
            
            teacher.assigned_sections.clear()
            
            for section_id in section_ids:
                section = ClassSection.objects.get(id=section_id)
                teacher.assigned_sections.add(section)
            
            messages.success(request, f'Sections assigned successfully for {teacher.full_name}.')
            return redirect('assign_teacher_to_section', teacher_id=teacher.id)
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')

    context.update({
        'teacher': teacher,
        'all_sections': all_sections,
        'assigned_sections': assigned_sections,
        'current_session': current_session,
    })
    return render(request, 'account/admin/assign_teacher_to_section.html', context)

@login_required
@admin_required
def admin_manage_sections(request):
    context = get_user_context(request)
    if not context:
        return redirect('login')

    current_session, _ = get_current_session_term()
    sessions = Session.objects.all().order_by('-start_year')
    classes = SchoolClass.objects.all().order_by('level_order')

    if request.method == 'POST':
        try:
            with transaction.atomic():
                class_id = request.POST.get('class_id')
                suffix = request.POST.get('suffix')
                session_id = request.POST.get('session_id')
                
                school_class = SchoolClass.objects.get(id=class_id)
                session = Session.objects.get(id=session_id)
                
                
                if ClassSection.objects.filter(
                    school_class=school_class,
                    suffix=suffix,
                    session=session
                ).exists():
                    raise ValidationError('This section already exists for the selected session')
                
                
                ClassSection.objects.create(
                    school_class=school_class,
                    suffix=suffix,
                    session=session
                )
                
                messages.success(request, f'Section {school_class.level}{suffix} created for {session.name}')
                return redirect('admin_manage_sections')
                
        except (SchoolClass.DoesNotExist, Session.DoesNotExist) as e:
            messages.error(request, 'Invalid class or session selected')
        except ValidationError as e:
            messages.error(request, str(e))
        except Exception as e:
            logger.error(f"Error creating section: {str(e)}")
            messages.error(request, 'An error occurred while creating the section')

    
    sections_by_session = {}
    for session in sessions:
        sections = ClassSection.objects.filter(session=session).select_related('school_class').order_by('school_class_id') 
        sections_by_session[session] = sections

    context.update({
        'sessions': sessions,
        'current_session': current_session,
        'classes': classes,
        'sections_by_session': sections_by_session,
        'section_suffixes': ['A', 'B', 'C'],
    })
    return render(request, 'account/admin/manage_sections.html', context)

def validate_section_modification(view_func):
    """Decorator to prevent modification of past session sections"""
    def wrapper(request, section_id, *args, **kwargs):
        try:
            section = ClassSection.objects.get(id=section_id)
            if not section.can_be_modified():
                messages.error(request, 'Cannot modify sections from past sessions')
                return redirect('admin_manage_sections')
            return view_func(request, section_id, *args, **kwargs)
        except ClassSection.DoesNotExist:
            messages.error(request, 'Section not found')
            return redirect('admin_manage_sections')
    return wrapper

@login_required
@admin_required
@validate_section_modification
def admin_update_section(request, section_id):
    try:
        section = ClassSection.objects.get(id=section_id)
    except ClassSection.DoesNotExist:
        messages.error(request, 'Section not found')
        return redirect('admin_manage_sections')

    if not section.can_be_modified():
        messages.error(request, 'Cannot modify sections from past sessions')
        return redirect('admin_manage_sections')

    context = get_user_context(request)
    if not context:
        return redirect('login')

    current_session, _ = get_current_session_term()
    teachers = Teacher.objects.filter(is_active=True)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                action = request.POST.get('action')
                
                if action == 'update_teachers':
                    teacher_ids = request.POST.getlist('teachers')
                    section.teachers.clear()
                    for teacher_id in teacher_ids:
                        teacher = Teacher.objects.get(id=teacher_id)
                        section.teachers.add(teacher)
                    
                    messages.success(request, 'Teachers updated successfully')
                    return redirect('admin_update_section', section_id=section.id)
                
                elif action == 'toggle_active':
                    section.is_active = not section.is_active
                    section.save()
                    
                    status = "activated" if section.is_active else "deactivated"
                    messages.success(request, f'Section {status} successfully')
                    return redirect('admin_update_section', section_id=section.id)
                
        except Teacher.DoesNotExist:
            messages.error(request, 'Invalid teacher selected')
        except Exception as e:
            logger.error(f"Error updating section: {str(e)}")
            messages.error(request, 'An error occurred while updating the section')

    context.update({
        'section': section,
        'current_session': current_session,
        'all_teachers': teachers,
        'assigned_teachers': section.teachers.all(),
    })
    return render(request, 'account/admin/update_section.html', context)

@login_required
@admin_required
def update_student(request, admission_number):
    try:
        student = Student.objects.get(admission_number=admission_number)
    except Student.DoesNotExist:
        messages.error(request, 'Student not found')
        logger.error(f"Student with admission_number {admission_number} not found")
        return redirect('admin_student_management')

    form_data = {}
    form_errors = []

    if request.method == 'POST':
        try:
            with transaction.atomic():
                full_name = request.POST.get('full_name')
                date_of_birth = request.POST.get('date_of_birth')
                address = request.POST.get('address')
                parent_phone = request.POST.get('parent_phone')
                gender = request.POST.get('gender')
                class_id = request.POST.get('class')
                section_id = request.POST.get('section')
                photo = request.FILES.get('photo')
                is_active = request.POST.get('is_active') == 'on'

                form_data = {
                    'full_name': full_name,
                    'date_of_birth': date_of_birth,
                    'address': address,
                    'parent_phone': parent_phone,
                    'gender': gender,
                    'class': class_id,
                    'section': section_id,
                    'is_active': is_active,
                }

                if not full_name:
                    form_errors.append('Full name is required.')
                if not date_of_birth:
                    form_errors.append('Date of birth is required.')
                if not address:
                    form_errors.append('Address is required.')
                if not parent_phone:
                    form_errors.append('Parent phone is required.')
                if not gender:
                    form_errors.append('Gender is required.')
                if not class_id:
                    form_errors.append('Class is required.')

                if form_errors:
                    raise ValidationError('Missing required fields')

                if not re.match(r'^\+?\d{10,15}$', parent_phone):
                    form_errors.append('Invalid phone number format')
                    raise ValidationError('Invalid phone number format')
                if gender not in ['M', 'F']:
                    form_errors.append('Invalid gender')
                    raise ValidationError('Invalid gender')

                school_class = SchoolClass.objects.get(id=class_id)
                class_section = ClassSection.objects.get(id=section_id) if section_id else None

                student.full_name = full_name
                student.date_of_birth = date_of_birth
                student.address = address
                student.parent_phone = parent_phone
                student.gender = gender
                student.current_class = school_class
                student.current_section = class_section
                student.is_active = is_active
                if photo:
                    student.photo = photo
                student.save()

                student.user.first_name = student.full_name.split()[0]
                student.user.last_name = ' '.join(student.full_name.split()[1:]) if len(student.full_name.split()) > 1 else ''
                student.user.save()

                messages.success(request, f'Student {full_name} updated successfully.')
                Notification.objects.create(
                    user=request.user,
                    message=f"Student {full_name} details updated."
                )
                logger.info(f"Admin {request.user.username} updated student {full_name}")
                return redirect('student_detail', admission_number=admission_number)
        except (SchoolClass.DoesNotExist, ClassSection.DoesNotExist) as e:
            form_errors.append(str(e))
            messages.error(request, f'Error: {", ".join(form_errors)}')
            logger.error(f"Error updating student: {str(e)}")
        except ValidationError as e:
            if not form_errors:
                form_errors.append(str(e))
            messages.error(request, f'Error: {", ".join(form_errors)}')
            logger.error(f"Error updating student: {str(e)}")
        except Exception as e:
            form_errors.append('An unexpected error occurred')
            messages.error(request, 'An unexpected error occurred')
            logger.error(f"Unexpected error updating student: {str(e)}")

    context = get_user_context(request)
    if not context:
        return redirect('login')

    current_session, _ = get_current_session_term()
    
    context.update({
        'student': student,
        'classes': SchoolClass.objects.all(),
        'class_sections': ClassSection.objects.filter(session=current_session, school_class=student.current_class),
        'genders': Student._meta.get_field('gender').choices,
        'form_data': form_data or {
            'full_name': student.full_name,
            'date_of_birth': student.date_of_birth.strftime('%Y-%m-%d'),
            'address': student.address,
            'parent_phone': student.parent_phone,
            'gender': student.gender,
            'class': student.current_class.id if student.current_class else '',
            'section': student.current_section.id if student.current_section else '',
            'is_active': student.is_active,
        },
        'form_errors': form_errors,
    })
    return render(request, 'account/admin/update_student.html', context)

@login_required
@teacher_required
def teacher_view_students(request):
    context = get_user_context(request)
    if not context:
        return redirect('login')

    teacher = context['teacher']
    current_session, _ = get_current_session_term()
    
    teacher_sections = ClassSection.objects.filter(
        teachers=teacher,
        session=current_session
    ).select_related('school_class')
    
    section_id = request.GET.get('section')
    selected_section = teacher_sections.first()
    
    if section_id:
        try:
            selected_section = teacher_sections.get(id=section_id)
        except ClassSection.DoesNotExist:
            messages.error(request, 'Invalid section selected')
            return redirect('teacher_view_students')
    
    if not selected_section:
        messages.error(request, 'You are not assigned to any sections')
        return redirect('dashboard')
    
    unassigned_students = Student.objects.filter(
        current_class=selected_section.school_class,
        current_section__isnull=True,
        is_active=True
    ).select_related('current_class')
    
    assigned_students = Student.objects.filter(
        current_section=selected_section,
        is_active=True
    ).select_related('current_class', 'current_section')
    
    context.update({
        'unassigned_students': unassigned_students,
        'assigned_students': assigned_students,
        'teacher_sections': teacher_sections,
        'selected_section': selected_section,
        'current_session': current_session,
    })
    return render(request, 'account/teacher/teacher_view_students.html', context)

@login_required
@teacher_required
def assign_student_to_section(request):
    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        admission_number = request.POST.get('admission_number')
        section_id = request.POST.get('section_id')
        
        try:
            with transaction.atomic():
                student = Student.objects.get(admission_number=admission_number)
                section = ClassSection.objects.get(id=section_id)
                teacher = request.user.teacher
                current_session, current_term = get_current_session_term()
                
                if teacher not in section.teachers.all():
                    logger.warning(f"Teacher {teacher.full_name} not authorized to assign to section {section}")
                    return JsonResponse({
                        'success': False,
                        'message': 'You are not authorized to assign students to this section'
                    }, status=403)
                
                if student.current_class != section.school_class:
                    logger.warning(f"Student {student.full_name} class {student.current_class} does not match section {section}")
                    return JsonResponse({
                        'success': False,
                        'message': 'Student must be in the same class level as the section'
                    }, status=400)
                
                old_section = student.current_section  
                student.current_section = section
                student.save()
                
                
                update_subject_positions(student, current_session, current_term)
                update_class_positions(section, current_session, current_term)
                logger.info(f"Assigned {student.full_name} to {section}. Updated positions.")
                
                
                if old_section and old_section != section:
                    update_class_positions(old_section, current_session, current_term)
                    logger.info(f"Updated positions for old section {old_section} after removing {student.full_name}")
                
                return JsonResponse({
                    'success': True,
                    'message': f'Student successfully assigned to {section}',
                    'section_name': str(section)
                })
            
        except (Student.DoesNotExist, ClassSection.DoesNotExist) as e:
            logger.error(f"Error assigning student: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=404)
        except Exception as e:
            logger.error(f"Unexpected error assigning student: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)
    
    return JsonResponse({
        'success': False,
        'message': 'Invalid request method'
    }, status=405)

@login_required
@teacher_required
def remove_student_from_section(request):
    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        admission_number = request.POST.get('admission_number')
        
        try:
            with transaction.atomic():
                student = Student.objects.get(admission_number=admission_number)
                teacher = request.user.teacher
                current_session, current_term = get_current_session_term()
                
                if student.current_section and teacher not in student.current_section.teachers.all():
                    logger.warning(f"Teacher {teacher.full_name} not authorized to remove from section {student.current_section}")
                    return JsonResponse({
                        'success': False,
                        'message': 'You are not authorized to remove students from this section'
                    }, status=403)
                
                old_section = student.current_section  
                if old_section:

                    Result.objects.filter(
                        student=student,
                        session=current_session,
                        term=current_term
                    ).update(subject_position='', class_position='')
                    student.current_section = None
                    student.save()
                    
                    
                    update_class_positions(old_section, current_session, current_term)
                    logger.info(f"Removed {student.full_name} from {old_section}. Updated positions.")
                    
                    return JsonResponse({
                        'success': True,
                        'message': 'Student successfully removed from section'
                    })
                else:
                    logger.warning(f"Student {student.full_name} was not assigned to any section")
                    return JsonResponse({
                        'success': False,
                        'message': 'Student is not assigned to any section'
                    }, status=400)
            
        except Student.DoesNotExist as e:
            logger.error(f"Error removing student: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=404)
        except Exception as e:
            logger.error(f"Unexpected error removing student: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=500)
    
    return JsonResponse({
        'success': False,
        'message': 'Invalid request method'
    }, status=405)

@login_required
@teacher_required
def teacher_manage_subjects(request):
    context = get_user_context(request)
    if not context:
        return redirect('login')
    
    teacher = context['teacher']
    current_session, current_term = get_current_session_term()
    
    teacher_sections = teacher.assigned_sections.filter(
        session=current_session
    ).select_related('school_class')
    
    if not teacher_sections.exists():
        messages.warning(request, 'You are not currently assigned to any class sections.')
        context.update({
            'teacher_sections': [],
            'current_session': current_session,
            'current_term': current_term,
        })
        return render(request, 'account/teacher/manage_student_subjects.html', context)
    
    section_id = request.GET.get('section')
    selected_section = teacher_sections.first()
    
    if section_id:
        try:
            selected_section = teacher_sections.get(id=section_id)
        except ClassSection.DoesNotExist:
            messages.error(request, 'Invalid class section selected.')
            return redirect('teacher_manage_subjects')
    
    students = Student.objects.filter(
        current_section=selected_section,
        is_active=True
    ).select_related('current_class')
    
    class_subjects = Subject.objects.filter(
        school_class=selected_section.school_class,
        is_active=True
    ).order_by('id')
    
    selected_student = None
    student_subjects = []
    student_admission_number = request.GET.get('student')
    
    if student_admission_number:
        try:
            selected_student = students.get(admission_number=student_admission_number)
            student_subjects = list(selected_student.assigned_subjects.filter(
                session=current_session,
                term=current_term
            ).values_list('subject__id', flat=True))
        except Student.DoesNotExist:
            messages.error(request, 'Invalid student selected.')
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                action = request.POST.get('action')
                
                if action == 'assign_subjects':
                    student_admission_number = request.POST.get('student')
                    subject_ids = request.POST.getlist('subjects')
                    
                    if not student_admission_number or not subject_ids:
                        raise ValidationError('Student and at least one subject are required')
                    
                    student = students.get(admission_number=student_admission_number)
                    
                    StudentSubject.objects.filter(
                        student=student,
                        session=current_session,
                        term=current_term
                    ).delete()
                    
                    for subject_id in subject_ids:
                        subject = Subject.objects.get(id=subject_id)
                        StudentSubject.objects.create(
                            student=student,
                            subject=subject,
                            session=current_session,
                            term=current_term,
                            assigned_by=teacher
                        )
                    
                    messages.success(request, f'Subjects assigned successfully for {student.full_name}.')
                    return redirect(f"{reverse('teacher_manage_subjects')}?section={selected_section.id}&student={student_admission_number}")
                
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')

    context.update({
        'teacher_sections': teacher_sections,
        'selected_section': selected_section,
        'class_subjects': class_subjects,
        'students': students,
        'selected_student': selected_student,
        'student_subjects': student_subjects,
        'current_session': current_session,
        'current_term': current_term,
    })
    
    return render(request, 'account/teacher/manage_student_subjects.html', context)


def update_subject_positions(student, session, term):
    """Update subject positions for a student's section in real-time, handling ties."""
    if not student.current_section:
        logger.debug(f"No section assigned for student {student.full_name}")
        return

    with transaction.atomic():
        section = ClassSection.objects.get(id=student.current_section.id)
        students = Student.objects.filter(current_section=section)
        
        student_subjects = StudentSubject.objects.filter(
            student__in=students,
            session=session,
            term=term,
            subject__is_active=True
        ).select_related('subject')
        subject_ids = list(student_subjects.values_list('subject__id', flat=True).distinct())

        results = Result.objects.filter(
            student__in=students,
            session=session,
            term=term,
            subject__id__in=subject_ids
        ).select_related('student', 'subject')

        results_by_subject = {}
        for result in results:
            subject_id = result.subject_id
            if subject_id not in results_by_subject:
                results_by_subject[subject_id] = []
            results_by_subject[subject_id].append(result)

        position_updates = []
        for subject_id, subject_results in results_by_subject.items():
            sorted_results = sorted(subject_results, key=lambda r: r.total_score, reverse=True)
            prev_score = None
            rank = 0
            for idx, result in enumerate(sorted_results, 1):
                if round(result.total_score, 2) != prev_score:  
                    rank = idx
                    prev_score = round(result.total_score, 2)
                suffix = 'th' if 10 <= rank % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(rank % 10, 'th')
                result.subject_position = f"{rank}{suffix}"
                position_updates.append(result)

        if position_updates:
            Result.objects.bulk_update(position_updates, ['subject_position'])
            logger.debug(f"Updated subject positions for section {section}")

def update_class_positions(section, session, term):
    """Update class positions for a section in real-time, handling ties correctly."""
    if not section:
        logger.debug("No section provided for class position update")
        return

    with transaction.atomic():
        students = Student.objects.filter(current_section=section)
        if not students.exists():
            logger.debug(f"No students in section {section}")
            return

        student_subjects = StudentSubject.objects.filter(
            student__in=students,
            session=session,
            term=term,
            subject__is_active=True
        ).select_related('subject')
        subject_ids = list(student_subjects.values_list('subject__id', flat=True).distinct())

        results = Result.objects.filter(
            student__in=students,
            session=session,
            term=term,
            subject__id__in=subject_ids
        ).select_related('student', 'subject')

        student_averages = []
        for student in students:
            student_results = [r for r in results if r.student_id == student.pk and r.total_score > 0]
            if student_results:
                avg_marks = sum(r.total_score for r in student_results) / len(student_results)
                avg_gp = (
                    sum(r.grade_point for r in student_results if r.grade_point is not None) / len(student_results)
                    if any(r.grade_point is not None for r in student_results)
                    else 0.0
                )
                student_averages.append({
                    'student_id': student.pk,
                    'avg_marks': round(avg_marks, 2),  
                    'avg_gp': avg_gp,
                    'results': student_results
                })

        position_updates = []
        if student_averages:
            
            sorted_by_marks = sorted(student_averages, key=lambda x: x['avg_marks'], reverse=True)
            prev_avg = None
            rank = 0
            for idx, s in enumerate(sorted_by_marks, 1):
                if s['avg_marks'] != prev_avg:
                    rank = idx
                    prev_avg = s['avg_marks']
                suffix = 'th' if 10 <= rank % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(rank % 10, 'th')
                for result in s['results']:
                    result.class_position = f"{rank}{suffix}"
                    position_updates.append(result)

            
            if section.school_class.section not in ['Nursery', 'Primary']:
                sorted_by_gp = sorted(student_averages, key=lambda x: x['avg_gp'], reverse=True)
                prev_avg_gp = None
                rank_gp = 0
                for idx, s in enumerate(sorted_by_gp, 1):
                    if s['avg_gp'] != prev_avg_gp:
                        rank_gp = idx
                        prev_avg_gp = s['avg_gp']
                    suffix = 'th' if 10 <= rank_gp % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(rank_gp % 10, 'th')
                    for result in s['results']:
                        result.class_position_gp = f"{rank_gp}{suffix}"
                        position_updates.append(result)

        if position_updates:
            Result.objects.bulk_update(position_updates, ['class_position', 'class_position_gp'])
            logger.debug(f"Updated class positions for section {section}")

@login_required
@teacher_required
def update_result(request, admission_number):
    try:
        student = Student.objects.get(admission_number=admission_number)
    except Student.DoesNotExist:
        messages.error(request, 'Student not found')
        logger.error(f"Student with admission_number {admission_number} not found")
        return redirect('teacher_view_students')
    
    context = get_user_context(request)
    if not context:
        return redirect('login')
    
    teacher = context['teacher']
    if not student.current_section or teacher not in student.current_section.teachers.all():
        messages.error(request, 'You are not authorized to update results for this student.')
        return redirect('teacher_view_students')
    
    current_session, current_term = get_current_session_term()
    
    term_end_date = timezone.datetime.strptime(
        {
            '1': f"{current_session.end_year}-12-31",
            '2': f"{current_session.end_year}-04-30",
            '3': f"{current_session.end_year}-08-31",
        }.get(current_term), "%Y-%m-%d").date()
    is_editable = timezone.now().date() <= term_end_date
    
    student_subjects = StudentSubject.objects.filter(
        student=student,
        session=current_session,
        term=current_term,
        subject__is_active=True
    ).select_related('subject')
    
    subject_ids = list(student_subjects.values_list('subject__id', flat=True))
    subjects = Subject.objects.filter(id__in=subject_ids).order_by('id')
    
    if not subjects.exists():
        messages.warning(request, "No subjects assigned to this student.")
    
    existing_results = Result.objects.filter(
        student=student,
        session=current_session,
        term=current_term,
        subject__id__in=subject_ids
    ).select_related('subject')
    
    existing_results_dict = {result.subject.id: result for result in existing_results}
    
    if request.method == 'POST' and is_editable:
        try:
            remarks = request.POST.get('remarks', '').strip()
            is_nursery = student.current_class.section == 'Nursery'
            is_primary = student.current_class.section == 'Primary'
            updates_made = False
            
            for subject in subjects:
                if not subject.is_active:
                    raise ValidationError(f'Cannot update results for inactive subject: {subject.name}')
                try:
                    result = Result.objects.get(
                        student=student,
                        subject=subject,
                        session=current_session,
                        term=current_term
                    )
                except Result.DoesNotExist:
                    result = Result(
                        student=student,
                        subject=subject,
                        session=current_session,
                        term=current_term
                    )
                
                result_updated = False
                
                if is_nursery:
                    total_marks_str = request.POST.get(f'total_marks_{subject.id}', '')
                    if total_marks_str:
                        total_marks = float(total_marks_str)
                        if not 0 <= total_marks <= 100:
                            raise ValidationError(f'Invalid total marks for {subject.name}')
                        if result.total_marks != total_marks:
                            result.total_marks = total_marks
                            result_updated = True
                elif is_primary:
                    test_str = request.POST.get(f'test_{subject.id}', '')
                    homework_str = request.POST.get(f'homework_{subject.id}', '')
                    classwork_str = request.POST.get(f'classwork_{subject.id}', '')
                    nursery_primary_exam_str = request.POST.get(f'nursery_primary_exam_{subject.id}', '')
                    
                    if test_str:
                        test = float(test_str)
                        if not 0 <= test <= 20:
                            raise ValidationError(f'Invalid test score for {subject.name}')
                        if result.test != test:
                            result.test = test
                            result_updated = True
                    if homework_str:
                        homework = float(homework_str)
                        if not 0 <= homework <= 10:
                            raise ValidationError(f'Invalid homework score for {subject.name}')
                        if result.homework != homework:
                            result.homework = homework
                            result_updated = True
                    if classwork_str:
                        classwork = float(classwork_str)
                        if not 0 <= classwork <= 10:
                            raise ValidationError(f'Invalid classwork score for {subject.name}')
                        if result.classwork != classwork:
                            result.classwork = classwork
                            result_updated = True
                    if nursery_primary_exam_str:
                        nursery_primary_exam = float(nursery_primary_exam_str)
                        if not 0 <= nursery_primary_exam <= 60:
                            raise ValidationError(f'Invalid exam score for {subject.name}')
                        if result.nursery_primary_exam != nursery_primary_exam:
                            result.nursery_primary_exam = nursery_primary_exam
                            result_updated = True
                else:  
                    ca_str = request.POST.get(f'ca_{subject.id}', '')
                    test_1_str = request.POST.get(f'test_1_{subject.id}', '')
                    test_2_str = request.POST.get(f'test_2_{subject.id}', '')
                    exam_str = request.POST.get(f'exam_{subject.id}', '')
                    
                    if ca_str:
                        ca = float(ca_str)
                        if not 0 <= ca <= 10:
                            raise ValidationError(f'Invalid CA score for {subject.name}')
                        if result.ca != ca:
                            result.ca = ca
                            result_updated = True
                    if test_1_str:
                        test_1 = float(test_1_str)
                        if not 0 <= test_1 <= 10:
                            raise ValidationError(f'Invalid test 1 score for {subject.name}')
                        if result.test_1 != test_1:
                            result.test_1 = test_1
                            result_updated = True
                    if test_2_str:
                        test_2 = float(test_2_str)
                        if not 0 <= test_2 <= 10:
                            raise ValidationError(f'Invalid test 2 score for {subject.name}')
                        if result.test_2 != test_2:
                            result.test_2 = test_2
                            result_updated = True
                    if exam_str:
                        exam = float(exam_str)
                        if not 0 <= exam <= 70:
                            raise ValidationError(f'Invalid exam score for {subject.name}')
                        if result.exam != exam:
                            result.exam = exam
                            result_updated = True
                
                if remarks and result.remarks != remarks:
                    result.remarks = remarks
                    result_updated = True
                
                if result_updated:
                    result.upload_date = timezone.now()
                    result.uploaded_by = teacher
                    result.save()
                    updates_made = True
            
            if updates_made:
                update_subject_positions(student, current_session, current_term)
                update_class_positions(student.current_section, current_session, current_term)
                
                messages.success(request, f'Results updated for {student.full_name}.')
                
                Notification.objects.create(
                    user=student.user,
                    message=f"Your results for {current_session.name} Term {dict(TERM_CHOICES).get(current_term)} have been updated."
                )
            else:
                messages.info(request, f'No changes made to results for {student.full_name}.')
            
            return redirect('update_result', admission_number=admission_number)
        
        except ValidationError as e:
            messages.error(request, f'Error: {str(e)}')
        except (ValueError, TypeError) as e:
            messages.error(request, f'Invalid score format: {str(e)}')
        except Exception as e:
            messages.error(request, f'An unexpected error occurred: {str(e)}')
    
    elif request.method == 'POST' and not is_editable:
        messages.error(request, 'Results cannot be edited after the term has ended.')
        return redirect('update_result', admission_number=admission_number)
    
    context.update({
        'student': student,
        'subjects': subjects,
        'sessions': Session.objects.all(),
        'terms': TERM_CHOICES,
        'current_session': current_session,
        'current_term': current_term,
        'selected_session': current_session,
        'selected_term': current_term,
        'existing_results': existing_results_dict,
        'is_nursery': student.current_class.section == 'Nursery',
        'is_primary': student.current_class.section == 'Primary',
        'next_term_start_date': getattr(settings, 'NEXT_TERM_START_DATE', 'TBD'),
        'remarks': existing_results.first().remarks if existing_results.exists() else '',
        'is_editable': is_editable,
        'term_end_date': term_end_date,
    })
    
    return render(request, 'account/teacher/update_result.html', context)

@login_required
@teacher_required
def teacher_view_student_past_results(request, admission_number):
    try:
        student = Student.objects.get(admission_number=admission_number)
    except Student.DoesNotExist:
        messages.error(request, 'Student not found')
        logger.error(f"Student with admission_number {admission_number} not found")
        return redirect('teacher_view_students')

    context = get_user_context(request)
    if not context:
        return redirect('login')

    teacher = context['teacher']
    current_session, current_term = get_current_session_term()
    is_nursery = student.current_class and student.current_class.section == 'Nursery'
    is_primary = student.current_class and student.current_class.section == 'Primary'
    
    past_results = Result.objects.filter(
        student=student
    ).exclude(
        session=current_session,
        term=current_term
    ).select_related('subject', 'session', 'student__current_class').order_by(
        'student__current_class__level_order', 'session__start_year', 'term', 'subject__id'
    )

    results_by_class = {}
    for result in past_results:
        class_level = result.student.current_class.level if result.student.current_class else 'Unknown'
        if class_level not in results_by_class:
            results_by_class[class_level] = []
        results_by_class[class_level].append(result)

    sorted_classes = sorted(
        results_by_class.keys(),
        key=lambda x: SchoolClass.objects.get(level=x).level_order if x != 'Unknown' else 0
    )

    
    context.update({
        'student': student,
        'results_by_class': {class_level: results_by_class[class_level] for class_level in sorted_classes},
        'current_session': current_session,
        'current_term': current_term,
        
        'is_nursery':is_nursery,
        'is_primary':is_primary

    })

    logger.debug(f"Rendering past results for student {student.full_name} with {past_results.count()} results")
    return render(request, 'account/teacher/view_student_past_results.html', context)


@login_required
@student_required
def student_view_subjects(request):
    context = get_user_context(request)
    if not context:
        logger.error(f"Invalid user context for user {request.user.username}")
        return redirect('login')

    student = context['student']
    current_session, current_term = get_current_session_term()

    selected_session_id = request.GET.get('session', current_session.id)
    selected_term = request.GET.get('term', current_term)

    try:
        selected_session = Session.objects.get(id=selected_session_id)
    except Session.DoesNotExist:
        logger.error(f"Session with id {selected_session_id} not found")
        messages.error(request, "Selected session not found")
        selected_session = current_session
        selected_session_id = current_session.id

    if selected_term not in [t[0] for t in TERM_CHOICES]:
        logger.warning(f"Invalid term {selected_term} selected by {student.full_name}")
        messages.error(request, "Invalid term selected")
        selected_term = current_term

    if selected_session == current_session and selected_term == current_term:
        assigned_subjects = StudentSubject.objects.filter(
            student=student,
            session=selected_session,
            term=selected_term,
            subject__is_active=True
        ).select_related('subject', 'assigned_by').order_by('subject__id')
    else:
        assigned_subjects = StudentSubject.objects.filter(
            student=student,
            session=selected_session,
            term=selected_term
        ).select_related('subject', 'assigned_by').order_by('subject__id')

    if not assigned_subjects.exists():
        messages.info(request, f"No subjects assigned for {selected_session.name} Term {selected_term}.")

    context.update({
        'student': student,
        'assigned_subjects': assigned_subjects,
        'current_session': current_session,
        'current_term': current_term,
        'selected_session': selected_session,
        'selected_term': selected_term,
        'sessions': Session.objects.all(),
        'terms': TERM_CHOICES,
    })

    logger.debug(f"Rendering student_view_subjects for {student.full_name} with {assigned_subjects.count()} subjects for {selected_session.name} Term {selected_term}")
    return render(request, 'account/student/student_view_subjects.html', context)

@login_required
@student_required
def student_grades(request):
    context = get_user_context(request)
    if not context:
        logger.error(f"Invalid user context for user {request.user.username}")
        return redirect('login')

    student = context['student']

    if student.current_class and student.current_class.level == 'Creche':
        messages.info(request, 'Creche students do not have grades.')
        logger.info(f"Creche student {student.full_name} attempted to view grades")
        return redirect('dashboard')

    current_session, current_term = get_current_session_term()
    if not current_session or not current_term:
        messages.error(request, "Unable to determine current session or term.")
        logger.error(f"No current session or term for student {student.full_name}")
        return redirect('dashboard')

    logger.debug(f"Checking grades for student {student.full_name}, session: {current_session.name}, term: {current_term}")

    is_nursery = student.current_class and student.current_class.section == 'Nursery'
    is_primary = student.current_class and student.current_class.section == 'Primary'

    # Check fees paid through parent
    fees_paid = False
    if student.parent:
        fees_paid = Payment.objects.filter(
            parent=student.parent,
            session=current_session,
            term=current_term,
            status='Completed'
        ).exists()
    logger.debug(f"Fees paid for student {student.full_name} by parent {student.parent.phone_number if student.parent else 'None'}: {fees_paid}")

    access_approved = False
    access_request = None
    if not fees_paid:
        access_request = ResultAccessRequest.objects.filter(
            student=student,
            session=current_session,
            term=current_term
        ).first()
        access_approved = access_request and access_request.status == 'Approved'
    logger.debug(f"Access request status: {access_request.status if access_request else 'None'}, Approved: {access_approved}")

    student_subjects = StudentSubject.objects.filter(
        student=student,
        session=current_session,
        term=current_term,
        subject__is_active=True
    ).select_related('subject')
    subject_ids = list(student_subjects.values_list('subject__id', flat=True))
    logger.debug(f"StudentSubject IDs: {subject_ids}, Count: {len(subject_ids)}")

    if not subject_ids:
        result_subjects = Result.objects.filter(
            student=student,
            session=current_session,
            term=current_term
        ).values_list('subject__id', flat=True).distinct()
        subject_ids = list(result_subjects)
        logger.warning(
            f"No StudentSubject records for {student.full_name} in {current_session.name}, term {current_term}. "
            f"Fallback to Result subjects: {subject_ids}"
        )

    results = []
    result_upload_date = None
    average_score = 0.0
    average_grade_point = 0.0
    class_position_marks = '-'
    class_position_gp = '-'
    total_in_section = 0
    overall_remark = None

    if (fees_paid or access_approved) and subject_ids:
        existing_results = Result.objects.filter(
            student=student,
            session=current_session,
            term=current_term,
            subject__id__in=subject_ids
        ).select_related('subject').order_by('subject__id')

        results_dict = {result.subject.id: result for result in existing_results}

        for student_subject in student_subjects:
            subject = student_subject.subject
            result = results_dict.get(subject.id)
            if not result:
                result = Result(
                    student=student,
                    subject=subject,
                    session=current_session,
                    term=current_term,
                    total_score=0,
                    grade='-',
                    description='-',
                    subject_position='-'
                )
            results.append(result)
            if result.remarks and not overall_remark:
                overall_remark = result.remarks

        if results:
            latest_result = max(
                results,
                key=lambda r: r.upload_date if r.upload_date else timezone.datetime.min.replace(tzinfo=timezone.utc),
                default=None
            )
            if latest_result and latest_result.upload_date:
                result_upload_date = latest_result.upload_date

            valid_results = [r for r in results if r.total_score > 0]
            if valid_results:
                average_score = sum(r.total_score for r in valid_results) / len(valid_results)
                average_grade_point = (
                    sum(r.grade_point for r in valid_results if r.grade_point is not None) / len(valid_results)
                    if any(r.grade_point is not None for r in valid_results)
                    else 0.0
                )
            else:
                average_score = 0.0
                average_grade_point = 0.0

            if student.current_section:
                section_results = Result.objects.filter(
                    session=current_session,
                    term=current_term,
                    student__current_section=student.current_section
                ).values('student__admission_number').annotate(total=Sum('total_score')).order_by('-total')

                total_in_section = section_results.count()
                for idx, res in enumerate(section_results, 1):
                    if res['student__admission_number'] == student.admission_number:
                        class_position_marks = f"{idx}{get_ordinal_suffix(idx)}"
                        class_position_gp = class_position_marks if not (is_nursery or is_primary) else '-'
                        break

    past_results = Result.objects.filter(
        student=student,
    ).exclude(
        Q(session=current_session, term=current_term) |
        Q(total_score=0)
    ).select_related('subject', 'session').order_by('-session__start_year', 'term', 'subject__name')

    past_results_grouped = []
    sessions_with_results = set()

    for session in Session.objects.filter(
        result__student=student,
        result__subject__id__in=subject_ids
    ).distinct().order_by('-start_year'):
        for term in ['1', '2', '3']:
            term_results = [r for r in past_results if r.session == session and r.term == term]
            if not term_results:
                continue

            term_fees_paid = False
            if student.parent:
                term_fees_paid = Payment.objects.filter(
                    parent=student.parent,
                    session=session,
                    term=term,
                    status='Completed'
                ).exists()

            term_access_approved = False
            term_access_request = None
            if not term_fees_paid:
                term_access_request = ResultAccessRequest.objects.filter(
                    student=student,
                    session=session,
                    term=term
                ).first()
                term_access_approved = term_access_request and term_access_request.status == 'Approved'

            term_valid_results = [r for r in term_results if r.total_score > 0]
            term_avg_score = sum(r.total_score for r in term_valid_results) / len(term_valid_results) if term_valid_results else 0
            term_avg_gp = (
                sum(r.grade_point for r in term_valid_results if r.grade_point is not None) / len(term_valid_results)
                if term_valid_results and any(r.grade_point is not None for r in term_valid_results)
                else 0
            ) if not (is_nursery or is_primary) else None

            term_total_in_section = 0
            term_class_position = '-'
            term_class_position_gp = '-'
            if student.current_section:
                past_section_results = Result.objects.filter(
                    session=session,
                    term=term,
                    student__current_section=student.current_section
                ).values('student__admission_number').annotate(total=Sum('total_score')).order_by('-total')
                term_total_in_section = past_section_results.count()
                for idx, res in enumerate(past_section_results, 1):
                    if res['student__admission_number'] == student.admission_number:
                        term_class_position = f"{idx}{get_ordinal_suffix(idx)}"
                        term_class_position_gp = term_class_position if not (is_nursery or is_primary) else '-'
                        break

            past_results_grouped.append({
                'session': session,
                'term': term,
                'term_display': dict(TERM_CHOICES).get(term),
                'results': term_results,
                'has_access': term_fees_paid or term_access_approved,
                'fees_paid': term_fees_paid,
                'access_request': term_access_request,
                'average_score': term_avg_score,
                'average_grade_point': term_avg_gp,
                'class_position': term_class_position,
                'class_position_gp': term_class_position_gp,
                'total_in_section': term_total_in_section
            })

    if not fees_paid:
        approved_requests = ResultAccessRequest.objects.filter(
            student=student,
            status='Approved'
        ).values_list('session__id', 'term')
        past_results = past_results.filter(
            Q(session__id__in=[req[0] for req in approved_requests]) &
            Q(term__in=[req[1] for req in approved_requests])
        )
    logger.debug(f"Past results: {past_results.count()}")

    context.update({
        'results': results,
        'average_score': round(average_score, 2),
        'average_grade_point': (
            round(average_grade_point, 2)
            if not (is_nursery or is_primary)
            else None
        ),
        'class_position_marks': class_position_marks,
        'class_position_gp': class_position_gp,
        'past_results': past_results,
        'current_session': current_session,
        'past_results_grouped': past_results_grouped,
        'current_term': current_term,
        'current_term_display': dict(TERM_CHOICES).get(current_term, current_term),
        'fees_paid': fees_paid,
        'access_approved': access_approved,
        'access_request': access_request,
        'subject_ids': subject_ids,
        'sessions': Session.objects.all(),
        'terms': TERM_CHOICES,
        'next_term_start_date': getattr(settings, 'NEXT_TERM_START_DATE', 'TBD'),
        'is_nursery': is_nursery,
        'is_primary': is_primary,
        'result_upload_date': result_upload_date,
        'total_in_section': total_in_section,
        'student': student,
        'overall_remark': overall_remark,
    })

    logger.debug(f"Rendering student_grades for {student.full_name} with {len(results)} results and {past_results.count()} past results")
    return render(request, 'account/student/student_grades.html', context)

@login_required
@student_required
def export_current_term_results_pdf(request):
    student = request.user.student
    current_session, current_term = get_current_session_term()
    
    is_nursery = student.current_class and student.current_class.section == 'Nursery'
    is_primary = student.current_class and student.current_class.section == 'Primary'
    
    student_subjects = StudentSubject.objects.filter(
        student=student,
        session=current_session,
        term=current_term
    ).select_related('subject')
    subject_ids = list(student_subjects.values_list('subject__id', flat=True))
    
    results = Result.objects.filter(
        student=student,
        session=current_session,
        term=current_term,
        subject__id__in=subject_ids
    ).select_related('subject').order_by('subject__name')
    
    pdf_buffer = generate_result_pdf(
        student, 
        results, 
        current_session, 
        current_term,
        is_nursery=is_nursery,
        is_primary=is_primary
    )
    
    filename = f"Results_{student.full_name}_{current_session.name}_Term{current_term}.pdf"
    response = HttpResponse(pdf_buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

@login_required
@student_required
def export_past_term_results_pdf(request, session_id, term):
    student = request.user.student
    try:
        session = Session.objects.get(id=session_id)
    except Session.DoesNotExist:
        messages.error(request, 'Session not found')
        return redirect('student_grades')
    
    is_nursery = student.current_class and student.current_class.section == 'Nursery'
    is_primary = student.current_class and student.current_class.section == 'Primary'
    
    student_subjects = StudentSubject.objects.filter(
        student=student,
        session=session,
        term=term
    ).select_related('subject')
    subject_ids = list(student_subjects.values_list('subject__id', flat=True))
    
    results = Result.objects.filter(
        student=student,
        session=session,
        term=term,
        subject__id__in=subject_ids
    ).select_related('subject').order_by('subject__name')
    
    pdf_buffer = generate_result_pdf(
        student, 
        results, 
        session, 
        term,
        is_nursery=is_nursery,
        is_primary=is_primary
    )
    
    filename = f"Results_{student.full_name}_{session.name}_Term{term}.pdf"
    response = HttpResponse(pdf_buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

@login_required
@student_required
def student_request_result_access(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)

    student = Student.objects.get(user=request.user, is_active=True)
    session_id = request.POST.get('session_id')
    term = request.POST.get('term')

    try:
        session = Session.objects.get(id=session_id)
    except Session.DoesNotExist:
        logger.error(f"Session with id {session_id} not found")
        return JsonResponse({'success': False, 'error': 'Invalid session'}, status=400)

    if term not in dict(TERM_CHOICES):
        logger.error(f"Invalid term {term} for student {student.admission_number}")
        return JsonResponse({'success': False, 'error': 'Invalid term'}, status=400)

    if student.parent:
        payment_status = Payment.objects.filter(
            parent=student.parent,
            session=session,
            term=term,
            status='Completed'
        ).exists()
        if payment_status:
            logger.info(f"Fees already paid for student {student.admission_number}, session {session.name}, term {term}")
            return JsonResponse({'success': False, 'error': 'Fees already paid, access is granted'}, status=400)

    try:
        access_request, created = ResultAccessRequest.objects.get_or_create(
            student=student,
            session=session,
            term=term,
            defaults={'status': 'Pending', 'handled_by': None}
        )
        if not created and access_request.status == 'Approved':
            logger.info(f"Access already approved for student {student.admission_number}, session {session.name}, term {term}")
            return JsonResponse({'success': False, 'error': 'Access already approved'}, status=400)
        elif not created:
            access_request.status = 'Pending'
            access_request.handled_by = None
            access_request.updated_at = timezone.now()
            access_request.save()
            logger.info(f"Updated access request to Pending for student {student.admission_number}, session {session.name}, term {term}")
        else:
            logger.info(f"Created new access request for student {student.admission_number}, session {session.name}, term {term}")

        messages.success(request, f"Access request for {student.full_name} submitted successfully.")
        return JsonResponse({'success': True})
    except Exception as e:
        logger.error(f"Error creating access request for student {student.admission_number}: {e}")
        return JsonResponse({'success': False, 'error': 'Failed to submit request'}, status=500)
    
@login_required
@admin_required
def admin_handle_result_access_request(request):
    if request.method != 'POST':
        logger.warning(f"Invalid request method for admin_handle_result_access_request: {request.method}")
        return JsonResponse({'success': False, 'error': 'Invalid request method'})

    request_id = request.POST.get('request_id')
    action = request.POST.get('action')

    try:
        if not request_id or not action:
            logger.error(f"Missing request_id or action: request_id={request_id}, action={action}")
            return JsonResponse({'success': False, 'error': 'Request ID and action are required'})

        access_request = ResultAccessRequest.objects.get(id=request_id)
        student = access_request.student
        session = access_request.session
        term = access_request.term

        if action not in ['grant', 'revoke']:
            logger.error(f"Invalid action: {action}")
            return JsonResponse({'success': False, 'error': 'Invalid action specified'})

        status = 'Approved' if action == 'grant' else 'Denied'
        notification_message = (
            f"Your result access request for {session.name} Term {access_request.get_term_display()} has been "
            f"{'approved' if action == 'grant' else 'denied'}."
        )

        with transaction.atomic():
            access_request.status = status
            access_request.handled_by = request.user
            access_request.updated_at = timezone.now()
            access_request.save()

        try:
            Notification.objects.create(
                user=student.user,
                message=notification_message
            )
            logger.debug(f"Notification sent to {student.full_name}: {notification_message}")
        except Exception as e:
            logger.warning(f"Failed to create notification for {student.full_name}: {str(e)}")

        logger.info(
            f"Result access {action}ed for {student.full_name}, session {session.name}, term {term} "
            f"by {request.user.username}"
        )
        return JsonResponse({'success': True, 'status': status})

    except ResultAccessRequest.DoesNotExist:
        logger.error(f"ResultAccessRequest with id {request_id} not found")
        return JsonResponse({'success': False, 'error': 'Request not found'})
    except Exception as e:
        logger.error(f"Unexpected error in admin_handle_result_access_request: {str(e)}")
        return JsonResponse({'success': False, 'error': 'An unexpected error occurred. Please try again or contact support'})

@login_required
@admin_required
def admin_manage_result_access_requests(request):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    current_session, current_term = get_current_session_term()
    selected_term = request.GET.get('term', current_term)

    class_filter = request.GET.get('class_filter', '')
    name_filter = request.GET.get('name_filter', '')
    status_filter = request.GET.get('status_filter', '')
    session_filter = request.GET.get('session_filter', '')
    term_filter = request.GET.get('term_filter', '')

    requests = ResultAccessRequest.objects.select_related('student', 'session').order_by('-requested_at')

    if class_filter:
        requests = requests.filter(student__current_class__level=class_filter)
    if name_filter:
        requests = requests.filter(student__full_name__icontains=name_filter)
    if status_filter:
        requests = requests.filter(status=status_filter)
    if session_filter:
        requests = requests.filter(session__id=session_filter)
    if term_filter:
        requests = requests.filter(term=term_filter)

    if is_ajax:
        try:
            requests_data = [{
                'id': req.id,
                'student_full_name': req.student.full_name or 'Unknown',
                'class_level': req.student.current_class.level if req.student.current_class else 'N/A',
                'session_name': req.session.name or 'Unknown',
                'term_display': req.get_term_display() if hasattr(req, 'get_term_display') else req.term,
                'status': req.status or 'Unknown',
                'requested_at': req.requested_at.strftime('%B %d, %Y %H:%M') if req.requested_at else 'N/A'
            } for req in requests]
            return JsonResponse({'requests': requests_data})
        except Exception as e:
            return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)
    else:
        classes = ResultAccessRequest.objects.values_list('student__current_class__level', flat=True).distinct()
        sessions = Session.objects.all()
        terms = TERM_CHOICES

        context = {
            'classes': classes,
            'sessions': sessions,
            'current_session':current_session,
            'selected_term':selected_term,
            'terms': terms,
            'requests': requests,
            'class_filter': class_filter,
            'name_filter': name_filter,
            'status_filter': status_filter,
            'session_filter': session_filter,
            'term_filter': term_filter,
            'role': 'admin'
        }
        return render(request, 'account/admin/manage_result_access_requests.html', context)
    
@login_required
@admin_required
def admin_result_tracking(request):
    context = get_user_context(request)
    if not context:
        logger.error(f"Invalid user context for user {request.user.username}")
        return redirect('login')

    current_session, current_term = get_current_session_term()
    sessions = Session.objects.all().order_by('-start_year')
    terms = TERM_CHOICES

    session_id = request.GET.get('session', current_session.id)
    term = request.GET.get('term', current_term)
    class_filter = request.GET.get('class_filter', '')
    section_filter = request.GET.get('section_filter', '')

    try:
        selected_session = Session.objects.get(id=session_id)
    except Session.DoesNotExist:
        logger.error(f"Session with id {session_id} not found")
        messages.error(request, "Selected session not found")
        selected_session = current_session
        session_id = current_session.id

    if term not in [t[0] for t in TERM_CHOICES]:
        logger.warning(f"Invalid term {term} selected")
        messages.error(request, "Invalid term selected")
        term = current_term

    sections = ClassSection.objects.filter(
        session=selected_session,
        is_active=True,
        **({'school_class__level': class_filter} if class_filter else {}),
        **({'suffix': section_filter} if section_filter else {})
    ).select_related('school_class').order_by('school_class__level_order', 'suffix')

    result_stats = []
    for section in sections:
        students = Student.objects.filter(
            current_section=section,
            is_active=True
        )
        student_count = students.count()

        # Get assigned subjects for all students in the section
        student_subjects = StudentSubject.objects.filter(
            student__in=students,
            session=selected_session,
            term=term,
            subject__is_active=True
        ).select_related('subject')
        subject_ids = student_subjects.values_list('subject__id', flat=True).distinct()

        # Fallback to Result subjects if StudentSubject is empty
        if not subject_ids:
            result_subjects = Result.objects.filter(
                student__in=students,
                session=selected_session,
                term=term,
                subject__is_active=True
            ).values_list('subject__id', flat=True).distinct()
            subject_ids = list(result_subjects)
            logger.warning(
                f"No StudentSubject records for section {section} in {selected_session.name}, term {term}. "
                f"Fallback to Result subjects: {subject_ids}"
            )

        # Fetch all results for the section
        results = Result.objects.filter(
            student__in=students,
            session=selected_session,
            term=term,
            subject__id__in=subject_ids
        ).select_related('student', 'subject', 'uploaded_by')

        # Count complete students
        complete_students = 0
        student_subject_counts = {
            ss['student__admission_number']: ss['count']
            for ss in student_subjects.values('student__admission_number').annotate(count=Count('subject'))
        }
        student_result_counts = {
            r['student__admission_number']: r['count']
            for r in results.filter(total_score__gt=0).values('student__admission_number').annotate(count=Count('subject'))
        }

        for student in students:
            expected_results = student_subject_counts.get(student.admission_number, 0)
            actual_results = student_result_counts.get(student.admission_number, 0)
            # Use Result subjects as fallback if no StudentSubject records
            if expected_results == 0:
                student_results = results.filter(student=student)
                expected_results = student_results.values('subject__id').distinct().count()
            if expected_results > 0 and actual_results == expected_results:
                complete_students += 1

        upload_percentage = (complete_students / student_count * 100) if student_count > 0 else 0

        teachers = section.teachers.filter(is_active=True)

        # Calculate top students
        student_averages = []
        for student in students:
            student_results = results.filter(student=student, total_score__gt=0)
            if student_results.exists():
                avg_score = student_results.aggregate(Avg('total_score'))['total_score__avg']
                student_averages.append({
                    'student': student,
                    'avg_score': avg_score
                })

        top_students = sorted(student_averages, key=lambda x: x['avg_score'], reverse=True)[:3]

        result_stats.append({
            'section': section,
            'student_count': student_count,
            'complete_students': complete_students,
            'upload_percentage': round(upload_percentage, 2),
            'teachers': teachers,
            'top_students': top_students
        })

    paginator = Paginator(result_stats, 10)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except:
        page_obj = paginator.page(1)
        page_number = 1

    query_params = {
        'session': session_id,
        'term': term,
        'class_filter': class_filter,
        'section_filter': section_filter,
        'page': page_number
    }
    query_string = urlencode({k: v for k, v in query_params.items() if v})

    context.update({
        'current_session': current_session,
        'selected_session': selected_session,
        'current_term': current_term,
        'selected_term': term,
        'sessions': sessions,
        'terms': terms,
        'classes': SchoolClass.objects.values_list('level', flat=True).distinct().order_by('level'),
        'sections': ClassSection.objects.filter(
            session=selected_session,
            is_active=True
        ).values_list('suffix', flat=True).distinct().order_by('suffix'),
        'class_filter': class_filter,
        'section_filter': section_filter,
        'result_stats': page_obj.object_list,
        'page_obj': page_obj,
        'query_string': query_string
    })

    logger.debug(f"Rendering admin_result_tracking for {request.user.username}")
    return render(request, 'account/admin/admin_result_tracking.html', context)

@login_required
@admin_required
def view_class_results(request, section_id, session_id, term):
    context = get_user_context(request)
    if not context:
        logger.error(f"Invalid user context for user {request.user.username}")
        return redirect('login')

    try:
        section = ClassSection.objects.get(id=section_id, is_active=True)
        session = Session.objects.get(id=session_id)
    except (ClassSection.DoesNotExist, Session.DoesNotExist):
        logger.error(f"Invalid section {section_id} or session {session_id}")
        messages.error(request, "Invalid class section or session")
        return redirect('admin_result_tracking')

    if term not in [t[0] for t in TERM_CHOICES]:
        logger.warning(f"Invalid term {term} selected")
        messages.error(request, "Invalid term selected")
        return redirect('admin_result_tracking')

    
    update_class_positions(section, session, term)
    first_student = Student.objects.filter(current_section=section).first()
    if first_student:
        update_subject_positions(first_student, session, term)

    students = Student.objects.filter(
        current_section=section,
        is_active=True
    ).order_by('surname', 'first_name', 'middle_name')

    all_subjects = Subject.objects.filter(
        school_class=section.school_class,
        is_active=True
    ).order_by('id')

    detailed_student_results = []
    for student in students:
        student_subjects = StudentSubject.objects.filter(
            student=student,
            session=session,
            term=term,
            subject__is_active=True
        ).select_related('subject')
        student_subject_ids = list(student_subjects.values_list('subject__id', flat=True))
        
        if not student_subject_ids:
            result_subjects = Result.objects.filter(
                student=student,
                session=session,
                term=term,
                subject__is_active=True
            ).values_list('subject__id', flat=True).distinct()
            student_subject_ids = list(result_subjects)
            logger.warning(
                f"No StudentSubject records for {student.full_name} in {session.name}, term {term}. "
                f"Fallback to Result subjects: {student_subject_ids}"
            )
        
        student_results = Result.objects.filter(
            student=student,
            session=session,
            term=term,
            subject__id__in=student_subject_ids
        ).select_related('subject')

        results_dict = {}
        total_score = 0
        subjects_count = len(student_subject_ids)
        has_complete_results = True

        for subject in all_subjects:
            result = student_results.filter(subject=subject).first()
            is_assigned = subject.id in student_subject_ids
            is_complete = result and result.total_score > 0

            results_dict[subject.id] = {
                'result_obj': result,
                'is_complete': is_complete,
                'is_assigned': is_assigned
            }

            if is_assigned and is_complete:
                total_score += result.total_score
            elif is_assigned and not is_complete:
                has_complete_results = False
        
        average_score = round(total_score / subjects_count, 2) if subjects_count > 0 and has_complete_results else 0
        class_position = student_results.first().class_position if student_results.exists() and has_complete_results else None

        student_data = {
            'student': student,
            'results': results_dict,
            'total_score': total_score,
            'subjects_count': subjects_count,
            'has_complete_results': has_complete_results,
            'average_score': average_score,
            'class_position': class_position,
            'assigned_subject_ids': student_subject_ids,
            'remarks': student_results.first().remarks if student_results.exists() else ''
        }
        detailed_student_results.append(student_data)

    
    def get_position_rank(position):
        if not position:
            return float('inf')  
        
        try:
            return int(position[:-2]) if position[:-2].isdigit() else float('inf')
        except:
            return float('inf')

    detailed_student_results.sort(key=lambda x: (-x['average_score'], get_position_rank(x['class_position'])))

    class_averages = {}
    for subject in all_subjects:
        subject_results = Result.objects.filter(
            student__in=students,
            session=session,
            term=term,
            subject=subject,
            total_score__gt=0
        )
        count = subject_results.count()
        class_averages[subject.id] = {
            'average': sum(r.total_score for r in subject_results) / count if count > 0 else 0,
            'count': count
        }

    complete_students = [s for s in detailed_student_results if s['has_complete_results']]
    class_average_score = (
        sum(s['average_score'] for s in complete_students) / len(complete_students)
        if complete_students else 0
    )
    
    paginator = Paginator(detailed_student_results, 10)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except:
        page_obj = paginator.page(1)

    context.update({
        'section': section,
        'session': session,
        'term': term,
        'term_display': dict(TERM_CHOICES).get(term, term),
        'subjects': all_subjects,
        'student_results': page_obj,
        'page_obj': page_obj,
        'class_averages': class_averages,
        'is_nursery': section.school_class.section == 'Nursery',
        'is_primary': section.school_class.section == 'Primary',
        'total_students': students.count(),
        'students_with_complete_results': len(complete_students),
        'class_average_score': class_average_score,
    })

    logger.debug(f"Rendering view_class_results for section {section}, session {session.name}, term {term}")
    return render(request, 'account/admin/view_class_results.html', context)

@login_required
@admin_required
def admin_manage_subjects(request):
    context = get_user_context(request)
    if not context:
        return redirect('login')

    classes = SchoolClass.objects.all().order_by('level_order')

    if request.method == 'POST':
        try:
            with transaction.atomic():
                action = request.POST.get('action')
                
                if action == 'edit':
                    subject_id = request.POST.get('subject_id')
                    subject = Subject.objects.get(id=subject_id)
                    subject.name = request.POST.get('name')
                    subject.section = request.POST.get('section')
                    subject.compulsory = request.POST.get('compulsory') == 'on'
                    
                    if not subject.name or not subject.section:
                        raise ValidationError('Subject name and section are required')
                    
                    class_ids = request.POST.get('classes', '').split(',')
                    if not class_ids or class_ids == ['']:
                        raise ValidationError('At least one class must be selected')
                    
                    subject.school_class.clear()
                    for class_id in class_ids:
                        if class_id:  
                            school_class = SchoolClass.objects.get(id=class_id)
                            subject.school_class.add(school_class)
                    
                    subject.save()
                    logger.info(f"Admin {request.user.username} updated subject {subject.name}")
                    return JsonResponse({
                        'success': True,
                        'message': f'Subject {subject.name} updated successfully'
                    })
                
                elif action == 'toggle_status':
                    subject_id = request.POST.get('subject_id')
                    subject = Subject.objects.get(id=subject_id)
                    subject.is_active = not subject.is_active
                    subject.save()
                    status = 'activated' if subject.is_active else 'deactivated'
                    logger.info(f"Admin {request.user.username} {status} subject {subject.name}")
                    return JsonResponse({
                        'success': True,
                        'message': f'Subject {status} successfully'
                    })
                
                else:  
                    name = request.POST.get('name')
                    section = request.POST.get('section')
                    compulsory = request.POST.get('compulsory') == 'on'
                    class_ids = request.POST.get('classes', '').split(',')
                    
                    if not name or not section:
                        raise ValidationError('Subject name and section are required')
                    if not class_ids or class_ids == ['']:
                        raise ValidationError('At least one class must be selected')
                    
                    if Subject.objects.filter(name=name, section=section).exists():
                        raise ValidationError('A subject with this name and section already exists')
                    
                    subject = Subject.objects.create(
                        name=name,
                        section=section,
                        compulsory=compulsory,
                        is_active=True
                    )
                    
                    for class_id in class_ids:
                        if class_id:  
                            school_class = SchoolClass.objects.get(id=class_id)
                            subject.school_class.add(school_class)
                    
                    logger.info(f"Admin {request.user.username} created subject {name}")
                    return JsonResponse({
                        'success': True,
                        'message': f'Subject {name} created successfully'
                    })
                    
        except Subject.DoesNotExist:
            logger.error("Subject not found")
            return JsonResponse({'success': False, 'error': 'Subject not found'}, status=404)
        except SchoolClass.DoesNotExist:
            logger.error("Invalid class selected")
            return JsonResponse({'success': False, 'error': 'Invalid class selected'}, status=400)
        except ValidationError as e:
            logger.error(f"Validation error: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
        except Exception as e:
            logger.error(f"Unexpected error in admin_manage_subjects: {str(e)}")
            return JsonResponse({'success': False, 'error': f'An unexpected error occurred: {str(e)}'}, status=500)

    subjects = Subject.objects.all().prefetch_related('school_class')
    class_filter = request.GET.get('class_id', '')
    section_filter = request.GET.get('section', '')
    subject_filter = request.GET.get('name', '')

    if class_filter:
        subjects = subjects.filter(school_class__id=class_filter)
    if section_filter:
        subjects = subjects.filter(section=section_filter)
    if subject_filter:
        subjects = subjects.filter(name__icontains=subject_filter)

    context.update({
        'subjects': subjects,
        'classes': classes,
        'class_filter': class_filter,
        'section_filter': section_filter,
        'subject_filter': subject_filter,
    })
    return render(request, 'account/admin/admin_manage_subjects.html', context)

@login_required
@admin_required
def filter_subjects(request):
    try:
        class_id = request.GET.get('class_id')
        section = request.GET.get('section')
        name = request.GET.get('name')

        subjects = Subject.objects.all().prefetch_related('school_class')

        if class_id:
            subjects = subjects.filter(school_class__id=class_id)
        if section:
            subjects = subjects.filter(section=section)
        if name:
            subjects = subjects.filter(name__icontains=name)

        data = {
            'subjects': [
                {
                    'id': s.id,
                    'name': s.name,
                    'section': s.section,
                    'compulsory': s.compulsory,
                    'is_active': s.is_active,
                    'classes': [c.level for c in s.school_class.all()]
                }
                for s in subjects
            ]
        }
        return JsonResponse(data)
    except Exception as e:
        logger.error(f"Error in filter_subjects: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@admin_required
def get_subject(request):
    try:
        subject_id = request.GET.get('subject_id')
        subject = Subject.objects.get(id=subject_id)
        data = {
            'id': subject.id,
            'name': subject.name,
            'section': subject.section,
            'compulsory': subject.compulsory,
            'classes': [str(c.id) for c in subject.school_class.all()]
        }
        return JsonResponse(data)
    except Subject.DoesNotExist:
        logger.error(f"Subject with id {subject_id} not found")
        return JsonResponse({'error': 'Subject not found'}, status=404)
    except Exception as e:
        logger.error(f"Error in get_subject: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
    
@login_required
@admin_required
def admin_statistics(request):
    context = get_user_context(request)
    if not context:
        return redirect('login')

    
    current_session, _ = get_current_session_term()
    if not current_session:
        context.update({
            'error': 'No active session found.',
            'current_session': None,
            'session_stats': {},
            'historical_data': [],
        })
        return render(request, 'account/admin/admin_statistics.html', context)

    
    selected_session = current_session

    
    session_stats = {
        'total_students': Student.objects.filter(
            enrollment_year__lte=selected_session.end_year,
            is_active=True
        ).count(),
        'total_teachers': Teacher.objects.filter(is_active=True).count(),
        'students_by_class': {},
        'students_by_gender': {
            'M': Student.objects.filter(
                gender='M',
                enrollment_year__lte=selected_session.end_year,
                is_active=True
            ).count(),
            'F': Student.objects.filter(
                gender='F',
                enrollment_year__lte=selected_session.end_year,
                is_active=True
            ).count(),
        },
        'teachers_by_gender': {
            'M': Teacher.objects.filter(gender='M', is_active=True).count(),
            'F': Teacher.objects.filter(gender='F', is_active=True).count(),
        }
    }

    for class_level in SchoolClass.objects.all().order_by('level_order'):
        session_stats['students_by_class'][class_level.level] = Student.objects.filter(
            current_class=class_level,
            enrollment_year__lte=selected_session.end_year,
            is_active=True
        ).count()

    all_sessions = Session.objects.filter(end_year__lte=selected_session.end_year).order_by('-start_year')
    historical_data = []
    for session in all_sessions:
        student_count = Student.objects.filter(
            enrollment_year__lte=session.end_year,
            is_active=True
        ).count()
        teacher_count = Teacher.objects.filter(is_active=True).count()
        parents_count = Parent.objects.filter(is_active=True).count()
        historical_data.append({
            'session': session,
            'students': student_count,
            'teachers': teacher_count,
            'parent': parents_count,
            'ratio': f"{student_count}:{teacher_count}" if teacher_count > 0 else 'N/A'
        })

    parents_count = Parent.objects.count()

    paginator = Paginator(historical_data, 5)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context.update({
        'current_session': current_session,
        'selected_session': selected_session,
        'all_sessions': [current_session],
        'session_stats': session_stats,
        'historical_data': page_obj,
        'page_obj': page_obj,
    })

    return render(request, 'account/admin/admin_statistics.html', context)
    
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
@teacher_required
def generate_student_token(request):
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        admission_number = request.POST.get('admission_number')
        try:
            student = Student.objects.get(admission_number=admission_number)
            teacher = request.user.teacher
            if student.current_section and teacher in student.current_section.teachers.all():
                
                if student.user:
                    from django.contrib.sessions.models import Session
                    from django.utils import timezone
                    
                    
                    sessions = Session.objects.filter(
                        expire_date__gte=timezone.now()
                    )
                    for session in sessions:
                        session_data = session.get_decoded()
                        if str(student.user.id) == str(session_data.get('_auth_user_id')):
                            session.delete()
                
                new_token = student.regenerate_token()
                logger.info(f"New token generated for student {admission_number} by teacher {teacher}")
                
                if student.user:
                    Notification.objects.create(
                        user=student.user,
                        message=f"Your access token has been updated. Please log in again with the new token."
                    )
                
                return JsonResponse({
                    'success': True,
                    'message': 'New token generated successfully. Student session has been terminated.',
                    'token': new_token
                })
            else:
                logger.warning(f"Unauthorized token generation attempt for {admission_number} by {teacher}")
                return JsonResponse({
                    'success': False,
                    'message': 'You are not authorized to generate a token for this student'
                }, status=403)
        except Student.DoesNotExist:
            logger.error(f"Student with admission_number {admission_number} not found")
            return JsonResponse({
                'success': False,
                'message': 'Student not found'
            }, status=404)
        except Exception as e:
            logger.error(f"Error generating token for {admission_number}: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': f'Error generating token: {str(e)}'
            }, status=500)
    return JsonResponse({
        'success': False,
        'message': 'Invalid request'
    }, status=400)

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

def parent_payments(request):
    try:
        parent = request.user.parent.get()
    except Parent.DoesNotExist:
        messages.error(request, "Parent profile not found. Please contact support.")
        return redirect('dashboard')
    except Parent.MultipleObjectsReturned:
        messages.error(request, "Multiple parent profiles detected. Please contact support.")
        return redirect('dashboard')

    current_year = datetime.now().year
    active_sessions = Session.objects.filter(is_active=True).order_by('-start_year')
    past_sessions = Session.objects.filter(start_year__lt=current_year).order_by('-start_year')
    term_choices = dict(TERM_CHOICES)
    current_session, current_term = get_current_session_term()

    active_payment_data = []
    for session in active_sessions:
        for term, term_name in term_choices.items():
            total_fees = parent.get_total_fees_for_term(session, term)
            payment_status = parent.get_payment_status_for_term(session, term)
            active_payment_data.append({
                'session': session,
                'term': term,
                'term_name': term_name,
                'total_fees': total_fees,
                'payment_status': payment_status['status'],
                'amount_paid': payment_status['amount_paid'],
                'amount_due': payment_status['amount_due'],
                'is_current': session == current_session and term == current_term,
            })

    past_payment_data = []
    for session in past_sessions:
        for term, term_name in term_choices.items():
            total_fees = parent.get_total_fees_for_term(session, term)
            payment_status = parent.get_payment_status_for_term(session, term)
            past_payment_data.append({
                'session': session,
                'term': term,
                'term_name': term_name,
                'total_fees': total_fees,
                'payment_status': payment_status['status'],
                'amount_paid': payment_status['amount_paid'],
                'amount_due': payment_status['amount_due'],
                'is_current': False,
            })

    context = {
        'parent': parent,
        'active_payment_data': active_payment_data,
        'past_payment_data': past_payment_data,
        'current_session': current_session,
        'current_term': current_term,
    }
    return render(request, 'account/parent/parent_payments.html', context)

def parent_payment_detail(request, session_id, term):
    try:
        parent = request.user.parent.get()  # Get the single Parent instance
    except Parent.DoesNotExist:
        messages.error(request, "Parent profile not found. Please contact support.")
        return redirect('dashboard')
    except Parent.MultipleObjectsReturned:
        messages.error(request, "Multiple parent profiles detected. Please contact support.")
        return redirect('dashboard')

    session = get_object_or_404(Session, id=session_id)
    
    if term not in dict(TERM_CHOICES):
        raise Http404("Invalid term")

    total_fees = parent.get_total_fees_for_term(session, term)
    payment_status = parent.get_payment_status_for_term(session, term)

    student_fees = []
    for student in parent.students.filter(is_active=True):
        if student.current_class and student.current_class.section:
            section = student.current_class.section
            fee_section = (
                'Creche' if section == 'Nursery' and student.current_class.level == 'Creche'
                else 'Nursery_Primary' if section in ['Nursery', 'Primary']
                else section
            )
            fee = FeeStructure.objects.filter(
                session=session,
                term=term,
                section=fee_section
            ).first()
            student_fees.append({
                'student': student,
                'class_level': student.current_class.level if student.current_class else 'N/A',
                'fee_amount': fee.amount if fee else 0,
            })

    payments = Payment.objects.filter(
        parent=parent,
        session=session,
        term=term
    ).order_by('-created_at')

    context = {
        'parent': parent,
        'session': session,
        'term': term,
        'term_name': dict(TERM_CHOICES)[term],
        'total_fees': total_fees,
        'payment_status': payment_status,
        'student_fees': student_fees,
        'payments': payments,
    }
    return render(request, 'account/parent/parent_payment_detail.html', context)

@csrf_exempt
def payment_callback(request):
    if request.method == 'POST':
        transaction_id = request.POST.get('transaction_id')
        try:
            payment = Payment.objects.get(transaction_id=transaction_id)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            response, status = loop.run_until_complete(async_post_request(
                'https://api-checkout.cinetpay.com/v2/payment/check',
                {
                    'apikey': settings.CINETPAY_API_KEY,
                    'site_id': settings.CINETPAY_SITE_ID,
                    'transaction_id': transaction_id
                }
            ))
            loop.close()

            if status == 200 and response.get('code') == '00':
                payment.status = 'Completed'
                payment.save()
                Notification.objects.create(
                    user=payment.student.user,
                    message=f"Payment of {payment.amount} XOF for {payment.session.name} Term {payment.get_term_display()} was successful."
                )
            else:
                payment.status = 'Failed'
                payment.save()
        except Payment.DoesNotExist:
            logger.error(f"Payment with transaction_id {transaction_id} not found")
        except Exception as e:
            logger.error(f"Error in payment callback: {str(e)}")
    return HttpResponse(status=200)

@login_required
@parent_required
def parent_view_children(request):
    context = get_user_context(request)
    parent = context.get('parent')
    if not parent:
        logger.error(f"No parent instance for user {request.user.username}")
        messages.error(request, "Parent account not found.")
        return redirect('dashboard')

    try:
        children = parent.students.filter(is_active=True).select_related('current_class', 'current_section')
        children_count = children.count()
    except Exception as e:
        logger.error(f"Error fetching children for parent {parent.phone_number}: {str(e)}")
        messages.error(request, "An error occurred while fetching your children.")
        children = []
        children_count = 0

    context.update({
        'parent': parent,
        'children': children,
        'children_count': children_count,
    })

    return render(request, 'account/parent/view_children.html', context)

@login_required
@parent_required
def parent_view_child_grades(request, admission_number):
    try:
        parent = Parent.objects.get(user=request.user)
    except Parent.DoesNotExist:
        logger.error(f"No Parent instance found for user {request.user.username}")
        messages.error(request, "Parent account not found. Please contact support.")
        return redirect('parent_view_children')
    except Parent.MultipleObjectsReturned:
        logger.error(f"Multiple Parent instances found for user {request.user.username}")
        messages.error(request, "Configuration error: Multiple parent accounts detected. Contact support.")
        return redirect('parent_view_children')

    try:
        student = parent.students.get(admission_number=admission_number, is_active=True)
    except Student.DoesNotExist:
        logger.error(f"Student with admission_number {admission_number} not found for parent {parent.phone_number}")
        messages.error(request, "Student not found or not associated with your account.")
        return redirect('parent_view_children')

    current_session, current_term = get_current_session_term()
    current_term_display = dict(TERM_CHOICES).get(current_term, 'N/A')

    subject_ids = StudentSubject.objects.filter(
        student=student,
        session=current_session,
        term=current_term
    ).values_list('subject_id', flat=True)

    if not subject_ids:
        subject_ids = Result.objects.filter(
            student=student,
            session=current_session,
            term=current_term
        ).values_list('subject__id', flat=True)
        if subject_ids:
            logger.warning(f"No StudentSubject records for student {student.admission_number}, using Result subjects: {list(subject_ids)}")

    try:
        payment_status = parent.get_payment_status_for_term(current_session, current_term)
        fees_paid = payment_status['status'] == 'Completed' and payment_status['amount_due'] <= 0
    except Exception as e:
        logger.error(f"Error fetching payment status for parent {parent.phone_number}: {e}")
        fees_paid = False
        payment_status = {'status': 'Pending', 'amount_paid': 0, 'amount_due': 0}

    access_request = ResultAccessRequest.objects.filter(
        student=student,
        session=current_session,
        term=current_term
    ).first()
    access_approved = access_request and access_request.status == 'Approved'

    results = []
    average_score = 0
    average_grade_point = None
    class_position_marks = None
    total_in_section = None

    if fees_paid or access_approved:
        try:
            results = Result.objects.filter(
                student=student,
                session=current_session,
                term=current_term,
                subject_id__in=subject_ids
            ).select_related('subject').order_by('subject__id')

            if results.exists():
                total_scores = [r.total_score for r in results if r.total_score > 0]
                average_score = sum(total_scores) / len(total_scores) if total_scores else 0

                if student.current_class and student.current_class.section not in ['Nursery', 'Primary']:
                    grade_points = [r.grade_point for r in results if r.grade_point is not None]
                    average_grade_point = sum(grade_points) / len(grade_points) if grade_points else 0

                if student.current_section:
                    section_results = Result.objects.filter(
                        session=current_session,
                        term=current_term,
                        student__current_section=student.current_section
                    ).values('student_id').annotate(total=Sum('total_score')).order_by('-total')

                    total_in_section = section_results.count()
                    for idx, res in enumerate(section_results, 1):
                        if res['student_id'] == student.admission_number:  # Use admission_number as PK
                            class_position_marks = f"{idx}{get_ordinal_suffix(idx)}"
                            break
            else:
                logger.info(f"No results found for student {student.admission_number} in session {current_session.name}, term {current_term}")
        except Exception as e:
            logger.error(f"Error fetching results for student {student.admission_number}: {e}")
            messages.error(request, "An error occurred while fetching results. Please try again later.")

    overall_remark = results[0].remarks if results and results[0].remarks else ''
    result_upload_date = results[0].upload_date if results and results[0].upload_date else None

    # Past results
    try:
        past_results = Result.objects.filter(
            student=student,
            session__start_year__lt=current_session.start_year
        ).select_related('session', 'subject').order_by('-session__start_year', 'term', 'subject__name')

        past_results_grouped = []
        for (session_id, term), group in groupby(
            sorted(
                [(r.session_id, r.term, r) for r in past_results],
                key=lambda x: (x[0], x[1])
            ),
            key=lambda x: (x[0], x[1])
        ):
            group_results = [item[2] for item in group]
            session = group_results[0].session
            term_display = dict(TERM_CHOICES).get(term, term)

            past_payment_status = parent.get_payment_status_for_term(session, term)
            past_fees_paid = past_payment_status['status'] == 'Completed' and past_payment_status['amount_due'] <= 0

            past_access_request = ResultAccessRequest.objects.filter(
                student=student,
                session=session,
                term=term,
                status='Approved'
            ).first()
            has_access = past_fees_paid or past_access_request

            total_scores = [r.total_score for r in group_results if r.total_score > 0]
            avg_score = sum(total_scores) / len(total_scores) if total_scores else 0

            avg_grade_point = None
            if student.current_class and student.current_class.section not in ['Nursery', 'Primary']:
                grade_points = [r.grade_point for r in group_results if r.grade_point is not None]
                avg_grade_point = sum(grade_points) / len(grade_points) if grade_points else 0

            class_pos = None
            total_in_sec = None
            if student.current_section:
                past_section_results = Result.objects.filter(
                    session=session,
                    term=term,
                    student__current_section=student.current_section
                ).values('student_id').annotate(total=Sum('total_score')).order_by('-total')
                total_in_sec = past_section_results.count()
                for idx, res in enumerate(past_section_results, 1):
                    if res['student_id'] == student.admission_number:
                        class_pos = f"{idx}{get_ordinal_suffix(idx)}"
                        break

            past_results_grouped.append({
                'session': session,
                'term': term,
                'term_display': term_display,
                'results': group_results,
                'fees_paid': past_fees_paid,
                'has_access': has_access,
                'access_request': past_access_request,
                'average_score': avg_score,
                'average_grade_point': avg_grade_point,
                'class_position': class_pos,
                'total_in_section': total_in_sec,
            })
    except Exception as e:
        logger.error(f"Error fetching past results for student {student.admission_number}: {e}")
        past_results_grouped = []

    context = {
        'student': student,
        'current_session': current_session,
        'current_term': current_term,
        'current_term_display': current_term_display,
        'subject_ids': subject_ids,
        'fees_paid': fees_paid,
        'access_approved': access_approved,
        'access_request': access_request,
        'results': results,
        'is_nursery': student.current_class.section == 'Nursery' if student.current_class else False,
        'is_primary': student.current_class.section == 'Primary' if student.current_class else False,
        'average_score': average_score,
        'average_grade_point': average_grade_point,
        'class_position_marks': class_position_marks,
        'total_in_section': total_in_section,
        'next_term_start_date': get_next_term_start_date(current_session, current_term),
        'result_upload_date': result_upload_date,
        'overall_remark': overall_remark,
        'past_results_grouped': past_results_grouped,
    }

    logger.debug(f"Rendering parent_view_child_grades for student {student.admission_number} with context: {context}")
    return render(request, 'account/parent/child_grades.html', context)

@login_required
@parent_required
def parent_request_result_access(request, admission_number):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)

    try:
        parent = Parent.objects.get(user=request.user)
    except Parent.DoesNotExist:
        logger.error(f"No Parent instance found for user {request.user.username}")
        return JsonResponse({'success': False, 'error': 'Parent account not found'}, status=400)
    except Parent.MultipleObjectsReturned:
        logger.error(f"Multiple Parent instances found for user {request.user.username}")
        return JsonResponse({'success': False, 'error': 'Configuration error: Multiple parent accounts detected'}, status=400)

    try:
        student = parent.students.get(admission_number=admission_number, is_active=True)
    except Student.DoesNotExist:
        logger.error(f"Student with admission_number {admission_number} not found for parent {parent.phone_number}")
        return JsonResponse({'success': False, 'error': 'Student not found'}, status=400)

    session_id = request.POST.get('session_id')
    term = request.POST.get('term')

    try:
        session = Session.objects.get(id=session_id)
    except Session.DoesNotExist:
        logger.error(f"Session with id {session_id} not found")
        return JsonResponse({'success': False, 'error': 'Invalid session'}, status=400)

    if term not in dict(TERM_CHOICES):
        logger.error(f"Invalid term {term} for student {student.admission_number}")
        return JsonResponse({'success': False, 'error': 'Invalid term'}, status=400)

    payment_status = parent.get_payment_status_for_term(session, term)
    if payment_status['status'] == 'Completed' and payment_status['amount_due'] <= 0:
        logger.info(f"Fees already paid for student {student.admission_number}, session {session.name}, term {term}")
        return JsonResponse({'success': False, 'error': 'Fees already paid, access is granted'}, status=400)

    try:
        access_request, created = ResultAccessRequest.objects.get_or_create(
            student=student,
            session=session,
            term=term,
            defaults={'status': 'Pending', 'handled_by': None}
        )
        if not created and access_request.status == 'Approved':
            logger.info(f"Access already approved for student {student.admission_number}, session {session.name}, term {term}")
            return JsonResponse({'success': False, 'error': 'Access already approved'}, status=400)
        elif not created:
            access_request.status = 'Pending'
            access_request.handled_by = None
            access_request.updated_at = timezone.now()
            access_request.save()
            logger.info(f"Updated access request to Pending for student {student.admission_number}, session {session.name}, term {term}")
        else:
            logger.info(f"Created new access request for student {student.admission_number}, session {session.name}, term {term}")

        messages.success(request, f"Access request for {student.full_name} submitted successfully.")
        return JsonResponse({'success': True})
    except Exception as e:
        logger.error(f"Error creating access request for student {student.admission_number}: {e}")
        return JsonResponse({'success': False, 'error': 'Failed to submit request'}, status=500)

@login_required
@parent_required
def parent_export_current_results_pdf(request, admission_number):
    try:
        parent = Parent.objects.get(user=request.user)
        student = parent.students.get(admission_number=admission_number, is_active=True)
    except Parent.DoesNotExist:
        messages.error(request, "Parent account not found.")
        return redirect('parent_view_children')
    except Student.DoesNotExist:
        messages.error(request, "Student not found.")
        return redirect('parent_view_children')

    current_session, current_term = get_current_session_term()
    is_nursery = student.current_class and student.current_class.section == 'Nursery'
    is_primary = student.current_class and student.current_class.section == 'Primary'

    student_subjects = StudentSubject.objects.filter(
        student=student,
        session=current_session,
        term=current_term
    ).select_related('subject')
    subject_ids = list(student_subjects.values_list('subject__id', flat=True))

    results = Result.objects.filter(
        student=student,
        session=current_session,
        term=current_term,
        subject__id__in=subject_ids
    ).select_related('subject').order_by('subject__name')

    pdf_buffer = generate_result_pdf(
        student,
        results,
        current_session,
        current_term,
        is_nursery=is_nursery,
        is_primary=is_primary
    )

    filename = f"Results_{student.full_name}_{current_session.name}_Term{current_term}.pdf"
    response = HttpResponse(pdf_buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

@login_required
@parent_required
def parent_export_past_results_pdf(request, admission_number, session_id, term):
    try:
        parent = Parent.objects.get(user=request.user)
        student = parent.students.get(admission_number=admission_number, is_active=True)
    except Parent.DoesNotExist:
        messages.error(request, "Parent account not found.")
        return redirect('parent_view_children')
    except Student.DoesNotExist:
        messages.error(request, "Student not found.")
        return redirect('parent_view_children')

    try:
        session = Session.objects.get(id=session_id)
    except Session.DoesNotExist:
        messages.error(request, 'Session not found')
        return redirect('parent_view_child_grades', admission_number=admission_number)

    is_nursery = student.current_class and student.current_class.section == 'Nursery'
    is_primary = student.current_class and student.current_class.section == 'Primary'

    student_subjects = StudentSubject.objects.filter(
        student=student,
        session=session,
        term=term
    ).select_related('subject')
    subject_ids = list(student_subjects.values_list('subject__id', flat=True))

    results = Result.objects.filter(
        student=student,
        session=session,
        term=term,
        subject__id__in=subject_ids
    ).select_related('subject').order_by('subject__name')

    pdf_buffer = generate_result_pdf(
        student,
        results,
        session,
        term,
        is_nursery=is_nursery,
        is_primary=is_primary
    )

    filename = f"Results_{student.full_name}_{session.name}_Term{term}.pdf"
    response = HttpResponse(pdf_buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

def handler400(request, exception):
    logger.error(f"Bad request: {exception}")
    return render(request, 'account/errors/400.html', status=400)

def handler403(request, exception):
    logger.error(f"Permission denied: {exception}")
    return render(request, 'account/errors/403.html', status=403)

def handler404(request, exception):
    logger.error(f"Page not found: {exception}")
    return render(request, 'account/errors/404.html', status=404)

def handler500(request):
    logger.error("Server error occurred")
    return render(request, 'account/errors/500.html', status=500)

def handle_template_does_not_exist(request, exception):
    logger.error(f"Template not found: {exception}")
    return render(request, 'account/errors/500.html', status=500)

@admin_required
def admin_create_payment(request):
    sessions = Session.objects.all()
    current_session, current_term = get_current_session_term()
    context = {
        'sessions': sessions,
        'current_session': current_session,
        'current_term': current_term,
        'term_choices': TERM_CHOICES,
        'role': 'admin'
    }

    if request.method == 'POST':
        logger.info('Received POST request: %s', request.POST)
        try:
            session_id = request.POST.get('session_id')
            term = request.POST.get('term')
            parent_id = request.POST.get('parent_id')
            amount = request.POST.get('amount')

            logger.debug('Input data: session_id=%s, term=%s, parent_id=%s, amount=%s',
                         session_id, term, parent_id, amount)

            if not session_id or not term or not parent_id or not amount:
                raise ValidationError("All fields (session, term, parent, amount) are required.")

            session = Session.objects.get(id=session_id)
            parent = Parent.objects.get(id=parent_id)
            try:
                amount = Decimal(amount.strip())
            except (ValueError, AttributeError):
                raise ValidationError("Invalid amount format.")

            if term not in dict(TERM_CHOICES):
                raise ValidationError("Invalid term selected.")

            students = Student.objects.filter(parent=parent, is_active=True).select_related('current_class')
            if not students.exists():
                raise ValidationError(f"No active students found for parent {parent.full_name or parent.phone_number}.")

            logger.debug('Students for parent %s: %s', parent.id, 
                         list(students.values('admission_number', 'first_name', 'surname', 'current_class__level')))

            total_fees = parent.get_total_fees_for_term(session, term)
            payment_status = parent.get_payment_status_for_term(session, term)
            amount_due = Decimal(payment_status['amount_due'])

            logger.debug('Payment validation: total_fees=%s, amount_due=%s, input_amount=%s',
                         total_fees, amount_due, amount)

            if total_fees == 0:
                raise ValidationError("No fees found for the selected students. Check FeeStructure configuration.")

            if amount <= 0:
                raise ValidationError("Payment amount must be greater than zero.")
            if amount > amount_due:
                raise ValidationError(f"Payment amount ({amount} XOF) exceeds amount due ({amount_due} XOF).")

            if amount == amount_due:
                for s in Session.objects.filter(start_year__lt=session.start_year):
                    status = parent.get_payment_status_for_term(s, term)
                    if status['amount_due'] > 0:
                        raise ValidationError(f"Cannot clear this term's balance. Outstanding bills exist for {s.name} Term {term}.")
                for t in [t[0] for t in TERM_CHOICES if t[0] < term]:
                    status = parent.get_payment_status_for_term(session, t)
                    if status['amount_due'] > 0:
                        raise ValidationError(f"Cannot clear this term's balance. Outstanding bills exist for {session.name} Term {t}.")

            # Create a new Payment record for each transaction
            payment = Payment.objects.create(
                parent=parent,
                session=session,
                term=term,
                amount=amount,
                status='Completed' if amount >= amount_due else 'Partial',
                transaction_id=str(uuid.uuid4())
            )
            payment.students.set(students)
            payment.save()

            logger.info('Payment recorded: payment_id=%s, amount=%s, parent=%s, transaction_id=%s, students=%s, created_at=%s', 
                        payment.id, amount, parent.full_name or parent.phone_number, payment.transaction_id, 
                        [s.admission_number for s in students], payment.created_at)

            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                updated_status = parent.get_payment_status_for_term(session, term)
                payments = Payment.objects.filter(parent=parent, session=session, term=term).order_by('-created_at')
                payment_history = [
                    {
                        'transaction_id': p.transaction_id or 'N/A',
                        'amount': float(p.amount),
                        'status': p.status or 'Unknown',
                        'datetime': p.created_at.strftime('%d %b %Y, %I:%M %p') if p.created_at else 'N/A'
                    } for p in payments
                ]
                return JsonResponse({
                    'success': True,
                    'message': f"Payment of {amount} XOF recorded for {parent.full_name or parent.phone_number}.",
                    'total_fees': float(total_fees),
                    'amount_paid': float(updated_status['amount_paid']),
                    'amount_due': float(updated_status['amount_due']),
                    'previous_payments': payment_history
                })

            messages.success(request, f"Payment of {amount} XOF recorded for {parent.full_name or parent.phone_number}.")
            return redirect('generate_payment_receipt', payment_id=payment.id)

        except (ValidationError, ValueError) as e:
            logger.error('Validation error: %s', str(e))
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
            messages.error(request, str(e))
            return render(request, 'account/admin/admin_create_payment.html', context)
        except Parent.DoesNotExist:
            logger.error('Parent not found: parent_id=%s', parent_id)
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'Parent not found.'}, status=404)
            messages.error(request, "Parent not found.")
            return render(request, 'account/admin/admin_create_payment.html', context)
        except Session.DoesNotExist:
            logger.error('Session not found: session_id=%s', session_id)
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'Session not found.'}, status=404)
            messages.error(request, "Session not found.")
            return render(request, 'account/admin/admin_create_payment.html', context)
        except Exception as e:
            logger.exception('Unexpected error in admin_create_payment: %s', str(e))
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                return JsonResponse({'success': False, 'error': f'An unexpected error occurred: {str(e)}'}, status=500)
            messages.error(request, f"An unexpected error occurred: {str(e)}")
            return render(request, 'account/admin/admin_create_payment.html', context)

    return render(request, 'account/admin/admin_create_payment.html', context)

@admin_required
def search_family_by_student_name(request):
    query = request.GET.get('query', '').strip()
    session_id = request.GET.get('session_id')
    term = request.GET.get('term')

    logger.info('Search request: query=%s, session_id=%s, term=%s', query, session_id, term)

    if not query or not session_id or not term:
        return JsonResponse({'error': 'Query, session, and term are required.'}, status=400)

    try:
        session = Session.objects.get(id=session_id)
        if term not in dict(TERM_CHOICES):
            return JsonResponse({'error': 'Invalid term.'}, status=400)

        # Split query into parts for flexible name matching
        query_parts = query.split()
        name_query = Q()
        if len(query_parts) > 1:
            # Try combinations of first_name, middle_name, surname
            for i in range(len(query_parts)):
                for j in range(i + 1, len(query_parts)):
                    name_query |= (
                        Q(first_name__icontains=query_parts[i], surname__icontains=query_parts[j]) |
                        Q(first_name__icontains=query_parts[j], surname__icontains=query_parts[i]) |
                        Q(first_name__icontains=query_parts[i], middle_name__icontains=query_parts[j]) |
                        Q(first_name__icontains=query_parts[j], middle_name__icontains=query_parts[i]) |
                        Q(middle_name__icontains=query_parts[i], surname__icontains=query_parts[j]) |
                        Q(middle_name__icontains=query_parts[j], surname__icontains=query_parts[i])
                    )
        else:
            # Single part: match any name field
            name_query = (
                Q(first_name__icontains=query) |
                Q(middle_name__icontains=query) |
                Q(surname__icontains=query)
            )

        logger.debug('Executing query: %s', str(name_query))
        student = Student.objects.filter(
            Q(admission_number__iexact=query) |
            Q(parent__phone_number__icontains=query) |
            name_query,
            is_active=True
        ).select_related('parent', 'current_class').first()

        if not student:
            logger.warning('No student found for query: %s', query)
            return JsonResponse({'error': 'No family found for the given search term.'}, status=404)

        parent = student.parent
        if not parent.is_active:
            logger.warning('Parent inactive for student: %s', student.admission_number)
            return JsonResponse({'error': 'Parent account is inactive.'}, status=404)

        family_students = Student.objects.filter(parent=parent, is_active=True).select_related('current_class').order_by('current_class__level_order')
        logger.debug('Found students: %s', list(family_students.values('admission_number', 'first_name', 'surname', 'current_class__level')))

        total_fees = parent.get_total_fees_for_term(session, term)
        payment_status = parent.get_payment_status_for_term(session, term)

        student_details = []
        for s in family_students:
            fee_structure = FeeStructure.objects.filter(
                session=session,
                term=term,
                section=(
                    'Creche' if s.current_class and s.current_class.section == 'Nursery' and s.current_class.level == 'Creche'
                    else 'Nursery_Primary' if s.current_class and s.current_class.section in ['Nursery', 'Primary']
                    else s.current_class.section if s.current_class else 'N/A'
                )
            ).first()
            student_details.append({
                'admission_number': s.admission_number,
                'full_name': s.full_name or 'Unknown',
                'class_level': s.current_class.level if s.current_class else 'N/A',
                'fee_amount': str(fee_structure.amount if fee_structure else 0)
            })

        payments = Payment.objects.filter(parent=parent, session=session, term=term).order_by('-created_at')
        payment_history = [
            {
                'transaction_id': p.transaction_id or 'N/A',
                'amount': float(p.amount),
                'status': p.status or 'Unknown',
                'datetime': p.created_at.strftime('%d %b %Y, %I:%M %p') if p.created_at else 'N/A'
            } for p in payments
        ]

        family_data = {
            'parent_id': parent.id,
            'parent_name': parent.full_name or parent.phone_number,
            'parent_phone': parent.phone_number,
            'students': student_details,
            'total_fees': float(total_fees),
            'amount_paid': float(payment_status['amount_paid']),
            'amount_due': float(payment_status['amount_due']),
            'previous_payments': payment_history
        }

        logger.debug('Returning family data: %s', family_data)
        return JsonResponse({'family': family_data})

    except Session.DoesNotExist:
        logger.error('Session not found: session_id=%s', session_id)
        return JsonResponse({'error': 'Session not found.'}, status=404)
    except Exception as e:
        logger.exception('Unexpected error in search_family_by_student_name: %s', str(e))
        return JsonResponse({'error': f'Unexpected error: {str(e)}'}, status=500)

@admin_required
def admin_payment_report(request):
    sessions = Session.objects.all()
    current_session, current_term = get_current_session_term()
    session_id = request.GET.get('session_id', current_session.id if current_session else '')
    term = request.GET.get('term', current_term if current_term else '1')

    try:
        session = Session.objects.get(id=session_id) if session_id else current_session
        if term not in dict(TERM_CHOICES):
            term = current_term or '1'
    except Session.DoesNotExist:
        session = current_session
        term = current_term or '1'

    parents = Parent.objects.filter(is_active=True).prefetch_related('students__current_class', 'payments')
    report_data = []
    for parent in parents:
        total_fees = parent.get_total_fees_for_term(session, term)
        payment_status = parent.get_payment_status_for_term(session, term)
        amount_paid = payment_status['amount_paid']
        percentage_paid = (amount_paid / total_fees * 100) if total_fees > 0 else 0
        students = parent.students.filter(is_active=True).select_related('current_class').order_by('current_class__level_order')
        student_list = [f"{s.full_name} - {s.current_class.level}" for s in students if s.current_class]
        report_data.append({
            'students': ', '.join(student_list) if student_list else 'No students',
            'parent_phone': parent.phone_number,
            'total_fees': float(total_fees),
            'amount_paid': float(amount_paid),
            'amount_due': float(payment_status['amount_due']),
            'percentage_paid': round(percentage_paid, 2)
        })

    report_data.sort(key=lambda x: x['amount_paid'], reverse=True)
    paginator = Paginator(report_data, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'sessions': sessions,
        'current_session': session,
        'current_term': term,
        'term_choices': TERM_CHOICES,
        'page_obj': page_obj,
        'report_data': page_obj.object_list,
        'role': 'admin'
    }

    return render(request, 'account/admin/admin_payment_report.html', context)

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
            'school_name': "Rehoboth International School of Excellence ",
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

@admin_required
def admin_fee_statistics(request):
    sessions = Session.objects.all()
    current_session, current_term = get_current_session_term()
    logger.debug('Admin Fee Statistics: current_session=%s, current_term=%s', 
                 current_session.name if current_session else None, current_term)
    session_id = request.GET.get('session_id', current_session.id if current_session else '')
    term = request.GET.get('term', current_term if current_term else '1')

    try:
        # Use pk instead of id to be generic
        session = Session.objects.get(pk=session_id) if session_id else current_session
        if term not in dict(TERM_CHOICES):
            term = current_term or '1'
    except Session.DoesNotExist:
        session = current_session
        term = current_term or '1'

    section_mappings = {
        'Creche': Q(current_class__section='Nursery', current_class__level='Creche'),
        'Nursery_Primary': Q(current_class__section__in=['Nursery', 'Primary']),
        'Junior': Q(current_class__section='Junior'),
        'Senior': Q(current_class__section='Senior'),
    }

    sections = ['Creche', 'Nursery_Primary', 'Junior', 'Senior']
    stats_data = []
    total_expected = Decimal(0)
    total_paid = Decimal(0)

    for section in sections:
        fee_structure = FeeStructure.objects.filter(
            session=session, term=term, section=section
        ).first()
        fee_amount = fee_structure.amount if fee_structure else Decimal(0)
        logger.debug('Section: %s, Fee Amount: %s', section, fee_amount)

        students = Student.objects.filter(
            is_active=True,
            current_class__isnull=False,
            enrollment_year__lte=session.end_year
        ).filter(section_mappings[section]).select_related('current_class').distinct()
        student_count = students.count()
        logger.debug('Section: %s, Student Count: %s, Students: %s', 
                     section, student_count, list(students.values('admission_number', 'current_class__level')))

        section_expected = fee_amount * student_count

        section_payments = Payment.objects.filter(
            session=session, term=term, students__admission_number__in=students.values('admission_number')
        ).select_related('parent').distinct()
        section_paid = Decimal(0)
        for payment in section_payments:
            payment_students = payment.students.filter(admission_number__in=students.values('admission_number')).count()
            if payment_students > 0:
                per_student_payment = min(payment.amount / payment_students, fee_amount)
                section_paid += per_student_payment * payment_students
        section_paid = min(section_paid, section_expected)
        logger.debug('Section: %s, Expected: %s, Paid: %s', section, section_expected, section_paid)

        percentage_paid = (section_paid / section_expected * 100) if section_expected > 0 else 0
        stats_data.append({
            'section': section,
            'expected': float(section_expected),
            'paid': float(section_paid),
            'outstanding': float(section_expected - section_paid),
            'percentage_paid': round(percentage_paid, 2),
            'student_count': student_count
        })

        total_expected += section_expected
        total_paid += section_paid

    total_outstanding = total_expected - total_paid
    total_percentage_paid = (total_paid / total_expected * 100) if total_expected > 0 else 0
    logger.debug('Totals: Expected=%s, Paid=%s, Outstanding=%s, Percentage=%s', 
                 total_expected, total_paid, total_outstanding, total_percentage_paid)

    context = {
        'sessions': sessions,
        'current_session': session,
        'current_term': term,
        'term_choices': TERM_CHOICES,
        'stats_data': stats_data,
        'total_expected': float(total_expected),
        'total_paid': float(total_paid),
        'total_outstanding': float(total_outstanding),
        'total_percentage_paid': round(total_percentage_paid, 2),
        'role': 'admin'
    }

    return render(request, 'account/admin/admin_fee_statistics.html', context)

@admin_required
def admin_daily_payment_report(request):
    sessions = Session.objects.all()
    current_session, current_term = get_current_session_term()
    logger.debug('Admin Daily Payment Report: current_session=%s, current_term=%s', 
                 current_session.name if current_session else None, current_term)
    date_str = request.GET.get('date', timezone.now().strftime('%Y-%m-%d'))
    
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = timezone.now().date()
        date_str = selected_date.strftime('%Y-%m-%d')

    payments = Payment.objects.filter(
        created_at__date=selected_date,
        session=current_session,
        term=current_term
    ).select_related('parent').prefetch_related('students__current_class').order_by('-created_at')
    
    report_data = []
    total_paid = Decimal(0)
    
    for payment in payments:
        students = payment.students.all()
        student_list = [f"{s.full_name} ({s.current_class.level})" for s in students if s.current_class]
        amount_due = payment.parent.get_payment_status_for_term(current_session, current_term)['amount_due']
        
        report_data.append({
            'parent_name': payment.parent.full_name or payment.parent.phone_number,
            'students': ', '.join(student_list) or 'No students',
            'amount_paid': float(payment.amount),
            'amount_due': float(amount_due),
            'transaction_id': payment.transaction_id,
            'time': payment.created_at.strftime('%I:%M %p')
        })
        total_paid += payment.amount
    
    logger.debug('Daily Payment Report: Date=%s, Payments=%s, Total Paid=%s', 
                 selected_date, len(payments), total_paid)

    context = {
        'sessions': sessions,
        'current_session': current_session,
        'current_term': current_term,
        'term_choices': TERM_CHOICES,
        'selected_date': date_str,
        'report_data': report_data,
        'total_paid': float(total_paid),
        'role': 'admin'
    }
    
    return render(request, 'account/admin/admin_daily_payment_report.html', context)
import uuid
import re

from datetime import date, datetime
from itertools import groupby
from urllib.parse import urlencode
from decimal import Decimal
from weasyprint import HTML

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.template.loader import render_to_string
from django.db.models import Prefetch
from django.http import HttpResponse, JsonResponse
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Avg, Q, Count, Sum
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.core import management
from django.core.exceptions import ObjectDoesNotExist

from accounts.decorators import group_required
from accounts.models import FeeStructure, PTADues, Refund, ResultAccessRequest, Student, StudentFeeOverride, Teacher, Result, Payment, SchoolClass, Subject, Notification, Session, ClassSection, TERM_CHOICES, StudentSubject, Parent

from .base import get_user_context, get_current_session_term, logger
from .teacher import update_class_positions, update_subject_positions

@login_required
@group_required('Secretary', 'Director')
def admin_student_management(request):
    context = get_user_context(request)
    if not context:
        return redirect('login')

    current_session, _ = get_current_session_term()
    students = Student.objects.all().select_related('current_class', 'current_section', 'parent')
    class_sections = ClassSection.objects.filter(session=current_session).select_related('school_class').order_by('school_class__level')
    form_data = {}
    form_errors = []

    if request.method == 'POST':
        try:
            with transaction.atomic():
                
                first_name = request.POST.get('first_name', '').strip()
                middle_name = request.POST.get('middle_name', '').strip()
                surname = request.POST.get('surname', '').strip()
                date_of_birth = request.POST.get('date_of_birth')
                nationality = request.POST.get('nationality', '').strip()
                address = request.POST.get('address', '').strip()
                parent_phone = request.POST.get('parent_phone', '').strip()
                parent_full_name = request.POST.get('parent_full_name', '').strip()
                gender = request.POST.get('gender')
                enrollment_year = request.POST.get('enrollment_year')
                class_id = request.POST.get('class')
                section_id = request.POST.get('section')
                photo = request.FILES.get('photo')
                selected_parent_id = request.POST.get('selected_parent_id')

                
                form_data = {
                    'first_name': first_name,
                    'middle_name': middle_name,
                    'surname': surname,
                    'date_of_birth': date_of_birth,
                    'nationality': nationality,
                    'address': address,
                    'parent_phone': parent_phone,
                    'parent_full_name': parent_full_name,
                    'gender': gender,
                    'enrollment_year': enrollment_year,
                    'class': class_id,
                    'section': section_id,
                }

                
                required_fields = [
                    ('first_name', 'First name is required.'),
                    ('surname', 'Surname is required.'),
                    ('date_of_birth', 'Date of birth is required.'),
                    ('nationality', 'Nationality is required.'),
                    ('address', 'Address is required.'),
                    ('parent_phone', 'Parent phone is required.'),
                    ('gender', 'Gender is required.'),
                    ('enrollment_year', 'Enrollment year is required.'),
                    ('class', 'Class is required.'),
                ]

                for field, error_msg in required_fields:
                    if not form_data.get(field):
                        raise ValidationError(error_msg)

                
                if not re.match(r'^\d{4}$', enrollment_year):
                    raise ValidationError('Enrollment year must be a four-digit number.')
                
                current_year = datetime.now().year
                if int(enrollment_year) > current_year:
                    raise ValidationError('Enrollment year cannot be in the future.')
                if int(enrollment_year) < 1900:
                    raise ValidationError('Enrollment year is too far in the past.')

                
                if not re.match(r'^\+?\d{8,15}$', parent_phone):
                    raise ValidationError('Invalid phone number format (minimum 8 digits).')
                
                if gender not in ['M', 'F']:
                    raise ValidationError('Invalid gender.')

                
                school_class = SchoolClass.objects.get(id=class_id)
                class_section = ClassSection.objects.get(id=section_id) if section_id else None

                
                parent = None
                parent_created = False  

                if selected_parent_id:
                    parent = Parent.objects.get(id=selected_parent_id)
                elif parent_phone:
                    parent, parent_created = Parent.objects.get_or_create(
                        phone_number=parent_phone,
                        defaults={
                            'full_name': parent_full_name or f"Parent of {first_name} {surname}",
                            'user': User.objects.create_user(
                                username=parent_phone,
                                password=parent_phone,
                                is_active=True
                            ) if not User.objects.filter(username=parent_phone).exists() else User.objects.get(username=parent_phone),
                        }
                    )
                    if not parent_created and parent_full_name:
                        parent.full_name = parent_full_name
                        parent.save()

                
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
                    is_active=True,
                    parent=parent
                )
                student.save()

                
                if parent_created:
                    Notification.objects.create(
                        user=parent.user,
                        message=f"Parent account created for {parent_phone}. Use phone number as password to login."
                    )
                    logger.info(f"Created parent account for {parent_phone} linked to student {student.full_name}")

                return JsonResponse({
                    'success': True,
                    'admission_number': student.admission_number,
                    'message': f'Student {student.full_name} registered with admission number {student.admission_number}.'
                })

        except IntegrityError as e:
            error_msg = 'Failed to register student due to a duplicate admission number or username. Try a different enrollment year or contact support.'
            logger.error(f"IntegrityError registering student: {str(e)}")
            return JsonResponse({'success': False, 'error': error_msg}, status=400)
            
        except (SchoolClass.DoesNotExist, ClassSection.DoesNotExist) as e:
            logger.error(f"Error registering student: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
            
        except ValidationError as e:
            logger.error(f"ValidationError registering student: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
            
        except Exception as e:
            error_msg = 'An unexpected error occurred. Please contact support.'
            logger.error(f"Unexpected error registering student: {str(e)}")
            return JsonResponse({'success': False, 'error': error_msg}, status=500)

    
    paginator = Paginator(students, 100)
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
    return render(request, 'account/admin/student_management.html', context)

@login_required
@group_required('Secretary', 'Director')
def search_parents(request):
    query = request.GET.get('query', '').strip()
    include_students = request.GET.get('include_students', 'false').lower() == 'true'
    
    if len(query) < 2:
        return JsonResponse({'parents': [], 'students': []})

    
    parents = Parent.objects.filter(
        Q(phone_number__icontains=query) |
        Q(full_name__icontains=query) |
        Q(full_name__istartswith=query)
    ).annotate(
        students_count=Count('students')
    ).order_by('-students_count', 'full_name')[:10]

    students = []
    if include_students:
        
        name_parts = query.split()
        q_objects = Q()
        
        for part in name_parts:
            q_objects |= (
                Q(admission_number__icontains=part) |
                Q(first_name__icontains=part) |
                Q(middle_name__icontains=part) |
                Q(surname__icontains=part) |
                Q(first_name__istartswith=part) |
                Q(surname__istartswith=part)
            )
        
        students = Student.objects.filter(q_objects).select_related('parent')[:10]

    parent_results = [{
        'id': parent.id,
        'full_name': parent.full_name,
        'phone_number': parent.phone_number,
        'students_count': parent.students_count
    } for parent in parents]

    student_results = [{
        'parent_id': student.parent.id if student.parent else None,
        'parent_phone': student.parent_phone,
        'full_name': f"{student.surname} {student.first_name} {student.middle_name or ''}".strip(),
        'admission_number': student.admission_number,
        'parent_name': student.parent.full_name if student.parent else 'No parent'
    } for student in students]

    return JsonResponse({
        'parents': parent_results,
        'students': student_results
    })

@login_required
@group_required('Secretary', 'Director')
def filter_students(request):
    try:
        class_id = request.GET.get('class_id')
        name = request.GET.get('name')
        gender = request.GET.get('gender')
        parent_phone = request.GET.get('parent_phone')
        page_number = request.GET.get('page', 1)
        
        students = Student.objects.select_related('current_class', 'current_section', 'parent')

        if class_id:
            try:
                students = students.filter(current_class__id=class_id)
            except ValueError:
                logger.error(f"Invalid class_id: {class_id}")
                return JsonResponse({'students': [], 'error': 'Invalid class ID'}, status=400)
        
        
        if name:
            name_parts = name.split()
            q_objects = Q()
            
            for part in name_parts:
                q_objects |= (
                    Q(first_name__icontains=part) |
                    Q(middle_name__icontains=part) |
                    Q(surname__icontains=part) |
                    Q(first_name__istartswith=part) |
                    Q(surname__istartswith=part) |
                    Q(admission_number__icontains=part))
            
            students = students.filter(q_objects)
        
        if gender:
            students = students.filter(gender=gender)
        if parent_phone:
            students = students.filter(parent_phone__icontains=parent_phone)

        
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
@group_required('Principal', 'Director')
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
    return render(request, 'account/admin/teacher_management.html', context)

@login_required
@group_required('Principal', 'Director')
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
    
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.core.paginator import Paginator
from django.utils import timezone
from accounts.models import Student, SchoolClass, ClassSection, Session, Notification, StudentClassHistory
from accounts.decorators import group_required
from accounts.utils.index import get_current_session_term
from .base import get_user_context, logger

@login_required
@group_required('Director')
def promote_students(request):
    context = get_user_context(request)
    if not context:
        return redirect('login')

    current_session, current_term = get_current_session_term()
    current_month = timezone.now().month
    if current_month != 8:  
        messages.error(request, 'Student promotion is only allowed in August.')
        return redirect('admin_student_management')

    
    next_session_year = current_session.start_year + 1
    next_session, created = Session.objects.get_or_create(
        start_year=next_session_year,
        end_year=next_session_year + 1,
        defaults={'name': f'{next_session_year}/{next_session_year + 1}', 'is_active': False}
    )
    if created:
        logger.info(f'Created new session: {next_session.name}')

    # Create ClassSection records for next session if they don't exist
    for class_section in ClassSection.objects.filter(session=current_session):
        ClassSection.objects.get_or_create(
            school_class=class_section.school_class,
            suffix=class_section.suffix,
            session=next_session,
            defaults={'is_active': True}
        )

    if request.method == 'POST':
        try:
            with transaction.atomic():
                action = request.POST.get('action')  
                if action == 'promote_all':
                    selected_student_ids = Student.objects.filter(
                        is_active=True,
                        current_class__isnull=False
                    ).exclude(current_class__level='SS 3').values_list('admission_number', flat=True)
                    action = 'promote'  
                else:
                    selected_student_ids = request.POST.getlist('students')

                students_to_process = Student.objects.filter(admission_number__in=selected_student_ids)

                for student in students_to_process:
                    current_class = student.current_class
                    if not current_class:
                        logger.warning(f"Student {student.full_name} has no current class, skipping.")
                        messages.warning(request, f"Student {student.full_name} has no current class and was skipped.")
                        continue

                    
                    if action == 'promote':
                        next_class = SchoolClass.objects.filter(
                            level_order__gt=current_class.level_order
                        ).order_by('level_order').first()
                    elif action == 'demote':
                        next_class = SchoolClass.objects.filter(
                            level_order__lt=current_class.level_order
                        ).order_by('-level_order').first()
                    else:
                        messages.error(request, 'Invalid action specified.')
                        return redirect('promote_students')

                    if not next_class:
                        logger.warning(f"No {'next' if action == 'promote' else 'previous'} class for {student.full_name} in {current_class.level}")
                        messages.warning(request, f"No {'next' if action == 'promote' else 'previous'} class available for {student.full_name} in {current_class.level}")
                        continue

                    
                    new_section = None
                    if student.current_section and student.current_section.suffix != 'N/A':
                        new_section = ClassSection.objects.filter(
                            school_class=next_class,
                            suffix=student.current_section.suffix,
                            session=next_session
                        ).first()
                        if not new_section:
                            logger.warning(
                                f'No matching section for {next_class.level} {student.current_section.suffix} '
                                f'in session {next_session.name} for student {student.full_name}'
                            )
                            messages.warning(request, f"No section {student.current_section.suffix} found for {next_class.level} in {next_session.name} for {student.full_name}")

                    
                    student.current_class = next_class
                    student.current_section = new_section
                    student.save()

                    
                    history, created = StudentClassHistory.objects.get_or_create(
                        student=student,
                        session=next_session,
                        term='1',  
                        defaults={
                            'class_level': next_class,
                            'section': new_section
                        }
                    )
                    if not created:
                        history.class_level = next_class
                        history.section = new_section
                        history.save()

                    Notification.objects.create(
                        user=student.user,
                        message=f"You have been {action}d to {next_class.level} "
                                f"{' ' + new_section.suffix if new_section else ''} for {next_session.name}."
                    )
                    logger.info(
                        f"Student {student.full_name} {action}d to {next_class.level} "
                        f"{' ' + new_section.suffix if new_section else ''} by {request.user.username}"
                    )

                
                ss3_students = Student.objects.filter(
                    current_class__level='SS 3', is_active=True
                )
                for student in ss3_students:
                    student.is_active = False
                    student.save()
                    history, created = StudentClassHistory.objects.get_or_create(
                        student=student,
                        session=next_session,
                        term='1',
                        defaults={
                            'class_level': student.current_class,
                            'section': student.current_section
                        }
                    )
                    if not created:
                        history.class_level = student.current_class
                        history.section = student.current_section
                        history.save()
                    Notification.objects.create(
                        user=student.user,
                        message=f"You have graduated from {student.current_class.level} in {current_session.name}."
                    )
                    logger.info(f"Student {student.full_name} marked as graduated by {request.user.username}")

                messages.success(request, f'Student {action} completed successfully.')
                return redirect('admin_student_management')

        except Exception as e:
            messages.error(request, f'Error during {action}: {str(e)}')
            logger.error(f"Error during {action}: {str(e)}")
            return redirect('promote_students')

    
    classes = SchoolClass.objects.all().order_by('level_order')
    class_data = []
    for school_class in classes:
        students = Student.objects.filter(
            is_active=True,
            current_class=school_class
        ).exclude(current_class__level='SS 3').select_related('current_section')
        if students.exists():
            paginator = Paginator(students, 10)  
            page_number = request.GET.get(f'page_{school_class.id}', 1)
            page_obj = paginator.get_page(page_number)
            student_data = []
            for student in page_obj.object_list:
                next_class = SchoolClass.objects.filter(
                    level_order__gt=student.current_class.level_order
                ).order_by('level_order').first()
                next_section = None
                if student.current_section and student.current_section.suffix != 'N/A' and next_class:
                    next_section = ClassSection.objects.filter(
                        school_class=next_class,
                        suffix=student.current_section.suffix,
                        session=next_session
                    ).first()
                student_data.append({
                    'student': student,
                    'next_class': next_class,
                    'next_section': next_section
                })
            class_data.append({
                'school_class': school_class,
                'students': student_data,
                'page_obj': page_obj,
                'next_class': next_class.level if next_class else 'No Promotion',
                'page_param': f'page_{school_class.id}'
            })

    context.update({
        'current_session': current_session,
        'next_session': next_session,
        'class_data': class_data,
        'students_count': Student.objects.filter(
            is_active=True,
            current_class__isnull=False
        ).exclude(current_class__level='SS 3').count(),
        'role': 'admin'
    })
    return render(request, 'account/admin/promote_students.html', context)

@login_required
@group_required('Principal', 'Director')
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
    return render(request, 'account/admin/view_student_results.html', context)

@login_required
@group_required('Principal', 'Director')
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
@group_required('Principal', 'Director')
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
@group_required('Director')
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
def update_student(request, admission_number):
    student = get_object_or_404(Student, admission_number=admission_number)
    classes = SchoolClass.objects.all().order_by('level_order')
    genders = [('M', 'Male'), ('F', 'Female')]
    current_session = Session.objects.filter(is_active=True).first()

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Update student fields
                student.first_name = request.POST.get('first_name', '').strip()
                student.middle_name = request.POST.get('middle_name', '').strip()
                student.surname = request.POST.get('surname', '').strip()
                student.date_of_birth = request.POST.get('date_of_birth')
                student.nationality = request.POST.get('nationality', 'Nigeria').strip()
                student.address = request.POST.get('address', '').strip()
                student.parent_phone = request.POST.get('parent_phone', '').strip() or None
                student.gender = request.POST.get('gender')
                student.enrollment_year = request.POST.get('enrollment_year')
                student.is_active = request.POST.get('is_active') == 'on'

                # Handle class
                class_id = request.POST.get('class')
                student.current_class = SchoolClass.objects.get(id=class_id) if class_id else None
                student.current_section = None  # Section removed from form

                # Handle photo upload
                if 'photo' in request.FILES:
                    student.photo = request.FILES['photo']

                # Validate student data
                student.clean()

                # Update User model
                if student.user:
                    student.user.first_name = student.first_name
                    student.user.last_name = student.surname
                    student.user.is_active = student.is_active
                    student.user.save()

                # Save student
                student.save()

                # Update class history
                if student.current_class and current_session:
                    history, created = StudentClassHistory.objects.get_or_create(
                        student=student,
                        session=current_session,
                        term=current_session.term_configurations.first().term if current_session.term_configurations.exists() else '1',
                        defaults={
                            'class_level': student.current_class,
                            'section': None
                        }
                    )
                    if not created:
                        history.class_level = student.current_class
                        history.section = None
                        history.save()

                messages.success(request, "Student updated successfully.")
                return redirect('admin_student_management')

        except ValidationError as e:
            messages.error(request, f"Error updating student: {str(e)}")
        except Exception as e:
            messages.error(request, f"An unexpected error occurred: {str(e)}")

    context = {
        'student': student,
        'classes': classes,
        'genders': genders,
    }
    return render(request, 'account/admin/update_student.html', context)

def get_students_by_phone(request):
    phone = request.GET.get('phone', '').strip()
    if not phone or not re.match(r'^\+?\d{8,15}$', phone):
        return JsonResponse({'students': []})
    
    students = Student.objects.filter(parent_phone=phone, is_active=True).exclude(admission_number=request.GET.get('exclude_admission_number', '')).values('admission_number', 'first_name', 'middle_name', 'surname')
    student_list = [
        {
            'admission_number': student['admission_number'],
            'full_name': f"{student['surname']} {student['first_name']} {student['middle_name'] or ''}".strip()
        } for student in students
    ]
    return JsonResponse({'students': student_list})

@login_required
@group_required('Principal', 'Director')
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
@group_required('Principal', 'Director')
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
@group_required('Principal', 'Director')
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

        
        student_subjects = StudentSubject.objects.filter(
            student__in=students,
            session=selected_session,
            term=term,
            subject__is_active=True
        ).select_related('subject')
        subject_ids = student_subjects.values_list('subject__id', flat=True).distinct()

        
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

        
        results = Result.objects.filter(
            student__in=students,
            session=selected_session,
            term=term,
            subject__id__in=subject_ids
        ).select_related('student', 'subject', 'uploaded_by')

        
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
            
            if expected_results == 0:
                student_results = results.filter(student=student)
                expected_results = student_results.values('subject__id').distinct().count()
            if expected_results > 0 and actual_results == expected_results:
                complete_students += 1

        upload_percentage = (complete_students / student_count * 100) if student_count > 0 else 0

        teachers = section.teachers.filter(is_active=True)

        
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
    return render(request, 'account/admin/result_tracking.html', context)

@login_required
@group_required('Principal', 'Director')
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
@group_required('Director')
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
    return render(request, 'account/admin/manage_subjects.html', context)

@login_required
@group_required('Director')
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
@group_required('Director')
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
@group_required('Director')
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
        return render(request, 'account/admin/statistics.html', context)

    
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

    return render(request, 'account/admin/statistics.html', context)

@login_required
@group_required('Secretary', 'Director')
def search_family_by_student_name(request):
    query = request.GET.get('query', '').strip()
    session_id = request.GET.get('session_id')
    term = request.GET.get('term')

    if not query or len(query) < 2:
        return JsonResponse({'error': 'Query must be at least 2 characters long'}, status=400)
    if not session_id or not term:
        return JsonResponse({'error': 'Session and term are required'}, status=400)

    try:
        session = Session.objects.get(id=session_id)
    except ObjectDoesNotExist:
        return JsonResponse({'error': 'Invalid session'}, status=400)
    if term not in [t[0] for t in TERM_CHOICES]:
        return JsonResponse({'error': 'Invalid term'}, status=400)

    try:
        
        query_parts = query.split()
        students = Student.objects.filter(is_active=True).select_related('parent', 'current_class')
        
        if len(query_parts) >= 2:
            
            surname, first_name = query_parts[0], query_parts[1]
            students = students.filter(
                Q(surname__iexact=surname, first_name__iexact=first_name) |
                Q(first_name__iexact=surname, surname__iexact=first_name) |
                Q(surname__iexact=surname, middle_name__iexact=first_name) |
                Q(middle_name__iexact=surname, first_name__iexact=first_name)
            )
        elif len(query_parts) == 1:
            
            students = students.filter(
                Q(admission_number__iexact=query) |
                Q(surname__icontains=query) |
                Q(first_name__icontains=query) |
                Q(middle_name__icontains=query) |
                Q(parent_phone__icontains=query)
            )
        else:
            
            students = students.filter(
                Q(full_name__icontains=query) |
                Q(admission_number__iexact=query) |
                Q(parent_phone__icontains=query)
            )

        if not students.exists():
            return JsonResponse({'family': None})

        parent = students.first().parent
        if not parent:
            return JsonResponse({'error': 'No parent associated with the student'}, status=400)

        
        can_pay = parent.has_completed_previous_term_payments(session, term)
        if not can_pay:
            return JsonResponse({'error': 'Previous term payments incomplete. Please clear outstanding balance.'}, status=400)

        family = {
            'parent_id': parent.id,
            'students': [],
            'total_student_fees': 0,
            'pta_dues': 0,
            'total_fees': 0,
            'amount_paid': 0,
            'amount_due': 0,
            'previous_payments': [],
            'is_first_term': term == '1',
            'refunds': []
        }

        parent_students = Student.objects.filter(parent=parent, is_active=True).select_related('current_class')
        total_student_fees = Decimal('0')
        for student in parent_students:
            override = StudentFeeOverride.objects.filter(student=student, session=session, term=term).first()
            if override:
                fee_amount = override.amount
            else:
                fee = FeeStructure.objects.filter(
                    session=session,
                    term=term,
                    class_level=student.current_class
                ).first()
                fee_amount = fee.amount if fee else Decimal('0')
            total_student_fees += fee_amount
            family['students'].append({
                'student_id': student.admission_number,
                'full_name': student.full_name,
                'class_level': student.current_class.level if student.current_class else 'N/A',
                'fee_amount': str(fee_amount)
            })

        family['total_student_fees'] = str(total_student_fees)
        pta_dues = Decimal('0')
        if term == '1':
            pta_dues_record = PTADues.objects.filter(session=session, term=term).first()
            pta_dues = pta_dues_record.amount if pta_dues_record else Decimal('2000.00')
        family['pta_dues'] = str(pta_dues)
        family['total_fees'] = str(total_student_fees + pta_dues)
        payment_status = parent.get_payment_status_for_term(session, term)
        family['amount_paid'] = str(payment_status['amount_paid'])
        family['amount_due'] = str(payment_status['amount_due'])

        payments = Payment.objects.filter(parent=parent, session=session, term=term).select_related('session').prefetch_related('students')
        for payment in payments:
            family['previous_payments'].append({
                'id': payment.id,
                'transaction_id': payment.transaction_id,
                'amount': str(payment.amount),
                'status': payment.status,
                'datetime': payment.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })

        refunds = Refund.objects.filter(parent=parent, session=session, term=term)
        for refund in refunds:
            family['refunds'].append({
                'id': refund.id,
                'amount': str(refund.amount),
                'reason': refund.reason,
                'datetime': refund.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })

        return JsonResponse({'family': family})
    except Exception as e:
        logger.error(f"Error in search_family_by_student_name: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@group_required('Secretary', 'Director')
@transaction.atomic
def admin_create_payment(request):
    if request.method == 'GET':
        current_session, current_term = get_current_session_term()
        sessions = Session.objects.all()
        context = {
            'sessions': sessions,
            'current_session': current_session,
            'current_term': current_term,
            'term_choices': TERM_CHOICES,
            'role': 'admin'
        }
        return render(request, 'account/admin/create_payment.html', context)

    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=400)

    try:
        action = request.POST.get('action')
        parent_id = request.POST.get('parent_id')
        session_id = request.POST.get('session_id')
        term = request.POST.get('term')
        amount = request.POST.get('amount')

        if not all([parent_id, session_id, term]):
            return JsonResponse({'error': 'Missing required fields'}, status=400)

        parent = Parent.objects.get(id=parent_id)
        session = Session.objects.get(id=session_id)
        if term not in [t[0] for t in TERM_CHOICES]:
            return JsonResponse({'error': 'Invalid term'}, status=400)

        
        if not parent.has_completed_previous_term_payments(session, term):
            return JsonResponse({'error': 'Previous term payments incomplete. Please clear outstanding balance.'}, status=400)

        if action == 'create':
            amount = Decimal(amount)
            if amount <= 0:
                return JsonResponse({'error': 'Amount must be greater than 0'}, status=400)
            total_fees = parent.get_total_fees_for_term(session, term)
            payment_status = parent.get_payment_status_for_term(session, term)
            if amount > (payment_status['amount_due'] + payment_status['amount_paid']):
                return JsonResponse({'error': f'Amount cannot exceed total fees {total_fees} XOF'}, status=400)
            payment = Payment.objects.create(
                parent=parent,
                session=session,
                term=term,
                amount=amount,
                status='Completed'
            )
            payment.students.set(parent.students.filter(is_active=True))
            message = f'Payment of {amount} XOF recorded for {parent.full_name or parent.phone_number}'
        elif action == 'edit':
            payment_id = request.POST.get('payment_id')
            if not payment_id:
                return JsonResponse({'error': 'Payment ID required for editing'}, status=400)
            payment = Payment.objects.get(id=payment_id, parent=parent, session=session, term=term)
            amount = Decimal(amount)
            if amount < 0:
                return JsonResponse({'error': 'Amount cannot be negative'}, status=400)
            total_fees = parent.get_total_fees_for_term(session, term)
            other_payments = Payment.objects.filter(parent=parent, session=session, term=term).exclude(id=payment_id).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            if amount + other_payments > total_fees:
                return JsonResponse({'error': f'New amount plus other payments cannot exceed total fees {total_fees} XOF'}, status=400)
            payment.amount = amount
            payment.status = 'Completed' if amount > 0 else 'Cancelled'
            payment.save()
            message = f'Payment of {amount} XOF updated for {parent.full_name or parent.phone_number}'
        elif action == 'delete':
            payment_id = request.POST.get('payment_id')
            if not payment_id:
                return JsonResponse({'error': 'Payment ID required for deletion'}, status=400)
            payment = Payment.objects.get(id=payment_id, parent=parent, session=session, term=term)
            payment.delete()
            message = f'Payment {payment.transaction_id} deleted for {parent.full_name or parent.phone_number}'
        else:
            return JsonResponse({'error': 'Invalid action'}, status=400)

        pta_dues = Decimal('0')
        if term == '1':
            pta_dues_record = PTADues.objects.filter(session=session, term=term).first()
            pta_dues = pta_dues_record.amount if pta_dues_record else Decimal('2000.00')

        payment_status = parent.get_payment_status_for_term(session, term)
        family = {
            'parent_id': parent.id,
            'students': [
                {
                    'student_id': student.admission_number,
                    'full_name': student.full_name,
                    'class_level': student.current_class.level if student.current_class else 'N/A',
                    'fee_amount': str(
                        StudentFeeOverride.objects.filter(student=student, session=session, term=term).first().amount
                        if StudentFeeOverride.objects.filter(student=student, session=session, term=term).exists()
                        else FeeStructure.objects.filter(
                            session=session,
                            term=term,
                            class_level=student.current_class
                        ).first().amount if student.current_class else Decimal('0')
                    )
                } for student in parent.students.filter(is_active=True)
            ],
            'total_student_fees': str(total_fees - pta_dues),
            'pta_dues': str(pta_dues),
            'total_fees': str(total_fees),
            'amount_paid': str(payment_status['amount_paid']),
            'amount_due': str(payment_status['amount_due']),
            'previous_payments': [
                {
                    'id': p.id,
                    'transaction_id': p.transaction_id,
                    'amount': str(p.amount),
                    'status': p.status,
                    'datetime': p.created_at.strftime('%Y-%m-%d %H:%M:%S')
                } for p in Payment.objects.filter(parent=parent, session=session, term=term)
            ],
            'refunds': [
                {
                    'id': r.id,
                    'amount': str(r.amount),
                    'reason': r.reason,
                    'datetime': r.created_at.strftime('%Y-%m-%d %H:%M:%S')
                } for r in Refund.objects.filter(parent=parent, session=session, term=term)
            ],
            'is_first_term': term == '1'
        }

        return JsonResponse({
            'success': True,
            'message': message,
            'total_student_fees': family['total_student_fees'],
            'pta_dues': family['pta_dues'],
            'total_fees': family['total_fees'],
            'amount_paid': family['amount_paid'],
            'amount_due': family['amount_due'],
            'previous_payments': family['previous_payments'],
            'refunds': family['refunds'],
            'is_first_term': family['is_first_term']
        })
    except Exception as e:
        logger.error(f"Error in admin_create_payment: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@group_required('Secretary', 'Director')
def admin_edit_student_fee(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    try:
        student_id = request.POST.get('student_id')
        session_id = request.POST.get('session_id')
        term = request.POST.get('term')
        new_amount = request.POST.get('new_amount')

        # Validate inputs
        if not all([student_id, session_id, term, new_amount]):
            logger.error(f"Missing required fields: student_id={student_id}, session_id={session_id}, term={term}, new_amount={new_amount}")
            return JsonResponse({'error': 'Missing required fields'}, status=400)

        try:
            new_amount = Decimal(new_amount)
            if new_amount < 0:
                logger.error(f"Negative fee amount: {new_amount}")
                return JsonResponse({'error': 'Fee amount cannot be negative'}, status=400)
        except (ValueError, TypeError):
            logger.error(f"Invalid fee amount: {new_amount}")
            return JsonResponse({'error': 'Invalid fee amount'}, status=400)

        try:
            student = Student.objects.get(admission_number=student_id)
        except Student.DoesNotExist:
            logger.error(f"Student not found: {student_id}")
            return JsonResponse({'error': f'Student with ID {student_id} not found'}, status=404)

        try:
            session = Session.objects.get(id=session_id)
        except Session.DoesNotExist:
            logger.error(f"Session not found: {session_id}")
            return JsonResponse({'error': f'Session with ID {session_id} not found'}, status=404)

        if term not in [t[0] for t in TERM_CHOICES]:
            logger.error(f"Invalid term: {term}")
            return JsonResponse({'error': f'Invalid term: {term}'}, status=400)

        # Update or create fee override
        with transaction.atomic():
            fee_override, created = StudentFeeOverride.objects.update_or_create(
                student=student,
                session=session,
                term=term,
                defaults={'amount': new_amount, 'updated_by': request.user}
            )
            action = 'created' if created else 'updated'
            logger.info(f"Student fee {action} for {student.full_name}, session {session.name}, term {term}, amount {new_amount}")

        # Calculate updated totals
        parent = student.parent
        parent_students = Student.objects.filter(parent=parent, is_active=True).select_related('current_class')
        total_student_fees = Decimal('0')
        for s in parent_students:
            override = s.fee_overrides.filter(session=session, term=term).first()
            fee_amount = override.amount if override else (
                FeeStructure.objects.filter(session=session, term=term, class_level=s.current_class).first().amount
                if s.current_class and FeeStructure.objects.filter(session=session, term=term, class_level=s.current_class).exists()
                else Decimal('0')
            )
            total_student_fees += fee_amount

        pta_dues = Decimal('0')
        if term == '1':
            pta = PTADues.objects.filter(session=session, term=term).first()
            pta_dues = pta.amount if pta else Decimal('2000.00')

        total_fees = total_student_fees + pta_dues
        payments = Payment.objects.filter(parent=parent, session=session, term=term).aggregate(total_paid=Sum('amount'))
        refunds = Refund.objects.filter(parent=parent, session=session, term=term).aggregate(total_refunded=Sum('amount'))
        amount_paid = (payments['total_paid'] or Decimal('0')) - (refunds['total_refunded'] or Decimal('0'))
        amount_due = max(total_fees - amount_paid, Decimal('0'))

        return JsonResponse({
            'success': True,
            'message': f"Fee {action} successfully for {student.full_name} ({term} Term, {session.name})",
            'updated_student': {
                'student_id': student.admission_number,
                'fee_amount': str(new_amount)
            },
            'total_student_fees': str(total_student_fees),
            'pta_dues': str(pta_dues),
            'total_fees': str(total_fees),
            'amount_paid': str(amount_paid),
            'amount_due': str(amount_due)
        })

    except Exception as e:
        logger.exception(f"Error editing student fee: {str(e)}")
        return JsonResponse({'error': f'Internal server error: {str(e)}'}, status=500)
    
@login_required
@group_required('Secretary', 'Director')
def admin_payment_report(request):
    sessions = Session.objects.all()
    current_session, current_term = get_current_session_term()
    session_id = request.GET.get('session_id', current_session.id if current_session else '')
    term = request.GET.get('term', current_term if current_term else '1')
    sort_type = request.GET.get('sort_type', 'all')  # Default to show all

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
        amount_due = payment_status['amount_due']
        percentage_paid = (amount_paid / total_fees * 100) if total_fees > 0 else 0
        students = parent.students.filter(is_active=True).select_related('current_class').order_by('current_class__level_order')
        student_list = [f"{s.full_name} - {s.current_class.level}" for s in students if s.current_class]
        payment_category = 'full' if amount_due == 0 else 'partial' if amount_paid > 0 else 'none'
        report_data.append({
            'students': ', '.join(student_list) if student_list else 'No students',
            'parent_phone': parent.phone_number,
            'total_fees': float(total_fees),
            'amount_paid': float(amount_paid),
            'amount_due': float(amount_due),
            'percentage_paid': round(percentage_paid, 2),
            'category': payment_category
        })

    # Log the report data for debugging
    logger.info(f"Generated report data: {len(report_data)} families")

    # Group data by category
    full_paid = [item for item in report_data if item['category'] == 'full']
    partial_paid = [item for item in report_data if item['category'] == 'partial']
    not_paid = [item for item in report_data if item['category'] == 'none']

    # Log the counts for each category
    logger.info(f"Full paid: {len(full_paid)}, Partial paid: {len(partial_paid)}, Not paid: {len(not_paid)}")

    # Sort each group by amount_paid descending
    full_paid.sort(key=lambda x: x['amount_paid'], reverse=True)
    partial_paid.sort(key=lambda x: x['amount_paid'], reverse=True)
    not_paid.sort(key=lambda x: x['amount_paid'], reverse=True)

    # Filter and paginate based on sort_type
    if sort_type == 'full':
        filtered_data = full_paid
    elif sort_type == 'partial':
        filtered_data = partial_paid
    elif sort_type == 'none':
        filtered_data = not_paid
    else:
        filtered_data = full_paid + partial_paid + not_paid  # All, in order: full, partial, none

    paginator = Paginator(filtered_data, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'sessions': sessions,
        'current_session': session,
        'current_term': term,
        'term_choices': TERM_CHOICES,
        'page_obj': page_obj,
        'report_data': page_obj.object_list,
        'sort_type': sort_type,
        'full_paid': full_paid,  # Pass full lists for grouped display
        'partial_paid': partial_paid,
        'not_paid': not_paid,
        'full_paid_count': len(full_paid),
        'partial_paid_count': len(partial_paid),
        'not_paid_count': len(not_paid),
        'role': 'admin'
    }

    return render(request, 'account/admin/payment_report.html', context)

@login_required
@group_required('Secretary', 'Director')
def admin_payment_report_pdf(request):
    session_id = request.GET.get('session_id')
    term = request.GET.get('term')
    sort_type = request.GET.get('sort_type', 'all')

    try:
        session = Session.objects.get(id=session_id)
    except Session.DoesNotExist:
        return HttpResponse("Session not found", status=404)

    parents = Parent.objects.filter(is_active=True).prefetch_related('students__current_class', 'payments')
    report_data = []
    for parent in parents:
        total_fees = parent.get_total_fees_for_term(session, term)
        payment_status = parent.get_payment_status_for_term(session, term)
        amount_paid = payment_status['amount_paid']
        amount_due = payment_status['amount_due']
        percentage_paid = (amount_paid / total_fees * 100) if total_fees > 0 else 0
        students = parent.students.filter(is_active=True).select_related('current_class').order_by('current_class__level_order')
        student_list = [f"{s.full_name} - {s.current_class.level}" for s in students if s.current_class]
        payment_category = 'full' if amount_due == 0 else 'partial' if amount_paid > 0 else 'none'
        report_data.append({
            'students': ', '.join(student_list) if student_list else 'No students',
            'parent_phone': parent.phone_number,
            'total_fees': float(total_fees),
            'amount_paid': float(amount_paid),
            'amount_due': float(amount_due),
            'percentage_paid': round(percentage_paid, 2),
            'category': payment_category
        })

    # Log the report data for debugging
    logger.info(f"Generated PDF report data: {len(report_data)} families")

    # Group data by category
    full_paid = [item for item in report_data if item['category'] == 'full']
    partial_paid = [item for item in report_data if item['category'] == 'partial']
    not_paid = [item for item in report_data if item['category'] == 'none']

    # Log the counts for each category
    logger.info(f"PDF - Full paid: {len(full_paid)}, Partial paid: {len(partial_paid)}, Not paid: {len(not_paid)}")

    # Sort each group by amount_paid descending
    full_paid.sort(key=lambda x: x['amount_paid'], reverse=True)
    partial_paid.sort(key=lambda x: x['amount_paid'], reverse=True)
    not_paid.sort(key=lambda x: x['amount_paid'], reverse=True)

    # Filter based on sort_type
    if sort_type == 'full':
        filtered_data = full_paid
    elif sort_type == 'partial':
        filtered_data = partial_paid
    elif sort_type == 'none':
        filtered_data = not_paid
    else:
        filtered_data = full_paid + partial_paid + not_paid

    context = {
        'report_data': filtered_data,
        'current_session': session,
        'current_term': term,
        'date_generated': date.today(),
        'sort_type': sort_type,
        'full_paid': full_paid,
        'partial_paid': partial_paid,
        'not_paid': not_paid,
        'full_paid_count': len(full_paid),
        'partial_paid_count': len(partial_paid),
        'not_paid_count': len(not_paid),
    }

    html_string = render_to_string('account/admin/payment_report_pdf.html', context)
    html = HTML(string=html_string)
    result = html.write_pdf()

    response = HttpResponse(result, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="payment_report_{session.name}_{term}.pdf"'
    return response

@login_required
@group_required('Secretary', 'Director')
def admin_fee_statistics(request):
    sessions = Session.objects.all()
    current_session, current_term = get_current_session_term()
    logger.debug('Admin Fee Statistics: current_session=%s, current_term=%s', 
                 current_session.name if current_session else None, current_term)
    session_id = request.GET.get('session_id', current_session.id if current_session else '')
    term = request.GET.get('term', current_term if current_term else '1')

    try:
        session = Session.objects.get(pk=session_id) if session_id else current_session
        if term not in dict(TERM_CHOICES):
            term = current_term or '1'
    except Session.DoesNotExist:
        logger.error('Session not found: %s', session_id)
        session = current_session
        term = current_term or '1'

    section_mappings = {
        'Creche': ['Creche'],
        'Nursery_Primary': ['Pre-Nursery', 'Nursery 1', 'Nursery 2', 'Nursery 3', 'Primary 1', 'Primary 2', 'Primary 3', 'Primary 4', 'Primary 5'],
        'Junior': ['JSS 1', 'JSS 2', 'JSS 3'],
        'Senior': ['SS 1', 'SS 2', 'SS 3'],
    }

    stats_data = []
    total_expected = Decimal(0)
    total_paid = Decimal(0)

    fee_structures = FeeStructure.objects.filter(
        session=session, term=term
    ).select_related('class_level')
    student_counts = Student.objects.filter(
        is_active=True,
        current_class__isnull=False,
        enrollment_year__lte=session.end_year
    ).values('current_class__level', 'current_class__section').annotate(
        count=Count('pk')
    )

    payment_sums = Payment.objects.filter(
        session=session, term=term, students__is_active=True
    ).values('students__current_class__level').annotate(
        total_paid=Sum('amount')
    )

    student_count_by_class = {item['current_class__level']: item['count'] for item in student_counts}
    payment_by_class = {item['students__current_class__level']: item['total_paid'] for item in payment_sums}

    for section, class_levels in section_mappings.items():
        section_expected = Decimal(0)
        section_paid = Decimal(0)
        student_count = 0

        for class_level in class_levels:
            fee_structure = fee_structures.filter(class_level__level=class_level).first()
            fee_amount = fee_structure.amount if fee_structure else Decimal(0)
            logger.debug('Class: %s, Fee Amount: %s', class_level, fee_amount)

            class_student_count = student_count_by_class.get(class_level, 0)
            student_count += class_student_count

            class_expected = fee_amount * class_student_count
            section_expected += class_expected

            class_paid = payment_by_class.get(class_level, Decimal(0))
            class_paid = min(class_paid, class_expected)
            section_paid += class_paid

            logger.debug('Class: %s, Students: %s, Expected: %s, Paid: %s', 
                         class_level, class_student_count, class_expected, class_paid)

        if term == '1':
            pta_dues = PTADues.objects.filter(session=session, term=term).first()
            pta_amount = pta_dues.amount if pta_dues else Decimal('2000.00')
            section_expected += pta_amount * student_count
            logger.debug('Section: %s, PTA Dues: %s', section, pta_amount)

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

    return render(request, 'account/admin/fee_statistics.html', context)

@login_required
@group_required('Secretary', 'Director')
def admin_fee_statistics_pdf(request):
    sessions = Session.objects.all()
    current_session, current_term = get_current_session_term()
    logger.debug('Admin Fee Statistics PDF: current_session=%s, current_term=%s', 
                 current_session.name if current_session else None, current_term)
    session_id = request.GET.get('session_id', current_session.id if current_session else '')
    term = request.GET.get('term', current_term if current_term else '1')

    try:
        session = Session.objects.get(pk=session_id) if session_id else current_session
        if term not in dict(TERM_CHOICES):
            term = current_term or '1'
    except Session.DoesNotExist:
        logger.error('Session not found: %s', session_id)
        session = current_session
        term = current_term or '1'

    section_mappings = {
        'Creche': ['Creche'],
        'Nursery_Primary': ['Pre-Nursery', 'Nursery 1', 'Nursery 2', 'Nursery 3', 'Primary 1', 'Primary 2', 'Primary 3', 'Primary 4', 'Primary 5'],
        'Junior': ['JSS 1', 'JSS 2', 'JSS 3'],
        'Senior': ['SS 1', 'SS 2', 'SS 3'],
    }

    stats_data = []
    total_expected = Decimal(0)
    total_paid = Decimal(0)

    fee_structures = FeeStructure.objects.filter(
        session=session, term=term
    ).select_related('class_level')
    student_counts = Student.objects.filter(
        is_active=True,
        current_class__isnull=False,
        enrollment_year__lte=session.end_year
    ).values('current_class__level', 'current_class__section').annotate(
        count=Count('pk')
    )

    payment_sums = Payment.objects.filter(
        session=session, term=term, students__is_active=True
    ).values('students__current_class__level').annotate(
        total_paid=Sum('amount')
    )

    student_count_by_class = {item['current_class__level']: item['count'] for item in student_counts}
    payment_by_class = {item['students__current_class__level']: item['total_paid'] for item in payment_sums}

    for section, class_levels in section_mappings.items():
        section_expected = Decimal(0)
        section_paid = Decimal(0)
        student_count = 0

        for class_level in class_levels:
            fee_structure = fee_structures.filter(class_level__level=class_level).first()
            fee_amount = fee_structure.amount if fee_structure else Decimal(0)
            logger.debug('Class: %s, Fee Amount: %s', class_level, fee_amount)

            class_student_count = student_count_by_class.get(class_level, 0)
            student_count += class_student_count

            class_expected = fee_amount * class_student_count
            section_expected += class_expected

            class_paid = payment_by_class.get(class_level, Decimal(0))
            class_paid = min(class_paid, class_expected)
            section_paid += class_paid

            logger.debug('Class: %s, Students: %s, Expected: %s, Paid: %s', 
                         class_level, class_student_count, class_expected, class_paid)

        if term == '1':
            pta_dues = PTADues.objects.filter(session=session, term=term).first()
            pta_amount = pta_dues.amount if pta_dues else Decimal('2000.00')
            section_expected += pta_amount * student_count
            logger.debug('Section: %s, PTA Dues: %s', section, pta_amount)

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
        'date_generated': date.today(),
    }

    html_string = render_to_string('account/admin/fee_statistics_pdf.html', context)
    html = HTML(string=html_string)
    result = html.write_pdf()

    response = HttpResponse(result, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="fee_statistics_{session.name}_{term}.pdf"'
    return response

@login_required
@group_required('Secretary', 'Director')
def admin_daily_payment_report(request):
    sessions = Session.objects.all()
    current_session, current_term = get_current_session_term()
    logger.debug('Admin Daily Payment Report: current_session=%s, current_term=%s', 
                 current_session.name if current_session else None, current_term)
    date_str = request.GET.get('date', timezone.now().strftime('%Y-%m-%d'))
    
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = date.today()  # Use explicit date import
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
    
    return render(request, 'account/admin/daily_payment_report.html', context)

@login_required
@group_required('Secretary', 'Director')
def admin_daily_payment_report_pdf(request):
    sessions = Session.objects.all()
    current_session, current_term = get_current_session_term()
    logger.debug('Admin Daily Payment Report PDF: current_session=%s, current_term=%s', 
                 current_session.name if current_session else None, current_term)
    date_str = request.GET.get('date', timezone.now().strftime('%Y-%m-%d'))
    
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = date.today()  # Use explicit date import
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
    
    logger.debug('Daily Payment Report PDF: Date=%s, Payments=%s, Total Paid=%s', 
                 selected_date, len(payments), total_paid)

    context = {
        'current_session': current_session,
        'current_term': current_term,
        'selected_date': date_str,
        'report_data': report_data,
        'total_paid': float(total_paid),
        'date_generated': date.today(), 
    }

    html_string = render_to_string('account/admin/daily_payment_report_pdf.html', context)
    html = HTML(string=html_string)
    result = html.write_pdf()

    response = HttpResponse(result, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="daily_payment_report_{selected_date}.pdf"'
    return response
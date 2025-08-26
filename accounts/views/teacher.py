from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.urls import reverse
from django.db import transaction
from django.core.paginator import Paginator

from accounts.decorators import teacher_required
from accounts.models import Student, Result, SchoolClass, Subject, Notification, Session, ClassSection, TERM_CHOICES, StudentSubject

from .base import get_current_session_term, get_user_context, logger

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
    return render(request, 'account/teacher/view_students.html', context)

@login_required
@teacher_required
def teacher_view_class_results(request):
    context = get_user_context(request)
    if not context:
        return redirect('login')

    teacher = context['teacher']
    current_session, current_term = get_current_session_term()
    
    # Get all sections the teacher is assigned to in current session
    teacher_sections = teacher.assigned_sections.filter(
        session=current_session,
        is_active=True
    ).select_related('school_class')
    
    if not teacher_sections.exists():
        messages.warning(request, 'You are not currently assigned to any class sections.')
        return redirect('teacher_view_students')
    
    # Get selected section from query parameters
    section_id = request.GET.get('section')
    selected_section = teacher_sections.first()
    
    if section_id:
        try:
            selected_section = teacher_sections.get(id=section_id)
        except ClassSection.DoesNotExist:
            messages.error(request, 'Invalid class section selected.')
            return redirect('teacher_view_class_results')
    
    # Get term from query parameters (default to current term)
    term = request.GET.get('term', current_term)
    if term not in [t[0] for t in TERM_CHOICES]:
        term = current_term
    
    # Update positions before displaying
    update_class_positions(selected_section, current_session, term)
    first_student = Student.objects.filter(current_section=selected_section).first()
    if first_student:
        update_subject_positions(first_student, current_session, term)

    students = Student.objects.filter(
        current_section=selected_section,
        is_active=True
    ).order_by('surname', 'first_name', 'middle_name')

    all_subjects = Subject.objects.filter(
        school_class=selected_section.school_class,
        is_active=True
    ).order_by('id')

    detailed_student_results = []
    for student in students:
        student_subjects = StudentSubject.objects.filter(
            student=student,
            session=current_session,
            term=term,
            subject__is_active=True
        ).select_related('subject')
        student_subject_ids = list(student_subjects.values_list('subject__id', flat=True))
        
        if not student_subject_ids:
            result_subjects = Result.objects.filter(
                student=student,
                session=current_session,
                term=term,
                subject__is_active=True
            ).values_list('subject__id', flat=True).distinct()
            student_subject_ids = list(result_subjects)
        
        student_results = Result.objects.filter(
            student=student,
            session=current_session,
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
            session=current_session,
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
        'teacher_sections': teacher_sections,
        'selected_section': selected_section,
        'current_session': current_session,
        'current_term': current_term,
        'selected_term': term,
        'subjects': all_subjects,
        'student_results': page_obj,
        'page_obj': page_obj,
        'class_averages': class_averages,
        'is_nursery': selected_section.school_class.section == 'Nursery',
        'is_primary': selected_section.school_class.section == 'Primary',
        'total_students': students.count(),
        'students_with_complete_results': len(complete_students),
        'class_average_score': class_average_score,
        'terms': TERM_CHOICES,
    })

    return render(request, 'account/teacher/view_class_results.html', context)

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
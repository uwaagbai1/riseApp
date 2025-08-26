from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.db.models import Sum, Q

from accounts.utils.pdf_generator import generate_result_pdf
from accounts.utils.index import get_next_term_start_date, get_ordinal_suffix
from accounts.decorators import student_required
from accounts.models import ResultAccessRequest, Student, Result, Payment, Session, TERM_CHOICES, StudentClassHistory, StudentSubject

from .base import get_current_session_term, get_user_context, logger

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
    return render(request, 'account/student/view_subjects.html', context)

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

    # Get selected session and term from query parameters
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

    logger.debug(f"Checking grades for student {student.full_name}, session: {selected_session.name}, term: {selected_term}")

    is_nursery = student.current_class and student.current_class.section == 'Nursery'
    is_primary = student.current_class and student.current_class.section == 'Primary'

    # Check payment status for the selected session and term
    fees_paid = False
    if student.parent:
        fees_paid = Payment.objects.filter(
            parent=student.parent,
            session=selected_session,
            term=selected_term,
            status='Completed'
        ).exists()
    logger.debug(f"Fees paid for student {student.full_name} by parent {student.parent.phone_number if student.parent else 'None'}: {fees_paid}")

    access_approved = False
    access_request = None
    if not fees_paid:
        access_request = ResultAccessRequest.objects.filter(
            student=student,
            session=selected_session,
            term=selected_term
        ).first()
        access_approved = access_request and access_request.status == 'Approved'
    logger.debug(f"Access request status: {access_request.status if access_request else 'None'}, Approved: {access_approved}")

    # Get subjects for the selected session and term
    student_subjects = StudentSubject.objects.filter(
        student=student,
        session=selected_session,
        term=selected_term,
        subject__is_active=(selected_session == current_session and selected_term == current_term)
    ).select_related('subject')
    subject_ids = list(student_subjects.values_list('subject__id', flat=True))
    logger.debug(f"StudentSubject IDs: {subject_ids}, Count: {len(subject_ids)}")

    if not subject_ids:
        result_subjects = Result.objects.filter(
            student=student,
            session=selected_session,
            term=selected_term
        ).values_list('subject__id', flat=True).distinct()
        subject_ids = list(result_subjects)
        logger.warning(
            f"No StudentSubject records for {student.full_name} in {selected_session.name}, term {selected_term}. "
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
            session=selected_session,
            term=selected_term,
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
                    session=selected_session,
                    term=selected_term,
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
                    session=selected_session,
                    term=selected_term,
                    student__current_section=student.current_section
                ).values('student__admission_number').annotate(total=Sum('total_score')).order_by('-total')

                total_in_section = section_results.count()
                for idx, res in enumerate(section_results, 1):
                    if res['student__admission_number'] == student.admission_number:
                        class_position_marks = f"{idx}{get_ordinal_suffix(idx)}"
                        class_position_gp = class_position_marks if not (is_nursery or is_primary) else '-'
                        break

    # Past results for all sessions/terms except the selected one
    past_results = Result.objects.filter(
        student=student
    ).exclude(
        Q(session=selected_session, term=selected_term) |
        Q(total_score=0)
    ).select_related('subject', 'session').order_by('-session__start_year', 'term', 'subject__name')

    past_results_grouped = []
    for session in Session.objects.filter(
        result__student=student
    ).distinct().order_by('-start_year'):
        for term in ['1', '2', '3']:
            if session == selected_session and term == selected_term:
                continue

            term_results = [r for r in past_results if r.session == session and r.term == term]
            if not term_results:
                continue

            class_history = StudentClassHistory.objects.filter(
                student=student,
                session=session,
                term=term
            ).select_related('class_level', 'section').first()
            class_level = class_history.class_level.level if class_history and class_history.class_level else 'N/A'
            section_suffix = class_history.section.suffix if class_history and class_history.section else 'N/A'

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
                'total_in_section': term_total_in_section,
                'class_level': class_level,
                'section_suffix': section_suffix
            })

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
        'past_results_grouped': past_results_grouped,
        'current_session': current_session,
        'current_term': current_term,
        'current_term_display': dict(TERM_CHOICES).get(current_term, current_term),
        'selected_session': selected_session,
        'selected_term': selected_term,
        'fees_paid': fees_paid,
        'access_approved': access_approved,
        'access_request': access_request,
        'subject_ids': subject_ids,
        'sessions': Session.objects.all(),
        'terms': TERM_CHOICES,
        'next_term_start_date': get_next_term_start_date(selected_session, selected_term),
        'is_nursery': is_nursery,
        'is_primary': is_primary,
        'result_upload_date': result_upload_date,
        'total_in_section': total_in_section,
        'student': student,
        'overall_remark': overall_remark,
    })

    logger.debug(f"Rendering student_grades for {student.full_name} with {len(results)} results and {len(past_results_grouped)} past result groups")
    return render(request, 'account/student/grades.html', context)

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
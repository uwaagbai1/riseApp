from datetime import datetime
from itertools import groupby
from decimal import Decimal

from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.db.models import Sum, Q

from accounts.utils.index import get_next_term_start_date, get_ordinal_suffix
from accounts.decorators import parent_required
from accounts.models import FeeStructure, ResultAccessRequest, Student, Result, Payment, Session, TERM_CHOICES, StudentClassHistory, StudentFeeOverride, StudentSubject, Parent
from accounts.utils.pdf_generator import generate_result_pdf

from .base import get_current_session_term, get_user_context, logger

@login_required
@parent_required
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
        'role': 'parent',
    }
    return render(request, 'account/parent/payments.html', context)

@login_required
@parent_required
def parent_payment_detail(request, session_id, term):
    try:
        parent = request.user.parent.get()
    except Parent.DoesNotExist:
        logger.error('Parent profile not found for user: %s', request.user.username)
        messages.error(request, "Parent profile not found. Please contact support.")
        return redirect('dashboard')
    except Parent.MultipleObjectsReturned:
        logger.error('Multiple parent profiles detected for user: %s', request.user.username)
        messages.error(request, "Multiple parent profiles detected. Please contact support.")
        return redirect('dashboard')

    session = get_object_or_404(Session, pk=session_id)

    if term not in dict(TERM_CHOICES):
        logger.error('Invalid term: %s', term)
        raise Http404("Invalid term")

    total_fees = parent.get_total_fees_for_term(session, term)
    payment_status = parent.get_payment_status_for_term(session, term)

    student_fees = []
    for student in parent.students.filter(is_active=True).select_related('current_class'):
        if not student.current_class:
            logger.debug('Student %s has no current class', student.full_name)
            student_fees.append({
                'student': student,
                'class_level': 'N/A',
                'fee_amount': 0,
            })
            continue

        # Check for student-specific fee override
        override = StudentFeeOverride.objects.filter(
            student=student,
            session=session,
            term=term
        ).first()
        if override:
            fee_amount = override.amount
            logger.debug('Using fee override for student %s: %s', student.full_name, fee_amount)
        else:
            # Get fee structure for the student's class level
            fee = FeeStructure.objects.filter(
                session=session,
                term=term,
                class_level=student.current_class
            ).first()
            fee_amount = fee.amount if fee else Decimal(0)
            logger.debug('Using fee structure for student %s, class %s: %s',
                         student.full_name, student.current_class.level, fee_amount)

        student_fees.append({
            'student': student,
            'class_level': student.current_class.level if student.current_class else 'N/A',
            'fee_amount': float(fee_amount),
        })

    payments = Payment.objects.filter(
        parent=parent,
        session=session,
        term=term
    ).order_by('-created_at').select_related('parent', 'session')

    context = {
        'parent': parent,
        'session': session,
        'term': term,
        'term_name': dict(TERM_CHOICES)[term],
        'total_fees': float(total_fees),
        'payment_status': payment_status,
        'student_fees': student_fees,
        'payments': payments,
        'role': 'parent'
    }
    return render(request, 'account/parent/payment_detail.html', context)

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
        logger.warning(f"Invalid term {selected_term} selected for student {student.admission_number}")
        messages.error(request, "Invalid term selected")
        selected_term = current_term

    subject_ids = StudentSubject.objects.filter(
        student=student,
        session=selected_session,
        term=selected_term,
        subject__is_active=(selected_session == current_session and selected_term == current_term)
    ).values_list('subject_id', flat=True)

    if not subject_ids:
        subject_ids = Result.objects.filter(
            student=student,
            session=selected_session,
            term=selected_term
        ).values_list('subject__id', flat=True)
        if subject_ids:
            logger.warning(f"No StudentSubject records for student {student.admission_number}, using Result subjects: {list(subject_ids)}")

    try:
        payment_status = parent.get_payment_status_for_term(selected_session, selected_term)
        fees_paid = payment_status['status'] == 'Completed' and payment_status['amount_due'] <= 0
    except Exception as e:
        logger.error(f"Error fetching payment status for parent {parent.phone_number}: {e}")
        fees_paid = False
        payment_status = {'status': 'Pending', 'amount_paid': 0, 'amount_due': 0}

    access_request = ResultAccessRequest.objects.filter(
        student=student,
        session=selected_session,
        term=selected_term
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
                session=selected_session,
                term=selected_term,
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
                        session=selected_session,
                        term=selected_term,
                        student__current_section=student.current_section
                    ).values('student__admission_number').annotate(total=Sum('total_score')).order_by('-total')

                    total_in_section = section_results.count()
                    for idx, res in enumerate(section_results, 1):
                        if res['student__admission_number'] == student.admission_number:
                            class_position_marks = f"{idx}{get_ordinal_suffix(idx)}"
                            break
            else:
                logger.info(f"No results found for student {student.admission_number} in session {selected_session.name}, term {selected_term}")
        except Exception as e:
            logger.error(f"Error fetching results for student {student.admission_number}: {e}")
            messages.error(request, "An error occurred while fetching results. Please try again later.")

    overall_remark = results[0].remarks if results and results[0].remarks else ''
    result_upload_date = results[0].upload_date if results and results[0].upload_date else None

    try:
        past_results = Result.objects.filter(
            student=student
        ).exclude(
            Q(session=selected_session, term=selected_term) |
            Q(total_score=0)
        ).select_related('session', 'subject').order_by('-session__start_year', 'term', 'subject__name')

        past_results_grouped = []
        for session in Session.objects.filter(
            result__student=student
        ).distinct().order_by('-start_year'):
            for term in ['1', '2', '3']:
                if session == selected_session and term == selected_term:
                    continue

                group_results = [r for r in past_results if r.session == session and r.term == term]
                if not group_results:
                    continue

                class_history = StudentClassHistory.objects.filter(
                    student=student,
                    session=session,
                    term=term
                ).select_related('class_level', 'section').first()
                class_level = class_history.class_level.level if class_history and class_history.class_level else 'N/A'
                section_suffix = class_history.section.suffix if class_history and class_history.section else 'N/A'

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
                    ).values('student__admission_number').annotate(total=Sum('total_score')).order_by('-total')
                    total_in_sec = past_section_results.count()
                    for idx, res in enumerate(past_section_results, 1):
                        if res['student__admission_number'] == student.admission_number:
                            class_pos = f"{idx}{get_ordinal_suffix(idx)}"
                            break

                past_results_grouped.append({
                    'session': session,
                    'term': term,
                    'term_display': dict(TERM_CHOICES).get(term, term),
                    'results': group_results,
                    'fees_paid': past_fees_paid,
                    'has_access': has_access,
                    'access_request': past_access_request,
                    'average_score': avg_score,
                    'average_grade_point': avg_grade_point,
                    'class_position': class_pos,
                    'total_in_section': total_in_sec,
                    'class_level': class_level,
                    'section_suffix': section_suffix
                })
    except Exception as e:
        logger.error(f"Error fetching past results for student {student.admission_number}: {e}")
        past_results_grouped = []

    context = {
        'student': student,
        'current_session': current_session,
        'current_term': current_term,
        'current_term_display': current_term_display,
        'selected_session': selected_session,
        'selected_term': selected_term,
        'subject_ids': subject_ids,
        'fees_paid': fees_paid,
        'access_approved': access_approved,
        'access_request': access_request,
        'results': results,
        'is_nursery': student.current_class.section == 'Nursery' if student.current_class else False,
        'is_primary': student.current_class.section == 'Primary' if student.current_class else False,
        'average_score': round(average_score, 2),
        'average_grade_point': round(average_grade_point, 2) if average_grade_point is not None else None,
        'class_position_marks': class_position_marks,
        'total_in_section': total_in_section,
        'next_term_start_date': get_next_term_start_date(selected_session, selected_term),
        'result_upload_date': result_upload_date,
        'overall_remark': overall_remark,
        'past_results_grouped': past_results_grouped,
        'sessions': Session.objects.all(),
        'terms': TERM_CHOICES,
    }

    logger.debug(f"Rendering parent_view_child_grades for student {student.admission_number} with {len(results)} results and {len(past_results_grouped)} past result groups")
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
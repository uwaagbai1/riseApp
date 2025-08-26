
def update_subject_positions(student, session, term):
    """Update subject positions for a student's section in real-time."""
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
                if result.total_score != prev_score:
                    rank = idx
                    prev_score = result.total_score
                suffix = 'th' if 10 <= rank % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(rank % 10, 'th')
                result.subject_position = f"{rank}{suffix}"
                position_updates.append(result)

        if position_updates:
            Result.objects.bulk_update(position_updates, ['subject_position'])
            logger.debug(f"Updated subject positions for section {section}")

def update_class_positions(section, session, term):
    """Update class positions for a section in real-time."""
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
                    'avg_marks': avg_marks,
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
                    suffix = 'th' if 10 <= rank_gp % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(rank % 10, 'th')
                    for result in s['results']:
                        result.class_position_gp = f"{rank_gp}{suffix}"
                        position_updates.append(result)

        if position_updates:
            Result.objects.bulk_update(position_updates, ['class_position', 'class_position_gp'])
            logger.debug(f"Updated class positions for section {section}")


def update_subject_positions(student, session, term):
    subject_ids = StudentSubject.objects.filter(
        student=student,
        session=session,
        term=term
    ).values_list('subject__id', flat=True)
    for subject_id in subject_ids:
        subject_results = Result.objects.filter(
            subject__id=subject_id,
            session=session,
            term=term,
            student__current_section=student.current_section
        ).select_related('student').order_by('-total_score')
        ranked_results = []
        prev_score = None
        rank = 0
        for idx, result in enumerate(subject_results, 1):
            if result.total_score != prev_score:
                rank = idx
                prev_score = result.total_score
            ranked_results.append((result.student_id, rank))
        subject_positions = dict(ranked_results)
        for student_id, rank in ranked_results:
            suffix = 'th' if 10 <= rank % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(rank % 10, 'th')
            Result.objects.filter(
                student_id=student_id,
                subject_id=subject_id,
                session=session,
                term=term
            ).update(subject_position=f"{rank}{suffix}")
    logger.debug(f"Updated subject positions for {student.full_name}")

def update_class_positions(section, session, term):
    if not section:
        return
    class_students = Student.objects.filter(current_section=section)
    student_averages = []
    for class_student in class_students:
        student_subject_ids = StudentSubject.objects.filter(
            student=class_student,
            session=session,
            term=term
        ).values_list('subject__id', flat=True)
        student_results = Result.objects.filter(
            student=class_student,
            session=session,
            term=term,
            subject__id__in=student_subject_ids,
            total_score__gt=0
        ).select_related('student')
        if student_results.exists():
            avg_marks = student_results.aggregate(Avg('total_score'))['total_score__avg'] or 0.0
            avg_gp = student_results.aggregate(Avg('grade_point'))['grade_point__avg'] or 0.0 if student_results.first().grade_point is not None else 0.0
            student_averages.append({
                'student_id': class_student.pk,
                'avg_marks': avg_marks,
                'avg_gp': avg_gp
            })
    if student_averages:
        student_averages_by_marks = sorted(student_averages, key=lambda x: x['avg_marks'], reverse=True)
        prev_avg = None
        rank = 0
        for i, s in enumerate(student_averages_by_marks, 1):
            if s['avg_marks'] != prev_avg:
                rank = i
                prev_avg = s['avg_marks']
            suffix = 'th' if 10 <= rank % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(rank % 10, 'th')
            Result.objects.filter(
                student_id=s['student_id'],
                session=session,
                term=term,
                subject__in=StudentSubject.objects.filter(
                    student_id=s['student_id'],
                    session=session,
                    term=term
                ).values_list('subject_id', flat=True)
            ).update(class_position=f"{rank}{suffix}")
        if section.school_class.section not in ['Nursery', 'Primary']:
            student_averages_by_gp = sorted(student_averages, key=lambda x: x['avg_gp'], reverse=True)
            prev_avg_gp = None
            rank_gp = 0
            for i, s in enumerate(student_averages_by_gp, 1):
                if s['avg_gp'] != prev_avg_gp:
                    rank_gp = i
                    prev_avg_gp = s['avg_gp']
                suffix = 'th' if 10 <= rank_gp % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(rank_gp % 10, 'th')
                Result.objects.filter(
                    student_id=s['student_id'],
                    session=session,
                    term=term,
                    subject__in=StudentSubject.objects.filter(
                        student_id=s['student_id'],
                        session=session,
                        term=term
                    ).values_list('subject_id', flat=True)
                ).update(class_position_gp=f"{rank_gp}{suffix}")
    logger.debug(f"Updated class positions for section {section}")


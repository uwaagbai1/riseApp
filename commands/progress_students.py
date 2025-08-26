from django.core.management.base import BaseCommand
from django.db import transaction
from accounts.models import Student, SchoolClass, ClassSection, Session
from accounts.constants import CLASS_LEVELS

class Command(BaseCommand):
    help = 'Promotes students to the next class level at session end'

    def handle(self, *args, **kwargs):
        current_session = Session.objects.filter(is_active=True).first()
        if not current_session:
            self.stdout.write(self.style.ERROR('No active session found'))
            return

        new_session, _ = Session.objects.get_or_create(
            name=f"{current_session.start_year + 1}/{current_session.end_year + 1}",
            defaults={'start_year': current_session.start_year + 1, 'end_year': current_session.end_year + 1}
        )

        with transaction.atomic():
            for student in Student.objects.all():
                if not student.current_section:
                    continue
                current_level = student.current_section.school_class.level
                if current_level == 'SS 3':
                    continue  # Graduated
                try:
                    current_index = CLASS_LEVELS.index(current_level)
                    next_level = CLASS_LEVELS[current_index + 1]
                except (ValueError, IndexError):
                    continue

                next_class, _ = SchoolClass.objects.get_or_create(level=next_level)
                suffix = student.current_section.suffix
                if next_class.section == 'Senior' and student.specialization:
                    suffix = 'A' if student.specialization == 'Science' else 'B'

                next_section, _ = ClassSection.objects.get_or_create(
                    school_class=next_class,
                    suffix=suffix,
                    session=new_session
                )

                student.current_section = next_section
                student.save()

            current_session.is_active = False
            new_session.is_active = True
            current_session.save()
            new_session.save()

        self.stdout.write(self.style.SUCCESS('Students promoted successfully'))
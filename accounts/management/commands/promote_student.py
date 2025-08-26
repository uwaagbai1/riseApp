from django.core.management.base import BaseCommand
from django.utils import timezone
from accounts.models import Student, SchoolClass, Session, get_current_session_term

class Command(BaseCommand):
    help = 'Promotes students to the next class level at the end of the academic session'

    def handle(self, *args, **kwargs):
        current_session, _ = get_current_session_term()
        next_session = Session.objects.filter(start_year=current_session.start_year + 1).first()
        if not next_session:
            self.stdout.write(self.style.ERROR('Next session not found. Please create it.'))
            return

        students = Student.objects.filter(is_active=True).exclude(current_class__level='SS 3')
        for student in students:
            current_class = student.current_class
            if not current_class:
                self.stdout.write(self.style.WARNING(f'No class assigned for {student.full_name}'))
                continue

            next_class = SchoolClass.objects.filter(
                level_order=current_class.level_order + 1
            ).first()
            if next_class:
                student.current_class = next_class
                student.current_section = None
                student.save()
                self.stdout.write(self.style.SUCCESS(
                    f'Promoted {student.full_name} to {next_class.level}'
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f'No next class found for {student.full_name}'
                ))

        current_session.is_active = False
        current_session.save()
        next_session.is_active = True
        next_session.save()
        self.stdout.write(self.style.SUCCESS('Session updated successfully.'))
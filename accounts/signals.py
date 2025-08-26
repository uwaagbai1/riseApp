from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.contrib.auth import logout
from django.contrib.sessions.models import Session
from django.utils import timezone
from .models import Student

@receiver(pre_save, sender=Student)
def student_token_changed(sender, instance, **kwargs):
    if instance.pk:
        try:
            old_student = Student.objects.get(pk=instance.pk)
            if old_student.token != instance.token:
                if instance.user:
                    sessions = Session.objects.filter(
                        expire_date__gte=timezone.now()
                    )
                    for session in sessions:
                        session_data = session.get_decoded()
                        if str(instance.user.id) == str(session_data.get('_auth_user_id')):
                            session.delete()
                    
                    instance.user.set_password(instance.token)
                    instance.user.save()
        except Student.DoesNotExist:
            pass
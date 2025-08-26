import logging
from django.contrib.auth.backends import BaseBackend, ModelBackend
from django.contrib.auth.models import User
from .models import Student

logger = logging.getLogger(__name__)

class CustomStudentBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            student = Student.objects.get(admission_number=username, token=password)
            if not student.is_active:
                logger.warning(f"Deactivated student {username} attempted login")
                return None
            user, created = User.objects.get_or_create(
                username=student.admission_number,
                defaults={'is_active': True}
            )
            if not student.user:
                student.user = user
                student.save()
            logger.info(f"Authenticated student: {student.admission_number}, user: {user.username}, created: {created}, is_active: {user.is_active}")
            return user
        except Student.DoesNotExist:
            logger.error(f"Student not found for admission_number: {username}")
            return None
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
        
class PhoneNumberBackend(ModelBackend):
    def authenticate(self, request, phone_number=None, password=None, **kwargs):
        try:
            user = User.objects.get(username=phone_number)
            if user.check_password(password):
                return user
        except User.DoesNotExist:
            return None
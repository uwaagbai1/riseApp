import re
import uuid
from django.db import IntegrityError, models, transaction
from django.contrib.auth.models import User
from django.forms import ValidationError
from django.utils.crypto import get_random_string
import random
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from accounts.constants import CLASS_LEVELS, TERM_CHOICES, PAYMENT_STATUS_CHOICES
from django.db.models import Avg, Sum
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from decimal import Decimal
from cloudinary.models import CloudinaryField

class Session(models.Model):
    name = models.CharField(max_length=10, unique=True)
    start_year = models.IntegerField()
    end_year = models.IntegerField()
    is_active = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.is_active:
            Session.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class TermConfiguration(models.Model):
    session = models.ForeignKey(
        'Session',
        on_delete=models.CASCADE,
        related_name='term_configurations',
        null=True,
        blank=True,
        help_text="Optional: Link to a specific session. If null, applies globally."
    )
    term = models.CharField(max_length=1, choices=TERM_CHOICES)
    start_month = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="Month when the term starts (1-12)."
    )
    end_month = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="Month when the term ends (1-12)."
    )
    start_day = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        default=1,
        help_text="Day of the month when the term starts."
    )
    end_day = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        default=28,
        help_text="Day of the month when the term ends."
    )

    class Meta:
        unique_together = ('session', 'term')
        indexes = [
            models.Index(fields=['session', 'term']),
            models.Index(fields=['start_month', 'end_month']),
        ]

    def clean(self):
        if self.start_month > self.end_month:
            raise ValidationError("Start month must be less than or equal to end month.")
        if self.start_day > 31 or self.end_day > 31:
            raise ValidationError("Days must be between 1 and 31.")

    def __str__(self):
        session_name = self.session.name if self.session else "Global"
        return f"{session_name} - Term {self.term} ({self.start_month}/{self.start_day} - {self.end_month}/{self.end_day})"


class SchoolClass(models.Model):
    level = models.CharField(max_length=20, unique=True, choices=[(x, x) for x in CLASS_LEVELS])
    section = models.CharField(max_length=20, choices=[
        ('Nursery', 'Nursery'), ('Primary', 'Primary'), ('Junior', 'Junior'), ('Senior', 'Senior')
    ])
    level_order = models.IntegerField(default=0)        

    def save(self, *args, **kwargs):
        level_mappings = {
            'Creche': ('Nursery', 1),
            'Pre-Nursery': ('Nursery', 2),
            'Nursery 1': ('Nursery', 3),
            'Nursery 2': ('Nursery', 4),
            'Nursery 3': ('Nursery', 5),
            'Primary 1': ('Primary', 6),
            'Primary 2': ('Primary', 7),
            'Primary 3': ('Primary', 8),
            'Primary 4': ('Primary', 9),
            'Primary 5': ('Primary', 10),
            'JSS 1': ('Junior', 11),
            'JSS 2': ('Junior', 12),
            'JSS 3': ('Junior', 13),
            'SS 1': ('Senior', 14),
            'SS 2': ('Senior', 15),
            'SS 3': ('Senior', 16),
        }
        if self.level in level_mappings:
            self.section, self.level_order = level_mappings[self.level]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.level

class ClassSection(models.Model):
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name='sections')
    suffix = models.CharField(max_length=1, choices=[('A', 'A'), ('B', 'B'), ('C', 'C')])
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    teachers = models.ManyToManyField('Teacher', related_name='assigned_sections', blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('school_class', 'suffix', 'session')
        ordering = ['session__start_year', 'school_class__level_order', 'suffix']

    def __str__(self):
        return f"{self.school_class.level}{self.suffix} ({self.session.name})"

    def can_be_modified(self):
        current_year = timezone.now().year
        current_month = timezone.now().month
        current_session_year = current_year if current_month >= 9 else current_year - 1
        return self.session.start_year >= current_session_year

class Subject(models.Model):
    name = models.CharField(max_length=50)
    school_class = models.ManyToManyField(SchoolClass, related_name='subjects')
    section = models.CharField(max_length=20, choices=[
        ('Nursery', 'Nursery'), ('Primary', 'Primary'), ('Junior', 'Junior'), ('Senior', 'Senior')
    ])
    compulsory = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.section})"

class Parent(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='parent')
    phone_number = models.CharField(max_length=15, unique=True, validators=[RegexValidator(r'^\+?\d{8,15}$', 'Phone number must be 8-15 digits, optionally starting with +.')])
    full_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    photo = CloudinaryField('image', folder='riseschools/parent_photos/', null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=['phone_number'])]

    def __str__(self):
        return self.full_name or self.phone_number

    def get_total_fees_for_term(self, session, term):
        """Calculate total fees for all students under this parent for a session and term."""
        students = self.students.filter(is_active=True).select_related('current_class')
        total = Decimal(0)
        for student in students:
            if not student.current_class or not student.current_class.section:
                continue
            # Check for student-specific fee override
            override = StudentFeeOverride.objects.filter(student=student, session=session, term=term).first()
            if override:
                total += override.amount
                continue
            fee = FeeStructure.objects.filter(
                session=session,
                term=term,
                class_level=student.current_class
            ).first()
            total += fee.amount if fee else Decimal(0)
        if term == '1':
            pta_dues = PTADues.objects.filter(session=session, term=term).first()
            total += pta_dues.amount if pta_dues else Decimal('2000.00')
        return total

    def get_payment_status_for_term(self, session, term):
        """Check payment status for a session and term, including refunds."""
        total_fees = self.get_total_fees_for_term(session, term)
        payments = self.payments.filter(session=session, term=term).aggregate(total_paid=Sum('amount'))
        refunds = Refund.objects.filter(parent=self, session=session, term=term).aggregate(total_refunded=Sum('amount'))['total_refunded'] or Decimal(0)
        amount_paid = (payments['total_paid'] or Decimal(0)) - refunds
        return {
            'status': 'Completed' if amount_paid >= total_fees else 'Partial' if amount_paid > 0 else 'Pending',
            'amount_paid': amount_paid,
            'amount_due': max(total_fees - amount_paid, Decimal(0))
        }

    def has_completed_previous_term_payments(self, session, term):
        """Check if all previous terms' payments are completed."""
        if term == '1':
            # For first term, check previous session's third term
            prev_session = Session.objects.filter(end_year=session.start_year-1).first()
            if prev_session:
                prev_status = self.get_payment_status_for_term(prev_session, '3')
                return prev_status['status'] == 'Completed'
            return True  # No previous session, allow payment
        else:
            # For second/third term, check previous term in same session
            prev_term = str(int(term) - 1)
            if prev_term in [t[0] for t in TERM_CHOICES]:
                prev_status = self.get_payment_status_for_term(session, prev_term)
                return prev_status['status'] == 'Completed'
            return True  # No previous term, allow payment

class Student(models.Model):
    admission_number = models.CharField(max_length=7, unique=True, primary_key=True)
    first_name = models.CharField(max_length=50)
    middle_name = models.CharField(max_length=50, blank=True)
    surname = models.CharField(max_length=50)
    date_of_birth = models.DateField()
    address = models.TextField()
    parent_phone = models.CharField(max_length=20, blank=True, null=True)
    gender = models.CharField(max_length=1, choices=[('M', 'Male'), ('F', 'Female')])
    nationality = models.CharField(max_length=100, default='Nigeria')
    enrollment_year = models.CharField(max_length=4, validators=[RegexValidator(r'^\d{4}$')])
    current_class = models.ForeignKey('SchoolClass', on_delete=models.SET_NULL, null=True, related_name='students')
    current_section = models.ForeignKey('ClassSection', on_delete=models.SET_NULL, null=True, blank=True, related_name='students')
    token = models.CharField(max_length=10, unique=True, default=get_random_string(10))
    photo = CloudinaryField('image', folder='riseschools/student_photos/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='student', null=True, blank=True)
    parent = models.ForeignKey('Parent', on_delete=models.SET_NULL, null=True, related_name='students')
    is_active = models.BooleanField(default=True)

    def clean(self):
        if not self.enrollment_year.isdigit() or len(self.enrollment_year) != 4:
            raise ValidationError('Enrollment year must be a 4-digit number.')
        if int(self.enrollment_year) < 1900 or int(self.enrollment_year) > timezone.now().year:
            raise ValidationError('Enrollment year must be between 1900 and the current year.')
        if self.parent_phone and not re.match(r'^\+?\d{8,15}$', self.parent_phone):
            raise ValidationError('Parent phone must be 8-15 digits, optionally starting with +.')
        if self.parent and self.parent_phone and self.parent.phone_number != self.parent_phone:
            raise ValidationError('Parent phone must match the linked parent’s phone number.')

    @transaction.atomic
    def save(self, *args, **kwargs):
        
        if not self.admission_number:
            year = self.enrollment_year
            attempts = 0
            max_attempts = 1000
            while attempts < max_attempts:
                random_id = random.randint(1, 999)
                admission_number = f"{year}{random_id:03d}"  
                if not (Student.objects.filter(admission_number=admission_number).exists() or
                        User.objects.filter(username=admission_number).exists()):
                    self.admission_number = admission_number
                    break
                attempts += 1
            else:
                raise ValidationError(
                    'Unable to generate a unique admission number for the given enrollment year. '
                    'Please try a different enrollment year or contact support.'
                )

        
        if self.parent and not self.parent_phone:
            self.parent_phone = self.parent.phone_number

        
        if not self.token or Student.objects.filter(token=self.token).exclude(pk=self.pk).exists():
            attempts = 0
            max_attempts = 100
            while attempts < max_attempts:
                new_token = get_random_string(10)
                if not Student.objects.filter(token=new_token).exists():
                    self.token = new_token
                    break
                attempts += 1
            else:
                raise ValidationError('Unable to generate a unique token.')

        
        if not self.user:
            username = self.admission_number
            password = self.token
            try:
                self.user = User.objects.create_user(
                    username=username,
                    password=password,
                    is_active=self.is_active,
                    first_name=self.first_name,
                    last_name=self.surname
                )
            except IntegrityError as e:
                raise ValidationError(
                    f'Failed to create user: Username {username} already exists. '
                    'Please try a different enrollment year or contact support.'
                )
        else:
            self.user.is_active = self.is_active  
            self.user.first_name = self.first_name
            self.user.last_name = self.surname
            self.user.save()

        super().save(*args, **kwargs)  

    def regenerate_token(self):
        attempts = 0
        max_attempts = 100
        while attempts < max_attempts:
            new_token = get_random_string(10)
            if not Student.objects.filter(token=new_token).exists():
                self.token = new_token
                self.save()
                if self.user:
                    self.user.set_password(new_token)
                    self.user.save()
                return new_token
            attempts += 1
        raise ValidationError('Failed to generate a unique token.')

    @property
    def full_name(self):
        middle = f" {self.middle_name}" if self.middle_name else ""
        return f"{self.surname} {self.first_name}{middle}"

    def __str__(self):
        return f"{self.full_name} ({self.admission_number})"

    class Meta:
        indexes = [
            models.Index(fields=['admission_number']),
            models.Index(fields=['current_class']),
            models.Index(fields=['current_section']),
            models.Index(fields=['is_active']),
            models.Index(fields=['surname', 'first_name']),
            models.Index(fields=['first_name']),  
            models.Index(fields=['middle_name']),  
            models.Index(fields=['surname']),  
        ]

class Teacher(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    first_name = models.CharField(max_length=50)
    middle_name = models.CharField(max_length=50, blank=True)
    surname = models.CharField(max_length=50)
    school_email = models.EmailField(unique=True)
    gender = models.CharField(max_length=1, choices=[('M', 'Male'), ('F', 'Female')])
    nationality = models.CharField(max_length=100, default='Nigeria')
    photo = CloudinaryField('image', folder='riseschools/teachers_photos/', null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def clean(self):
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', self.school_email):
            raise ValidationError('Invalid email format.')

    def save(self, *args, **kwargs):
        if self.user:
            self.user.is_active = self.is_active
            self.user.first_name = self.first_name
            self.user.last_name = self.surname
            self.user.email = self.school_email
            self.user.save()
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        middle = f" {self.middle_name}" if self.middle_name else ""
        return f"{self.surname} {self.first_name}{middle}"

    def __str__(self):
        return self.full_name

    class Meta:
        indexes = [
            models.Index(fields=['school_email']),
            models.Index(fields=['is_active']),
            models.Index(fields=['surname', 'first_name']),
        ]

from accounts.utils.index import get_current_session_term

class StudentSubject(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='assigned_subjects')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='assigned_students')
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    term = models.CharField(max_length=1, choices=TERM_CHOICES)
    assigned_by = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        current_session, current_term = get_current_session_term()
        if self.session == current_session and self.term == current_term and not self.subject.is_active:
            raise ValidationError(f"Cannot assign inactive subject: {self.subject.name}")
        if self.student.current_class not in self.subject.school_class.all():
            raise ValidationError(f"Subject {self.subject.name} is not available for {self.student.current_class.level}")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ('student', 'subject', 'session', 'term')

    def __str__(self):
        return f"{self.student.full_name} - {self.subject.name} ({self.session.name}, Term {self.term})"

class Result(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='results')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    term = models.CharField(max_length=1, choices=TERM_CHOICES)
    ca = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(10)], default=0.0, blank=True, null=True)
    test_1 = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(10)], default=0.0, blank=True, null=True)
    test_2 = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(10)], default=0.0, blank=True, null=True)
    exam = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(70)], default=0.0, blank=True, null=True)
    test = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(20)], default=0.0, blank=True, null=True)
    homework = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(10)], default=0.0, blank=True, null=True)
    classwork = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(10)], default=0.0, blank=True, null=True)
    nursery_primary_exam = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(60)], default=0.0, blank=True, null=True)
    total_marks = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(100)], default=0.0, blank=True, null=True)
    total_score = models.FloatField(default=0.0)
    grade = models.CharField(max_length=5, blank=True)
    grade_point = models.FloatField(null=True, blank=True)
    description = models.CharField(max_length=50, blank=True)
    subject_position = models.CharField(max_length=10, blank=True)
    class_position = models.CharField(max_length=10, blank=True)
    class_position_gp = models.CharField(max_length=10, blank=True)
    upload_date = models.DateTimeField(null=True, blank=True)
    uploaded_by = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True, blank=True)
    remarks = models.TextField(max_length=500, blank=True, null=True)

    class Meta:
        unique_together = ('student', 'subject', 'session', 'term')
        indexes = [
            models.Index(fields=['session']),
            models.Index(fields=['term']),
            models.Index(fields=['student', 'session', 'term']),
            models.Index(fields=['class_position']),
            models.Index(fields=['class_position_gp']),
        ]

    def clean(self):
        current_session, current_term = get_current_session_term()
        
        if self.session == current_session and self.term == current_term and not self.subject.is_active:
            raise ValidationError(f"Cannot save result for inactive subject: {self.subject.name}")
        if not StudentSubject.objects.filter(
            student=self.student,
            subject=self.subject,
            session=self.session,
            term=self.term
        ).exists():
            raise ValidationError(f"Subject {self.subject.name} is not assigned to {self.student.full_name} for this term")
        
    def save(self, *args, **kwargs):
        section = self.student.current_class.section if self.student.current_class else None
        
        if section == 'Nursery':
            self.total_score = self.total_marks or 0
            if self.total_score >= 95:
                self.grade, self.grade_point, self.description = 'A+', None, 'Distinction'
            elif self.total_score >= 90:
                self.grade, self.grade_point, self.description = 'A', None, 'Excellent'
            elif self.total_score >= 85:
                self.grade, self.grade_point, self.description = 'B+', None, 'Very Good'
            elif self.total_score >= 80:
                self.grade, self.grade_point, self.description = 'B', None, 'Good'
            elif self.total_score >= 70:
                self.grade, self.grade_point, self.description = 'C+', None, 'Credit'
            elif self.total_score >= 65:
                self.grade, self.grade_point, self.description = 'C', None, 'Average'
            elif self.total_score >= 60:
                self.grade, self.grade_point, self.description = 'D', None, 'Fair'
            elif self.total_score >= 50:
                self.grade, self.grade_point, self.description = 'E', None, 'Pass'
            else:
                self.grade, self.grade_point, self.description = 'F9', None, 'Fail'
        elif section == 'Primary':
            self.total_score = (self.test or 0) + (self.homework or 0) + (self.classwork or 0) + (self.nursery_primary_exam or 0)
            if self.total_score >= 95:
                self.grade, self.grade_point, self.description = 'A+', None, 'Distinction'
            elif self.total_score >= 90:
                self.grade, self.grade_point, self.description = 'A', None, 'Excellent'
            elif self.total_score >= 85:
                self.grade, self.grade_point, self.description = 'B+', None, 'Very Good'
            elif self.total_score >= 80:
                self.grade, self.grade_point, self.description = 'B', None, 'Good'
            elif self.total_score >= 70:
                self.grade, self.grade_point, self.description = 'C+', None, 'Credit'
            elif self.total_score >= 65:
                self.grade, self.grade_point, self.description = 'C', None, 'Average'
            elif self.total_score >= 60:
                self.grade, self.grade_point, self.description = 'D', None, 'Fair'
            elif self.total_score >= 50:
                self.grade, self.grade_point, self.description = 'E', None, 'Pass'
            else:
                self.grade, self.grade_point, self.description = 'F9', None, 'Fail'
        elif section == 'Junior':
            self.total_score = (self.ca or 0) + (self.test_1 or 0) + (self.test_2 or 0) + (self.exam or 0)
            if self.total_score >= 90:
                self.grade, self.grade_point, self.description = 'A+', 4.0, 'Distinction'
            elif self.total_score >= 80:
                self.grade, self.grade_point, self.description = 'A', 3.5, 'Excellent'
            elif self.total_score >= 70:
                self.grade, self.grade_point, self.description = 'B', 3.0, 'Good'
            elif self.total_score >= 60:
                self.grade, self.grade_point, self.description = 'C', 2.5, 'Above Average'
            elif self.total_score >= 50:
                self.grade, self.grade_point, self.description = 'D', 2.0, 'Average'
            elif self.total_score >= 40:
                self.grade, self.grade_point, self.description = 'E', 1.5, 'Average'
            else:
                self.grade, self.grade_point, self.description = 'F', 1.0, 'Poor'
        else:
            self.total_score = (self.ca or 0) + (self.test_1 or 0) + (self.test_2 or 0) + (self.exam or 0)
            if self.total_score >= 90:
                self.grade, self.grade_point, self.description = 'A1', 5.0, 'Distinction'
            elif self.total_score >= 85:
                self.grade, self.grade_point, self.description = 'B2', 4.5, 'Excellent'
            elif self.total_score >= 80:
                self.grade, self.grade_point, self.description = 'B3', 4.0, 'Very Good'
            elif self.total_score >= 70:
                self.grade, self.grade_point, self.description = 'C4', 3.5, 'Good'
            elif self.total_score >= 60:
                self.grade, self.grade_point, self.description = 'C5', 3.0, 'Above Avg.'
            elif self.total_score >= 50:
                self.grade, self.grade_point, self.description = 'C6', 2.5, 'Average'
            elif self.total_score >= 45:
                self.grade, self.grade_point, self.description = 'D7', 2.0, 'Below Avg.'
            elif self.total_score >= 40:
                self.grade, self.grade_point, self.description = 'E8', 1.5, 'Fair'
            else:
                self.grade, self.grade_point, self.description = 'F9', 1.0, 'Fail'

        if self.remarks:
            self.remarks = self.remarks.strip()
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student.full_name} - {self.subject.name} - {self.session.name} - Term {self.term}"
    
    def is_editable(self):
        term_end_dates = {
            '1': f"{self.session.end_year}-12-31",
            '2': f"{self.session.end_year}-04-30",
            '3': f"{self.session.end_year}-08-31",
        }
        term_end = timezone.datetime.strptime(term_end_dates.get(self.term), "%Y-%m-%d").date()
        return timezone.now().date() <= term_end

class StudentClassHistory(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='class_history')
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    term = models.CharField(max_length=1, choices=TERM_CHOICES)
    class_level = models.ForeignKey(SchoolClass, on_delete=models.SET_NULL, null=True, blank=True)
    section = models.ForeignKey(ClassSection, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('student', 'session', 'term')
        indexes = [
            models.Index(fields=['student', 'session', 'term']),
            models.Index(fields=['session']),
            models.Index(fields=['term']),
        ]
        verbose_name_plural = 'Student Class Histories'

    def clean(self):
        if self.class_level and self.section and self.section.school_class != self.class_level:
            raise ValidationError("Section must belong to the specified class level.")
        if self.section and self.section.session != self.session:
            raise ValidationError("Section must belong to the specified session.")

    def __str__(self):
        return f"{self.student.full_name} - {self.session.name} Term {self.term}"

class ResultAccessRequest(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    term = models.CharField(max_length=10, choices=[('1', 'First'), ('2', 'Second'), ('3', 'Third')])
    status = models.CharField(
        max_length=20,
        choices=[('Pending', 'Pending'), ('Approved', 'Approved'), ('Denied', 'Denied')],
        default='Pending'
    )
    requested_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    handled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        unique_together = ('student', 'session', 'term')
        ordering = ['-requested_at']

    def __str__(self):
        return f"{self.student.full_name} - {self.session.name} Term {self.get_term_display()}"

class PTADues(models.Model):
    session = models.ForeignKey('Session', on_delete=models.CASCADE, related_name='pta_dues')
    term = models.CharField(max_length=1, choices=TERM_CHOICES, default='1')
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=Decimal('2000.00'),
        help_text="PTA dues amount for this session and term (in XOF)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session', 'term')
        indexes = [
            models.Index(fields=['session', 'term']),
        ]

    def __str__(self):
        return f"PTA Dues - {self.session.name} Term {self.term} - {self.amount} XOF"
    
class FeeStructure(models.Model):
    session = models.ForeignKey('Session', on_delete=models.CASCADE, related_name='fee_structures')
    term = models.CharField(max_length=1, choices=TERM_CHOICES)
    class_level = models.ForeignKey(SchoolClass, on_delete=models.CASCADE)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Fee amount for this class level, session, and term (in XOF)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session', 'term', 'class_level')
        indexes = [
            models.Index(fields=['session', 'term', 'class_level']),
        ]

    def __str__(self):
        return f"{self.class_level.level} - {self.session.name} Term {self.term} - {self.amount} XOF"

class StudentFeeOverride(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='fee_overrides')
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    term = models.CharField(max_length=1, choices=TERM_CHOICES)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Custom fee amount for this student, session, and term (in XOF)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        unique_together = ('student', 'session', 'term')
        indexes = [
            models.Index(fields=['student', 'session', 'term']),
        ]

    def __str__(self):
        return f"{self.student.full_name} - {self.session.name} Term {self.term} - {self.amount} XOF"

class Refund(models.Model):
    parent = models.ForeignKey(Parent, on_delete=models.CASCADE, related_name='refunds')
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    term = models.CharField(max_length=1, choices=TERM_CHOICES)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Refund amount for this parent, session, and term (in XOF)"
    )
    reason = models.TextField(default="Fee reduction overpayment")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['parent', 'session', 'term']),
        ]

    def __str__(self):
        return f"Refund {self.amount} XOF for {self.parent.full_name} - {self.session.name} Term {self.term}"

class Payment(models.Model):
    parent = models.ForeignKey(Parent, on_delete=models.CASCADE, related_name='payments')
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    term = models.CharField(max_length=1, choices=TERM_CHOICES)
    students = models.ManyToManyField(Student, related_name='payments', blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    transaction_id = models.CharField(max_length=36, unique=True, default=uuid.uuid4)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        student_names = ", ".join([student.full_name for student in self.students.all()])
        return f"{self.parent.full_name} - {self.amount} XOF for {student_names} ({self.session.name} Term {self.term})"

    class Meta:
        indexes = [
            models.Index(fields=['transaction_id']),
            models.Index(fields=['parent', 'session', 'term']),
        ]

    def calculate_total_fee(self):
        """Calculate total fee based on students' class levels, including overrides."""
        total = Decimal('0')
        for student in self.students.select_related('current_class').all():
            if not student.current_class:
                continue
            override = StudentFeeOverride.objects.filter(student=student, session=self.session, term=self.term).first()
            if override:
                total += override.amount
                continue
            fee = FeeStructure.objects.filter(
                session=self.session,
                term=self.term,
                class_level=student.current_class
            ).first()
            total += fee.amount if fee else Decimal('0')
        if self.term == '1':
            pta_dues = PTADues.objects.filter(session=self.session, term=self.term).first()
            total += pta_dues.amount if pta_dues else Decimal('2000.00')
        return total

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = str(uuid.uuid4())
        super().save(*args, **kwargs)

class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification for {self.user.username}"
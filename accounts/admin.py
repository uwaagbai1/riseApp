from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Value as V
from django import forms
from django.contrib.admin.helpers import ActionForm
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.utils.crypto import get_random_string

from .models import (
    FeeStructure, Parent, Session, SchoolClass, ClassSection, StudentClassHistory, Subject, Student,
    Teacher, StudentSubject, Result, Payment, Notification, TermConfiguration
)

TERM_CHOICES = (
    ('1', 'First Term'),
    ('2', 'Second Term'),
    ('3', 'Third Term'),
)

class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 
                    'is_teacher', 'is_student', 'is_active')
    list_filter = ('is_staff', 'is_active', 'is_superuser')
    
    def is_teacher(self, obj):
        return hasattr(obj, 'teacher')
    is_teacher.boolean = True
    is_teacher.short_description = 'Teacher'
    
    def is_student(self, obj):
        return hasattr(obj, 'student')
    is_student.boolean = True
    is_student.short_description = 'Student'

admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


class BulkActionForm(ActionForm):
    session = forms.ModelChoiceField(
        queryset=Session.objects.all(),
        required=False,
        label='Apply to Session'
    )
    term = forms.ChoiceField(
        choices=(('', '---------'),) + TERM_CHOICES,
        required=False,
        label='Apply to Term'
    )


class SchoolAdminMixin:
    list_per_page = 50
    action_form = BulkActionForm
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if hasattr(request.user, 'teacher'):
            return qs.filter(assigned_by=request.user.teacher)
        return qs.none()

@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_year', 'end_year', 'is_active', 'student_count')
    list_editable = ('is_active',)
    search_fields = ('name',)
    actions = ['make_active']
    
    def student_count(self, obj):
        
        from django.db.models import Count
        return obj.result_set.aggregate(count=Count('student', distinct=True))['count']
        
        
    student_count.short_description = 'Students'
    
    def make_active(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Please select exactly one session to activate.", level=messages.ERROR)
            return
        session = queryset.first()
        session.is_active = True
        session.save()
        self.message_user(request, f"Session {session.name} is now active.")
    make_active.short_description = "Mark selected session as active"

@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ('level', 'section', 'student_count', 'subject_count')
    list_filter = ('section',)
    search_fields = ('level',)
    
    def student_count(self, obj):
        return obj.students.count()
    student_count.short_description = 'Students'
    
    def subject_count(self, obj):
        return obj.subjects.count()
    subject_count.short_description = 'Subjects'

class TeacherInline(admin.TabularInline):
    model = ClassSection.teachers.through
    extra = 1
    verbose_name = 'Teacher'
    verbose_name_plural = 'Teachers'

@admin.register(ClassSection)
class ClassSectionAdmin(SchoolAdminMixin, admin.ModelAdmin):
    list_display = ('__str__', 'school_class', 'session', 'teacher_list', 'student_count')
    list_filter = ('school_class__section', 'school_class', 'session')
    search_fields = ('school_class__level', 'suffix')
    filter_horizontal = ('teachers',)
    inlines = [TeacherInline]
    autocomplete_fields = ['school_class', 'session']
    
    def teacher_list(self, obj):
        return ", ".join([t.full_name for t in obj.teachers.all()])
    teacher_list.short_description = 'Teachers'
    
    def student_count(self, obj):
        return obj.students.count()
    student_count.short_description = 'Students'

@admin.register(Subject)
class SubjectAdmin(SchoolAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'section', 'compulsory', 'is_active', 'class_list')
    list_filter = ('section', 'compulsory', 'is_active')
    search_fields = ('name',)
    list_editable = ('is_active',)
    filter_horizontal = ('school_class',)
    
    def class_list(self, obj):
        classes = obj.school_class.all().order_by('level')
        return ", ".join([c.level for c in classes])
    class_list.short_description = 'Classes'

class StudentSubjectInline(admin.TabularInline):
    model = StudentSubject
    extra = 0
    autocomplete_fields = ['subject']
    fields = ('subject', 'term', 'session', 'assigned_by', 'assigned_at')
    readonly_fields = ('assigned_by', 'assigned_at')

class ResultInline(admin.TabularInline):
    model = Result
    extra = 0
    fields = ('subject', 'term', 'total_score', 'grade', 'uploaded_by')
    readonly_fields = ('uploaded_by',)
    show_change_link = True

class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ('session', 'term', 'amount', 'status', 'created_at')
    readonly_fields = ('created_at',)

@admin.register(Student)
class StudentAdmin(SchoolAdminMixin, admin.ModelAdmin):
    list_display = ('admission_number', 'full_name', 'current_class', 'current_section', 
                    'gender', 'enrollment_year', 'is_active', 'view_results_link')
    list_filter = ('current_class__section', 'current_class', 'gender', 'is_active')
    search_fields = ('full_name', 'admission_number', 'parent_phone')
    list_editable = ('is_active',)
    readonly_fields = ('token', 'created_at', 'photo_preview')
    fieldsets = (
        (None, {
            'fields': ('full_name', 'date_of_birth', 'gender')
        }),
        ('Contact Information', {
            'fields': ('address', 'parent_phone')
        }),
        ('Academic Information', {
            'fields': ('enrollment_year', 'current_class', 'current_section')
        }),
        ('Account Information', {
            'fields': ('token', 'photo', 'photo_preview', 'is_active', 'created_at')
        }),
    )
    
    actions = ['promote_students', 'generate_login_tokens']
    
    def photo_preview(self, obj):
        if obj.photo:
            return format_html('<img src="{}" style="max-height: 200px;"/>', obj.photo.url)
        return "-"
    photo_preview.short_description = 'Photo Preview'
    
    def view_results_link(self, obj):
        url = reverse('admin:accounts_result_changelist') + f'?student__admission_number__exact={obj.admission_number}'
        return format_html('<a href="{}">View Results</a>', url)
    view_results_link.short_description = 'Results'
    
    def promote_students(self, request, queryset):
        from django.urls import reverse
        return HttpResponseRedirect(
            reverse('admin:promote_students') + 
            f'?ids={",".join([str(s.pk) for s in queryset])}'
        )
    promote_students.short_description = "Promote selected students"
    
    def generate_login_tokens(self, request, queryset):
        for student in queryset:
            student.token = get_random_string(10)
            student.save()
        self.message_user(request, f"Generated new login tokens for {queryset.count()} students.")
    generate_login_tokens.short_description = "Generate new login tokens"

@admin.register(Teacher)
class TeacherAdmin(SchoolAdminMixin, admin.ModelAdmin):
    list_display = ('full_name', 'school_email', 'is_active', 'section_count', 'photo_preview')
    search_fields = ('full_name', 'school_email')
    list_editable = ('is_active',)
    readonly_fields = ('photo_preview',)
    filter_horizontal = ('assigned_sections',)
    
    def photo_preview(self, obj):
        if obj.photo:
            return format_html('<img src="{}" style="max-height: 200px;"/>', obj.photo.url)
        return "-"
    photo_preview.short_description = 'Photo Preview'
    
    def section_count(self, obj):
        return obj.assigned_sections.count()
    section_count.short_description = 'Sections'

@admin.register(StudentSubject)
class StudentSubjectAdmin(SchoolAdminMixin, admin.ModelAdmin):
    list_display = ('student', 'subject', 'session', 'term', 'assigned_by', 'assigned_at')
    list_filter = ('subject__section', 'subject', 'session', 'term')
    search_fields = ('student__full_name', 'student__admission_number', 'subject__name')
    autocomplete_fields = ['student', 'subject', 'session', 'assigned_by']
    readonly_fields = ('assigned_at',)
    
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'term':
            kwargs['choices'] = TERM_CHOICES
        return super().formfield_for_dbfield(db_field, request, **kwargs)
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.assigned_by = request.user.teacher if hasattr(request.user, 'teacher') else None
        super().save_model(request, obj, form, change)
      
@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    
    def has_add_permission(self, request):
        return False

    
    readonly_fields = [f.name for f in Result._meta.fields]
    
    
    list_display = ('student', 'subject', 'session', 'term', 'total_score', 'grade')
    list_filter = ('subject__section', 'subject', 'session', 'term', 'grade')
    search_fields = ('student__full_name', 'student__admission_number', 'subject__name')
    list_select_related = ('student', 'subject', 'session')

@admin.register(Payment)
class PaymentAdmin(SchoolAdminMixin, admin.ModelAdmin):
    list_display = ('parent', 'session', 'term', 'amount', 'status', 'created_at')
    list_filter = ('session', 'term', 'status')
    search_fields = ('parent__full_name', 'transaction_id')
    readonly_fields = ('created_at', 'transaction_id')
    list_editable = ('status',)
    autocomplete_fields = ['parent', 'session']

@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ('class_level', 'session', 'term', 'amount', 'created_at', 'updated_at')
    list_filter = ('session', 'term', 'class_level')
    search_fields = ('class_level__level', 'session__name', 'term')
    ordering = ('session__start_year', 'term', 'class_level__level')
    list_editable = ('amount',)
    list_per_page = 25

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('session', 'class_level')
    
@admin.register(Parent)
class ParentAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone_number', 'email', 'is_active')
    search_fields = ('full_name', 'phone_number', 'email')
    list_filter = ('is_active',)
    autocomplete_fields = ['user']
    
@admin.register(Notification)
class NotificationAdmin(SchoolAdminMixin, admin.ModelAdmin):
    list_display = ('user', 'short_message', 'read', 'created_at')
    list_filter = ('read', 'user')
    search_fields = ('message', 'user__username')
    list_editable = ('read',)
    
    def short_message(self, obj):
        return obj.message[:50] + '...' if len(obj.message) > 50 else obj.message
    short_message.short_description = 'Message'

@admin.register(TermConfiguration)
class TermConfigurationAdmin(admin.ModelAdmin):
    list_display = ('session', 'term', 'start_month', 'start_day', 'end_month', 'end_day')
    list_filter = ('session', 'term')
    search_fields = ('session__name', 'term')
    ordering = ('session__start_year', 'term')

@admin.register(StudentClassHistory)
class StudentClassHistoryAdmin(admin.ModelAdmin):
    list_display = ('student', 'session', 'term', 'class_level', 'section', 'created_at')
    list_filter = ('session', 'term', 'class_level', 'section')
    search_fields = ('student__full_name', 'student__admission_number')
    date_hierarchy = 'created_at'

from django.contrib import admin
from accounts.models import PTADues

from django.contrib import admin
from accounts.models import PTADues

@admin.register(PTADues)
class PTADuesAdmin(admin.ModelAdmin):
    list_display = ('session', 'term', 'amount', 'created_at', 'updated_at')
    list_filter = ('session', 'term')
    search_fields = ('session__name', 'term')
    ordering = ('-session__start_year', 'term')
    fieldsets = (
        (None, {
            'fields': ('session', 'term', 'amount')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    readonly_fields = ('created_at', 'updated_at')
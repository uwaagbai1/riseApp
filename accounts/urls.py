from django.urls import path

from accounts.views.base import *
from accounts.views.admin import *
from accounts.views.parent import *
from accounts.views.student import *
from accounts.views.teacher import *

urlpatterns = [

    # General
    path('test-session-term/', test_session_term, name='test_session_term'),
    path('dashboard/', dashboard, name='dashboard'),
    path('profile/', profile, name='profile'),

    # Admin and Teacher
    path('student/details/<str:admission_number>/', student_detail, name='student_detail'),

    # Admin & Specific Teacher
    path('payment/receipt/<int:payment_id>/', generate_payment_receipt, name='generate_payment_receipt'),

    # Auth
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    
    # Students
    path('student/grades/', student_grades, name='student_grades'),
    path('student/request-result-access/', student_request_result_access, name='student_request_result_access'),
    path('student/subjects/', student_view_subjects, name='student_view_subjects'),
    path('student/export/current-results/', export_current_term_results_pdf, name='export_current_results_pdf'),
    path('student/export/past-results/<int:session_id>/<str:term>/', export_past_term_results_pdf, name='export_past_results_pdf'),
    
    # Teachers
    path('teacher/view-students/', teacher_view_students, name='teacher_view_students'),
    path('teacher/student/<str:admission_number>/update_result/', update_result, name='update_result'),
    path('teacher/class-results/', teacher_view_class_results, name='teacher_view_class_results'),
    path('teacher/manage-subjects/', teacher_manage_subjects, name='teacher_manage_subjects'),
    path('teacher/assign-student/', assign_student_to_section, name='assign_student_to_section'),
    path('teacher/remove-student/', remove_student_from_section, name='remove_student_from_section'),
    path('teacher/generate-student-token/', generate_student_token, name='generate_student_token'),
    path('teacher/student/<str:admission_number>/past-results/', teacher_view_student_past_results, name='teacher_view_student_past_results'),
    
    # Parent
    path('parent/child/<str:admission_number>/grades/', parent_view_child_grades, name='parent_view_child_grades'),
    path('parent/children', parent_view_children, name='parent_view_children'),
    path('parent/payments/', parent_payments, name='parent_payments'),
    path('parent/payments/<int:session_id>/<str:term>/', parent_payment_detail, name='parent_payment_detail'),
    path('parent/request-result-access/<str:admission_number>/', parent_request_result_access, name='parent_request_result_access'),
    path('parent/export-current-results/<str:admission_number>/', parent_export_current_results_pdf, name='parent_export_current_results_pdf'),
    path('parent/export-past-results/<str:admission_number>/<int:session_id>/<str:term>/',parent_export_past_results_pdf,name='parent_export_past_results_pdf'),

    # Admins
    path('admin/students/', admin_student_management, name='admin_student_management'),
    path('admin/filter_students/', filter_students, name='filter_students'),
    path('admin/teachers/filter/', filter_teachers, name='filter_teachers'),
    path('admin/manage-result-access-requests/', admin_manage_result_access_requests, name='admin_manage_result_access_requests'),
    path('admin/result-access-request/', admin_handle_result_access_request, name='admin_handle_result_access_request'),
    path('admin/promote-students/', promote_students, name='promote_students'),
    path('admin/student/<str:admission_number>/update/', update_student, name='update_student'),
    path('get-students-by-phone/', get_students_by_phone, name='get_students_by_phone'),
    path('admin/teachers/', admin_teacher_management, name='admin_teacher_management'),
    path('admin/teachers/<int:teacher_id>/assign-sections/', assign_teacher_to_section, name='assign_teacher_to_section'),
    path('admin/sections/', admin_manage_sections, name='admin_manage_sections'),
    path('admin/sections/<int:section_id>/update/', admin_update_section, name='admin_update_section'),
    path('admin/subjects/', admin_manage_subjects, name='admin_manage_subjects'),
    path('admin/subjects/filter/', filter_subjects, name='filter_subjects'),
    path('admin/subjects/get/', get_subject, name='get_subject'),
    path('admin/statistics/', admin_statistics, name='admin_statistics'),
    path('admin/student/<str:admission_number>/results/<int:session_id>/<str:term>/', admin_view_student_results, name='admin_view_student_results'),
    path('admin/result-tracking/', admin_result_tracking, name='admin_result_tracking'),
    path('admin/class-results/<int:section_id>/<int:session_id>/<str:term>/', view_class_results, name='view_class_results'),
    path('admin/payment-report/', admin_payment_report, name='admin_payment_report'),
    path('admin/payment-report-pdf/', admin_payment_report_pdf, name='admin_payment_report_pdf'),
    path('admin/fee-statistics/', admin_fee_statistics, name='admin_fee_statistics'),
    path('admin/fee-statistics-pdf/', admin_fee_statistics_pdf, name='admin_fee_statistics_pdf'),
    path('admin/daily-payment-report/', admin_daily_payment_report, name='admin_daily_payment_report'),
    path('admin/daily-payment-report-pdf/', admin_daily_payment_report_pdf, name='admin_daily_payment_report_pdf'),
    path('admin/payments/create/', admin_create_payment, name='admin_create_payment'),
    path('admin/search-family/', search_family_by_student_name, name='search_family_by_student_name'),
    path('admin/students/search-parents/', search_parents, name='search_parents'),
    path('edit-student-fee/', admin_edit_student_fee, name='admin_edit_student_fee'),
    # API
    path('api/get-class-sections/', get_class_sections, name='get_class_sections'),    

]
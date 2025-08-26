
from django.db import migrations
from django.utils import timezone
from accounts.constants import (
    PRE_NURSERY_SUBJECTS, NURSERY_1_2_SUBJECTS, NURSERY_3_SUBJECTS,
    PRIMARY_SUBJECTS, JSS_SUBJECTS, SSS_SUBJECTS, CLASS_LEVELS
)

def populate_sessions(apps, schema_editor):
    Session = apps.get_model('accounts', 'Session')
    
    current_year = timezone.now().year
    current_month = timezone.now().month
    session_start_year = current_year if current_month >= 9 else current_year - 1
    
    for i in range(3):
        year = session_start_year + i
        session_name = f"{year}/{year + 1}"
        is_active = (i == 0)
        
        Session.objects.get_or_create(
            name=session_name,
            defaults={
                'start_year': year,
                'end_year': year + 1,
                'is_active': is_active
            }
        )

def populate_classes_and_subjects(apps, schema_editor):
    SchoolClass = apps.get_model('accounts', 'SchoolClass')
    Subject = apps.get_model('accounts', 'Subject')
    Session = apps.get_model('accounts', 'Session')
    ClassSection = apps.get_model('accounts', 'ClassSection')
    
    
    for level in CLASS_LEVELS:
        section = (
            'Nursery' if level in ['Creche', 'Pre-Nursery', 'Nursery 1', 'Nursery 2', 'Nursery 3'] else
            'Primary' if level.startswith('Primary') else
            'Junior' if level.startswith('JSS') else
            'Senior'
        )
        SchoolClass.objects.get_or_create(level=level, defaults={'section': section})
    
    
    active_session = Session.objects.filter(is_active=True).first()
    if active_session:
        for school_class in SchoolClass.objects.all():
            for suffix in ['A', 'B']:
                ClassSection.objects.get_or_create(
                    school_class=school_class,
                    suffix=suffix,
                    session=active_session
                )
    
    
    pre_nursery_class = SchoolClass.objects.get(level='Pre-Nursery')
    nursery_1_class = SchoolClass.objects.get(level='Nursery 1')
    nursery_2_class = SchoolClass.objects.get(level='Nursery 2')
    nursery_3_class = SchoolClass.objects.get(level='Nursery 3')
    primary_classes = SchoolClass.objects.filter(section='Primary')
    jss_classes = SchoolClass.objects.filter(section='Junior')
    sss_classes = SchoolClass.objects.filter(section='Senior')
    
    
    for subject_data in PRE_NURSERY_SUBJECTS:
        subject, created = Subject.objects.get_or_create(
            name=subject_data['name'],
            section=subject_data['section'],
            defaults={'compulsory': subject_data['compulsory']}
        )
        subject.school_class.add(pre_nursery_class)
    
    
    for subject_data in NURSERY_1_2_SUBJECTS:
        subject, created = Subject.objects.get_or_create(
            name=subject_data['name'],
            section=subject_data['section'],
            defaults={'compulsory': subject_data['compulsory']}
        )
        subject.school_class.add(nursery_1_class, nursery_2_class)
    
    
    for subject_data in NURSERY_3_SUBJECTS:
        subject, created = Subject.objects.get_or_create(
            name=subject_data['name'],
            section=subject_data['section'],
            defaults={'compulsory': subject_data['compulsory']}
        )
        subject.school_class.add(nursery_3_class)
    
    
    for subject_data in PRIMARY_SUBJECTS:
        subject, created = Subject.objects.get_or_create(
            name=subject_data['name'],
            section=subject_data['section'],
            defaults={'compulsory': subject_data['compulsory']}
        )
        for primary_class in primary_classes:
            subject.school_class.add(primary_class)
    
    
    for subject_data in JSS_SUBJECTS:
        subject, created = Subject.objects.get_or_create(
            name=subject_data['name'],
            section=subject_data['section'],
            defaults={'compulsory': subject_data['compulsory']}
        )
        for jss_class in jss_classes:
            subject.school_class.add(jss_class)
    
    
    for subject_data in SSS_SUBJECTS:
        subject, created = Subject.objects.get_or_create(
            name=subject_data['name'],
            section=subject_data['section'],
            defaults={'compulsory': subject_data['compulsory']}
        )
        for sss_class in sss_classes:
            subject.school_class.add(sss_class)

class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ('accounts', '0001_initial'),
    ]
    operations = [
        migrations.RunPython(populate_sessions, reverse_code=migrations.RunPython.noop),
        migrations.RunPython(populate_classes_and_subjects, reverse_code=migrations.RunPython.noop),
    ]
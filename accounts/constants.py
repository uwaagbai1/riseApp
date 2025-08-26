CLASS_LEVELS = [
    'Creche', 'Pre-Nursery', 'Nursery 1', 'Nursery 2', 'Nursery 3',
    'Primary 1', 'Primary 2', 'Primary 3', 'Primary 4', 'Primary 5',
    'JSS 1', 'JSS 2', 'JSS 3',
    'SS 1', 'SS 2', 'SS 3'
]

TERM_CHOICES = (
    ('1', 'First Term'),
    ('2', 'Second Term'),
    ('3', 'Third Term'),
)

PAYMENT_STATUS_CHOICES = (
    ('Pending', 'Pending'),
    ('Completed', 'Completed'),
    ('Failed', 'Failed'),
)

PRE_NURSERY_SUBJECTS = [
    {'name': 'English Language', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Mathematics', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Health Habits', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Bible Story', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Social Habits', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Science', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Fine Arts', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Story/Rhyme', 'section': 'Nursery', 'compulsory': True},
]

NURSERY_1_2_SUBJECTS = [
    {'name': 'English Language', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Mathematics', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Verbal Reasoning', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Quantitative Reasoning', 'section': 'Nursery', 'compulsory': True},
    {'name': 'French', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Bible Story', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Social Habits', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Science', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Fine Arts', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Phonics', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Story/Rhyme', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Writing', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Reading', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Health Habits', 'section': 'Nursery', 'compulsory': True},
]

NURSERY_3_SUBJECTS = [
    {'name': 'English Language', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Mathematics', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Verbal Reasoning', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Quantitative Reasoning', 'section': 'Nursery', 'compulsory': True},
    {'name': 'French', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Christian Religious Knowledge', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Social Studies', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Basic Science and Technology', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Civic Education', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Cultural and Creative Arts', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Phonics', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Story/Rhyme', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Writing', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Reading', 'section': 'Nursery', 'compulsory': True},
    {'name': 'Igbo', 'section': 'Nursery', 'compulsory': False},
    {'name': 'Physical and Health Education', 'section': 'Nursery', 'compulsory': True},
]

PRIMARY_SUBJECTS = [
    {'name': 'Mathematics', 'section': 'Primary', 'compulsory': True},
    {'name': 'English Language', 'section': 'Primary', 'compulsory': True},
    {'name': 'Basic Science and Technology', 'section': 'Primary', 'compulsory': True},
    {'name': 'Social Studies', 'section': 'Primary', 'compulsory': True},
    {'name': 'Civic Education', 'section': 'Primary', 'compulsory': True},
    {'name': 'Christian Religious Studies', 'section': 'Primary', 'compulsory': True},
    {'name': 'Creative Arts', 'section': 'Primary', 'compulsory': True},
    {'name': 'Agricultural Science', 'section': 'Primary', 'compulsory': True},
    {'name': 'French', 'section': 'Primary', 'compulsory': True},
    {'name': 'Physical and Health Education', 'section': 'Primary', 'compulsory': True},
    {'name': 'Home Economics', 'section': 'Primary', 'compulsory': True},
    {'name': 'Verbal Reasoning', 'section': 'Primary', 'compulsory': True},
    {'name': 'Quantitative Reasoning', 'section': 'Primary', 'compulsory': True},
    {'name': 'Igbo', 'section': 'Primary', 'compulsory': False},
    {'name': 'Computer Studies', 'section': 'Primary', 'compulsory': True},
]

JSS_SUBJECTS = [
    {'name': 'Mathematics', 'section': 'Junior', 'compulsory': True},
    {'name': 'English Language', 'section': 'Junior', 'compulsory': True},
    {'name': 'Basic Science', 'section': 'Junior', 'compulsory': True},
    {'name': 'Social Studies', 'section': 'Junior', 'compulsory': True},
    {'name': 'Civic Education', 'section': 'Junior', 'compulsory': True},
    {'name': 'Christian Religious Studies', 'section': 'Junior', 'compulsory': True},
    {'name': 'Business Studies', 'section': 'Junior', 'compulsory': True},
    {'name': 'Basic Technology', 'section': 'Junior', 'compulsory': True},
    {'name': 'Agricultural Science', 'section': 'Junior', 'compulsory': True},
    {'name': 'French', 'section': 'Junior', 'compulsory': True},
    {'name': 'Physical and Health Education', 'section': 'Junior', 'compulsory': True},
    {'name': 'Home Economics', 'section': 'Junior', 'compulsory': True},
    {'name': 'Cultural and Creative Arts', 'section': 'Junior', 'compulsory': True},
    {'name': 'Igbo', 'section': 'Junior', 'compulsory': False},
    {'name': 'Computer Science', 'section': 'Junior', 'compulsory': True},
    {'name': 'Security Education', 'section': 'Junior', 'compulsory': True},
    {'name': 'History', 'section': 'Junior', 'compulsory': True},
]

SSS_SUBJECTS = [
    {'name': 'Mathematics', 'section': 'Senior', 'compulsory': True},
    {'name': 'English Language', 'section': 'Senior', 'compulsory': True},
    {'name': 'Civic Education', 'section': 'Senior', 'compulsory': True},
    {'name': 'Economics', 'section': 'Senior', 'compulsory': True},
    {'name': 'Computer Science/ICT', 'section': 'Senior', 'compulsory': True},
    {'name': 'Marketing', 'section': 'Senior', 'compulsory': True},
    {'name': 'Physics', 'section': 'Senior', 'compulsory': False},
    {'name': 'Chemistry', 'section': 'Senior', 'compulsory': False},
    {'name': 'Biology', 'section': 'Senior', 'compulsory': False},
    {'name': 'Literature in English', 'section': 'Senior', 'compulsory': False},
    {'name': 'Government', 'section': 'Senior', 'compulsory': False},
    {'name': 'Christian Religious Studies', 'section': 'Senior', 'compulsory': False},
    {'name': 'Accounting', 'section': 'Senior', 'compulsory': False},
    {'name': 'Commerce', 'section': 'Senior', 'compulsory': False},
    {'name': 'Igbo', 'section': 'Senior', 'compulsory': False},
    {'name': 'French', 'section': 'Senior', 'compulsory': False},
]
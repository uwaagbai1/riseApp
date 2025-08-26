import csv
import os
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from accounts.models import Student, SchoolClass, Parent
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Import students from CSV file'

    def add_arguments(self, parser):
        parser.add_argument(
            'csv_file',
            type=str,
            help='Path to the CSV file containing student data'
        )
        parser.add_argument(
            '--delete-file',
            action='store_true',
            help='Delete the CSV file after successful import',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Number of records to process in each batch (default: 100)',
        )

    def handle(self, *args, **options):
        csv_file_path = options['csv_file']
        delete_file = options['delete_file']
        batch_size = options['batch_size']

        if not os.path.exists(csv_file_path):
            self.stdout.write(
                self.style.ERROR(f'CSV file not found: {csv_file_path}')
            )
            return

        try:
            self.import_students(csv_file_path, batch_size)
            
            if delete_file:
                os.remove(csv_file_path)
                self.stdout.write(
                    self.style.SUCCESS(f'CSV file deleted: {csv_file_path}')
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Import failed: {str(e)}')
            )
            logger.exception("Import failed with exception:")

    def parse_date(self, date_string):
        """Parse date from MM/DD/YYYY format"""
        try:
            return datetime.strptime(date_string.strip(), '%m/%d/%Y').date()
        except ValueError:
            # Try alternative formats
            for fmt in ['%m-%d-%Y', '%m/%d/%y', '%m-%d-%y']:
                try:
                    return datetime.strptime(date_string.strip(), fmt).date()
                except ValueError:
                    continue
            raise ValueError(f"Unable to parse date: {date_string}")

    def get_or_create_class(self, class_name):
        """Get or create SchoolClass instance"""
        try:
            return SchoolClass.objects.get(level=class_name.strip())
        except SchoolClass.DoesNotExist:
            self.stdout.write(
                self.style.WARNING(f'Class not found: {class_name}. Skipping student.')
            )
            return None

    def get_or_create_parent(self, phone_number):
        """Get or create Parent instance"""
        if not phone_number or phone_number.strip() == '':
            return None
            
        phone_clean = phone_number.strip()
        
        try:
            return Parent.objects.get(phone_number=phone_clean)
        except Parent.DoesNotExist:
            # Create a basic user for the parent
            try:
                user = User.objects.create_user(
                    username=phone_clean,
                    password=phone_clean,  # Using phone number as password per your logic
                    is_active=True
                )
                parent = Parent.objects.create(
                    user=user,
                    phone_number=phone_clean,
                    full_name=f'Parent {phone_clean}',  # Placeholder name
                )
                return parent
            except Exception as e:
                logger.warning(f"Could not create parent for phone {phone_clean}: {e}")
                return None

    def clean_csv_data(self, row):
        """Clean and validate CSV row data"""
        cleaned = {}
        
        # Map CSV columns to model fields
        field_mapping = {
            'Surname': 'surname',
            'First Name': 'first_name', 
            'Middle Name': 'middle_name',
            'Date of Birth': 'date_of_birth',
            'Address': 'address',
            'Parent Phone Number': 'parent_phone',
            'Gender': 'gender',
            'Enrollment Year': 'enrollment_year',
            'Class': 'class_name'
        }
        
        for csv_col, model_field in field_mapping.items():
            value = row.get(csv_col, '').strip()
            
            if model_field == 'date_of_birth':
                if value:
                    try:
                        cleaned[model_field] = self.parse_date(value)
                    except ValueError as e:
                        raise ValueError(f"Invalid date format for {value}: {e}")
                else:
                    raise ValueError("Date of birth is required")
            
            elif model_field == 'gender':
                if value.upper() in ['M', 'MALE']:
                    cleaned[model_field] = 'M'
                elif value.upper() in ['F', 'FEMALE']:
                    cleaned[model_field] = 'F'
                else:
                    raise ValueError(f"Invalid gender: {value}")
            
            elif model_field == 'enrollment_year':
                if value and len(value) == 4 and value.isdigit():
                    cleaned[model_field] = value
                else:
                    raise ValueError(f"Invalid enrollment year: {value}")
            
            else:
                cleaned[model_field] = value
        
        return cleaned

    def create_student_batch(self, students_data):
        """Create students in batches"""
        created_count = 0
        error_count = 0
        
        for student_data in students_data:
            try:
                with transaction.atomic():
                    # Get or create parent
                    parent = None
                    if student_data.get('parent_phone'):
                        parent = self.get_or_create_parent(student_data['parent_phone'])
                    
                    # Get class
                    school_class = self.get_or_create_class(student_data['class_name'])
                    if not school_class:
                        error_count += 1
                        continue
                    
                    # Create student
                    student = Student(
                        first_name=student_data['first_name'],
                        middle_name=student_data.get('middle_name', ''),
                        surname=student_data['surname'],
                        date_of_birth=student_data['date_of_birth'],
                        address=student_data.get('address', ''),
                        parent_phone=student_data.get('parent_phone', ''),
                        gender=student_data['gender'],
                        nationality='Nigeria',  # Default from model
                        enrollment_year=student_data['enrollment_year'],
                        current_class=school_class,
                        parent=parent,
                        is_active=True
                    )
                    
                    # This will trigger the save method which handles:
                    # - admission_number generation
                    # - token generation  
                    # - user creation
                    student.save()
                    created_count += 1
                    
                    if created_count % 50 == 0:
                        self.stdout.write(f'Created {created_count} students...')
                        
            except Exception as e:
                error_count += 1
                logger.error(f"Error creating student {student_data.get('first_name', '')} {student_data.get('surname', '')}: {e}")
        
        return created_count, error_count

    def import_students(self, csv_file_path, batch_size):
        """Main import function"""
        self.stdout.write(f'Starting import from: {csv_file_path}')
        
        total_processed = 0
        total_created = 0
        total_errors = 0
        batch_data = []
        
        with open(csv_file_path, 'r', encoding='utf-8-sig') as file:
            # Use DictReader for easier column access
            reader = csv.DictReader(file)
            
            # Verify required columns exist
            required_columns = ['Surname', 'First Name', 'Date of Birth', 'Gender', 'Enrollment Year', 'Class']
            missing_columns = [col for col in required_columns if col not in reader.fieldnames]
            
            if missing_columns:
                raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")
            
            self.stdout.write(f'Found columns: {", ".join(reader.fieldnames)}')
            
            for row_num, row in enumerate(reader, start=2):  # Start at 2 since row 1 is header
                try:
                    # Clean and validate data
                    cleaned_data = self.clean_csv_data(row)
                    batch_data.append(cleaned_data)
                    
                    # Process batch when it reaches batch_size
                    if len(batch_data) >= batch_size:
                        created, errors = self.create_student_batch(batch_data)
                        total_created += created
                        total_errors += errors
                        total_processed += len(batch_data)
                        batch_data = []  # Reset batch
                        
                        self.stdout.write(
                            f'Processed {total_processed} records. Created: {total_created}, Errors: {total_errors}'
                        )
                
                except Exception as e:
                    total_errors += 1
                    logger.error(f"Error processing row {row_num}: {e}")
                    self.stdout.write(
                        self.style.WARNING(f'Row {row_num} error: {str(e)}')
                    )
            
            # Process remaining records in the final batch
            if batch_data:
                created, errors = self.create_student_batch(batch_data)
                total_created += created
                total_errors += errors
                total_processed += len(batch_data)
        
        # Final summary
        self.stdout.write(
            self.style.SUCCESS(
                f'Import completed!\n'
                f'Total processed: {total_processed}\n'
                f'Successfully created: {total_created}\n'
                f'Errors: {total_errors}'
            )
        )
        
        if total_errors > 0:
            self.stdout.write(
                self.style.WARNING(
                    f'Check logs for details on {total_errors} failed records.'
                )
            )
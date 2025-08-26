from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from django.conf import settings
import os

from accounts.constants import TERM_CHOICES

def generate_result_pdf(student, results, session, term, is_nursery=False, is_primary=False):
    # Register modern fonts
    try:
        font_dir = os.path.join(settings.STATIC_ROOT, 'accounts/fonts')
        pdfmetrics.registerFont(TTFont('Montserrat', os.path.join(font_dir, 'Montserrat-Regular.ttf')))
        pdfmetrics.registerFont(TTFont('Montserrat-Bold', os.path.join(font_dir, 'Montserrat-Bold.ttf')))
        pdfmetrics.registerFont(TTFont('OpenSans', os.path.join(font_dir, 'OpenSans-Regular.ttf')))
        custom_fonts_loaded = True
    except:
        # Fallback to standard fonts if custom fonts fail
        custom_fonts_loaded = False

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=letter, 
        rightMargin=20, 
        leftMargin=20, 
        topMargin=20, 
        bottomMargin=20,
        title=f"{student.full_name}'s Result - {session.name} Term {term}"
    )
    
    # Get base styles
    styles = getSampleStyleSheet()
    
    # Modify or create styles safely
    if 'Title' not in styles:
        styles.add(ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontName='Montserrat-Bold' if custom_fonts_loaded else 'Helvetica-Bold',
            fontSize=18,
            alignment=1,
            spaceAfter=10,
            textColor=colors.HexColor('#2c3e50'))
        )
    else:
        styles['Title'].fontName = 'Montserrat-Bold' if custom_fonts_loaded else 'Helvetica-Bold'
        styles['Title'].fontSize = 18
        styles['Title'].textColor = colors.HexColor('#2c3e50')
        styles['Title'].alignment = 1
        styles['Title'].spaceAfter = 10

    if 'Subtitle' not in styles:
        styles.add(ParagraphStyle(
            'Subtitle',
            parent=styles['Heading2'],
            fontName='Montserrat' if custom_fonts_loaded else 'Helvetica',
            fontSize=11,
            alignment=1,
            spaceAfter=15,
            textColor=colors.HexColor('#7f8c8d'))
        )
    else:
        styles['Subtitle'].fontName = 'Montserrat' if custom_fonts_loaded else 'Helvetica'
        styles['Subtitle'].fontSize = 11
        styles['Subtitle'].textColor = colors.HexColor('#7f8c8d')
        styles['Subtitle'].alignment = 1
        styles['Subtitle'].spaceAfter = 15

    # Header style
    if 'Header' not in styles:
        styles.add(ParagraphStyle(
            'Header',
            parent=styles['Normal'],
            fontName='Montserrat-Bold' if custom_fonts_loaded else 'Helvetica-Bold',
            fontSize=10,
            textColor=colors.white,
            alignment=1
        ))

    # Cell style
    if 'Cell' not in styles:
        styles.add(ParagraphStyle(
            'Cell',
            parent=styles['Normal'],
            fontName='OpenSans' if custom_fonts_loaded else 'Helvetica',
            fontSize=9,
            alignment=1
        ))

    # Highlight style
    if 'Highlight' not in styles:
        styles.add(ParagraphStyle(
            'Highlight',
            parent=styles['Normal'],
            fontName='Montserrat-Bold' if custom_fonts_loaded else 'Helvetica-Bold',
            fontSize=10,
            textColor=colors.HexColor('#e74c3c'),
            alignment=1
        ))

    logo_path = os.path.join(settings.STATIC_ROOT, 'main/images/rise-logo.jpeg')
    elements = []
    
    # Header with school info and logo
    header_table_data = []
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=1.5*inch, height=1.5*inch)
        header_table_data.append([logo, ""])
    else:
        header_table_data.append(["", ""])
    
    header_table = Table(header_table_data, colWidths=[2*inch, 5*inch])
    elements.append(header_table)
    
    school_info = [
        Spacer(1, 10),
        Paragraph("<b>REHOBOTH INTERNATIONAL SCHOOL OF EXCELLENCE</b>", styles['Title']),
        Paragraph("796 Rue Des Cormiers, Qt Hedrzranawoe B.P. 3128 LOME-TOGO", styles['Subtitle']),
        Paragraph(f"ACADEMIC REPORT - {session.name.upper()} (TERM {term})", styles['Subtitle']),
        Spacer(1, 15)
    ]
    elements.extend(school_info)
    
    # Student information with modern card-like design
    student_info_data = [
        ["STUDENT INFORMATION", "", "", ""],
        ["Name:", student.full_name, "Admission No:", student.admission_number],
        ["Class:", f"{student.current_class.level if student.current_class else 'N/A'}", 
         "Section:", f"{student.current_section.suffix if student.current_section else 'N/A'}"],
        ["Term:", dict(TERM_CHOICES).get(term, term), "Session:", session.name]
    ]
    
    student_info_table = Table(student_info_data, colWidths=[1.5*inch, 3*inch, 1.5*inch, 2*inch])
    student_info_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Montserrat-Bold' if custom_fonts_loaded else 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8f9fa')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e0e0e0')),
        ('FONTNAME', (0,1), (-1,-1), 'OpenSans' if custom_fonts_loaded else 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    
    elements.extend([
        student_info_table,
        Spacer(1, 25)
    ])
    
    # Results table with modern styling
    if is_nursery:
        data = [["Subject", "Total Marks", "Grade", "Remark"]]
        for result in results:
            data.append([
                Paragraph(result.subject.name, styles['Cell']),
                Paragraph(f"{result.total_marks:.1f}" if result.total_marks else "-", styles['Cell']),
                Paragraph(result.grade, styles['Cell']),
                Paragraph(result.description, styles['Cell'])
            ])
        col_widths = [1.8*inch, 0.7*inch, 0.7*inch, 1.5*inch]
    elif is_primary:
        data = [["Subject", "Test", "HW", "CW", "Exam", "Total", "Grade", "Remark"]]
        for result in results:
            data.append([
                Paragraph(result.subject.name, styles['Cell']),
                Paragraph(f"{result.test:.1f}" if result.test else "-", styles['Cell']),
                Paragraph(f"{result.homework:.1f}" if result.homework else "-", styles['Cell']),
                Paragraph(f"{result.classwork:.1f}" if result.classwork else "-", styles['Cell']),
                Paragraph(f"{result.nursery_primary_exam:.1f}" if result.nursery_primary_exam else "-", styles['Cell']),
                Paragraph(f"{result.total_score:.1f}", styles['Cell']),
                Paragraph(result.grade, styles['Cell']),
                Paragraph(result.description, styles['Cell'])
            ])
        col_widths = [1.8*inch] + [0.7*inch]*5 + [0.7*inch, 1.5*inch]
    else:
        data = [["Subject", "CA", "Test 1", "Test 2", "Exam", "Total", "Grade", "G.P", "Remark"]]
        for result in results:
            data.append([
                Paragraph(result.subject.name, styles['Cell']),
                Paragraph(f"{result.ca:.1f}" if result.ca else "-", styles['Cell']),
                Paragraph(f"{result.test_1:.1f}" if result.test_1 else "-", styles['Cell']),
                Paragraph(f"{result.test_2:.1f}" if result.test_2 else "-", styles['Cell']),
                Paragraph(f"{result.exam:.1f}" if result.exam else "-", styles['Cell']),
                Paragraph(f"{result.total_score:.1f}", styles['Cell']),
                Paragraph(result.grade, styles['Cell']),
                Paragraph(f"{result.grade_point:.1f}" if result.grade_point is not None else "-", styles['Cell']),
                Paragraph(result.description, styles['Cell'])
            ])
        col_widths = [1.8*inch] + [0.7*inch]*5 + [0.7*inch, 0.7*inch, 1.5*inch]
    
    # Create table with modern styling
    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('FONTNAME', (0,0), (-1,0), 'Montserrat-Bold' if custom_fonts_loaded else 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('BACKGROUND', (0,1), (-1,-1), colors.white),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e0e0e0')),
        ('FONTNAME', (0,1), (-1,-1), 'OpenSans' if custom_fonts_loaded else 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    
    # Highlight excellent and poor grades (for non-nursery/primary)
    if not (is_nursery or is_primary):
        for i in range(1, len(data)):
            if data[i][6] in ['A', 'A+', 'B+']:  # Excellent grades
                table.setStyle(TableStyle([
                    ('TEXTCOLOR', (0,i), (-1,i), colors.HexColor('#27ae60'))
                ]))
            elif data[i][6] in ['D', 'E', 'F']:  # Poor grades
                table.setStyle(TableStyle([
                    ('TEXTCOLOR', (0,i), (-1,i), colors.HexColor('#e74c3c'))
                ]))
    
    elements.append(table)
    elements.append(Spacer(1, 25))
    
    # Performance summary with modern design
    valid_results = [r for r in results if r.total_score > 0]
    if valid_results:
        avg_score = sum(r.total_score for r in valid_results) / len(valid_results)
        if not (is_nursery or is_primary):
            avg_gp = sum(r.grade_point for r in valid_results if r.grade_point is not None) / len(valid_results)
        
        summary_data = [
            ["PERFORMANCE SUMMARY", ""],
            ["Average Score:", f"{avg_score:.2f}%"],
            ["Class Position:", valid_results[0].class_position if valid_results else "-"]
        ]
        
        if not (is_nursery or is_primary):
            summary_data.append(["Average Grade Point:", f"{avg_gp:.2f}"])
            summary_data.append(["Class Position (G.P):", valid_results[0].class_position_gp if valid_results else "-"])
        
        summary_table = Table(summary_data, colWidths=[2.5*inch, 3*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Montserrat-Bold' if custom_fonts_loaded else 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 10),
            ('ALIGN', (0,0), (-1,0), 'CENTER'),
            ('SPAN', (0,0), (1,0)),
            ('FONTNAME', (0,1), (-1,-1), 'OpenSans' if custom_fonts_loaded else 'Helvetica'),
            ('FONTSIZE', (0,1), (-1,-1), 9),
            ('ALIGN', (0,1), (0,-1), 'RIGHT'),
            ('ALIGN', (1,1), (1,-1), 'LEFT'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e0e0e0')),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8f9fa')),
        ]))
        
        elements.append(summary_table)
        elements.append(Spacer(1, 30))
    
    # Comments section
    comments = [
        Paragraph("<b>TEACHER'S COMMENTS:</b>", ParagraphStyle(
            'CommentsHeader',
            parent=styles['Normal'],
            fontName='Montserrat-Bold' if custom_fonts_loaded else 'Helvetica-Bold',
            fontSize=10,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=5
        )),
        Paragraph("_________________________________________________________________________________________", styles['Normal']),
        Paragraph("_________________________________________________________________________________________", styles['Normal']),
        Spacer(1, 15),
        Paragraph("<b>PRINCIPAL'S COMMENTS:</b>", ParagraphStyle(
            'CommentsHeader',
            parent=styles['Normal'],
            fontName='Montserrat-Bold' if custom_fonts_loaded else 'Helvetica-Bold',
            fontSize=10,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=5
        )),
        Paragraph("_________________________________________________________________________________________", styles['Normal']),
        Paragraph("_________________________________________________________________________________________", styles['Normal']),
        Spacer(1, 30)
    ]
    elements.extend(comments)
    
    # Footer with signatures
    footer_data = [
        ["", "", ""],
        ["Class Teacher's Signature", "", "Principal's Signature"],
        ["", "", ""],
        ["Date: _________________", "", "Date: _________________"]
    ]
    
    footer_table = Table(footer_data, colWidths=[3*inch, 1*inch, 3*inch])
    footer_table.setStyle(TableStyle([
        ('FONTNAME', (0,1), (-1,1), 'Montserrat' if custom_fonts_loaded else 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,1), 9),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('LINEABOVE', (0,2), (0,2), 0.5, colors.black),
        ('LINEABOVE', (2,2), (2,2), 0.5, colors.black),
    ]))
    
    # elements.extend([
    #     footer_table,
    #     Spacer(1, 10),
    #     Paragraph("<i>This is a computer generated report. No signature is required.</i>", ParagraphStyle(
    #         'Footer',
    #         parent=styles['Normal'],
    #         fontName='OpenSans-Italic' if custom_fonts_loaded else 'Helvetica-Oblique',
    #         fontSize=8,
    #         alignment=1,
    #         textColor=colors.HexColor('#7f8c8d')
    #     ))
    # ])
    
    doc.build(elements)
    buffer.seek(0)
    return buffer
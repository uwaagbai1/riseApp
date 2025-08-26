from django.urls import path

from main.views import *

urlpatterns = [
    path('', index, name='index'),
    path('who-we-are/', about, name='about_us'),
    path('contact-us/', contact, name='contact_us'),
    path('school-news/', news_list, name='news_list'),
    path('school-news/<slug:slug>/', news_detail, name='news_detail'),
    path('our-gallery/', gallery, name='gallery'),
    path('academic-programs/creche', creche_info, name='creche_info'),
    path('academic-programs/nursery-and-primary', npinfo, name='nurseryandprimary_info'),
    path('academic-programs/junior-secondary-school', jss, name='juniorsec_info'),
    path('academic-programs/senior-secondary-school', sss, name='seniorsec_info'),
]
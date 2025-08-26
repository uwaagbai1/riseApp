from django.shortcuts import get_object_or_404, render
from django.core.paginator import Paginator

from main.models import Home, Testimonial, News, About, Staff, Gallery, Creche_info, Np_info, Jss_info, Sss_info

def index(request):
    home = Home.objects.first()  
    
    testimonials = Testimonial.objects.all()[:3]  
    
    news = News.objects.all()[:6]  

    for news_item in news:
        news_item.category_list = news_item.categories.split(',') if news_item.categories else []

    context = {
        'home': home,
        'testimonials': testimonials,
        'news': news,
    }
    return render(request, 'main/index.html', context)

def about(request):
    about = About.objects.last()  
    staff = Staff.objects.all()  
    
    for index, staff_member in enumerate(staff):
        staff_member.delay = index * 180  
    context = {
        'about': about,
        'staff': staff,
    }
    return render(request, 'main/about.html', context)

def contact(request):

    return render(request, 'main/contact.html')

def news_list(request):
    news = News.objects.all().order_by('-created_at')
    recent_posts = News.objects.all().order_by('-created_at')[:3]  
    for news_item in news:
        news_item.category_list = news_item.categories.split(',') if news_item.categories else []
    for recent_post in recent_posts:
        recent_post.category_list = recent_post.categories.split(',') if recent_post.categories else []
    context = {
        'news': news,
        'recent_posts': recent_posts,
    }
    return render(request, 'main/news.html', context)

def news_detail(request, slug):
    news_item = get_object_or_404(News, slug=slug)
    news_item.category_list = news_item.categories.split(',') if news_item.categories else []
    related_posts = News.objects.exclude(slug=slug).order_by('-created_at')[:3]  
    for related_post in related_posts:
        related_post.category_list = related_post.categories.split(',') if related_post.categories else []
    context = {
        'news_item': news_item,
        'related_posts': related_posts,
    }
    return render(request, 'main/news_detail.html', context)

def gallery(request):
    gallery_items = Gallery.objects.all().order_by('-created_at')
    categories = sorted(set(item.category for item in gallery_items if item.category))
    paginator = Paginator(gallery_items, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {
        'gallery_items': page_obj,
        'categories': categories,
    }
    return render(request, 'main/gallery.html', context)

def creche_info(request):
    item = Creche_info.objects.last()  
    
    context = {
        'item': item,
    }
    return render(request, 'main/creche_info.html', context)

def npinfo(request):
    item = Np_info.objects.last()  
    
    context = {
        'item': item,
    }
    return render(request, 'main/np_info.html', context)

def jss(request):
    item = Jss_info.objects.last()  
    
    context = {
        'item': item,
    }
    return render(request, 'main/juniorsec_info.html', context)

def sss(request):
    item = Sss_info.objects.last()  
    
    context = {
        'item': item,
    }
    return render(request, 'main/seniorsec_info.html', context)
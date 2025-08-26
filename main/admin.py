from django.contrib import admin

from main.models import Gallery, Home, Testimonial, News, About, Staff, Creche_info, Np_info, Jss_info, Sss_info

@admin.register(Home)
class HomeAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'updated_at')
    list_filter = ('created_at',)
    search_fields = ('id',)

@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ('name', 'designation', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'content')

@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('title', 'content', 'slug')
    prepopulated_fields = {'slug': ('title',)}

@admin.register(About)
class AboutAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'updated_at')
    list_filter = ('created_at',)
    search_fields = ('id',)

@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ('name', 'position', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'position')

@admin.register(Gallery)
class GalleryAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'slug', 'created_at')
    list_filter = ('created_at', 'category')
    search_fields = ('title', 'description', 'category')
    prepopulated_fields = {'slug': ('title',)}

@admin.register(Creche_info)
class CrecheAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'updated_at')
    list_filter = ('created_at',)
    search_fields = ('id',)

@admin.register(Np_info)
class NPAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'updated_at')
    list_filter = ('created_at',)
    search_fields = ('id',)

@admin.register(Jss_info)
class JSSAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'updated_at')
    list_filter = ('created_at',)
    search_fields = ('id',)

@admin.register(Sss_info)
class SSSAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'updated_at')
    list_filter = ('created_at',)
    search_fields = ('id',)
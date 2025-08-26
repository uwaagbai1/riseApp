from django.db import models
from django.utils.text import slugify
from cloudinary.models import CloudinaryField

class Home(models.Model):
    banner_image_1 = CloudinaryField('image', folder='riseschools/banners/', blank=True, null=True)
    banner_image_2 = CloudinaryField('image', folder='riseschools/banners/', blank=True, null=True)
    mission_image = CloudinaryField('image', folder='riseschools/mission/', blank=True, null=True)
    cta_image = CloudinaryField('image', folder='riseschools/cta/', blank=True, null=True)
    why_rise_image = CloudinaryField('image', folder='riseschools/why_rise/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    admission_link = models.URLField(blank=True, null=True)

    def __str__(self):
        return f"Home Page Images ({self.id})"

    class Meta:
        verbose_name = "Home Page"
        verbose_name_plural = "Home Pages"

class Testimonial(models.Model):
    name = models.CharField(max_length=100)
    designation = models.CharField(max_length=100, default="Student")
    image = CloudinaryField('image', folder='riseschools/testimonials/', blank=True, null=True)
    rating = models.PositiveIntegerField(default=5)  
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.designation}"

    class Meta:
        verbose_name = "Testimonial"
        verbose_name_plural = "Testimonials"

class News(models.Model):
    title = models.CharField(max_length=200)
    image = CloudinaryField('image', folder='riseschools/news/', blank=True, null=True)
    categories = models.CharField(max_length=200, blank=True)
    read_time = models.CharField(max_length=50, blank=True, default="3 Minutes Read")
    content = models.TextField()
    slug = models.SlugField(max_length=250, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
            
            original_slug = self.slug
            counter = 1
            while News.objects.filter(slug=self.slug).exists():
                self.slug = f"{original_slug}-{counter}"
                counter += 1

        
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
    
    class Meta:
        verbose_name = "News"
        verbose_name_plural = "News"

class About(models.Model):
    about_image_1 = CloudinaryField('image', folder='riseschools/about/', blank=True, null=True)
    about_image_2 = CloudinaryField('image', folder='riseschools/about/', blank=True, null=True)
    directors_image = CloudinaryField('image', folder='riseschools/directors/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    video_link = models.URLField(blank=True, null=True)

    
    def __str__(self):
        return f"About Page Images {self.id}"
    
    class Meta:
        verbose_name = "About"
        verbose_name_plural = "About"

class Staff(models.Model):
    name = models.CharField(max_length=100)
    position = models.CharField(max_length=100)
    image = CloudinaryField('image', folder='riseschools/staff/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.position}"
    
    class Meta:
        verbose_name = "Staff"
        verbose_name_plural = "Staff"

class Gallery(models.Model):
    CATEGORY_CHOICES = [
        ('SPORTS', 'Sports'),
        ('STEM', 'STEM'),
        ('EVENTS', 'Events'),
        ('ACADEMICS', 'Academics'),
        ('ARTS', 'Arts'),
        ('GRADUATION', 'Graduation'),
    ]

    title = models.CharField(max_length=200)
    image = CloudinaryField('image', folder='riseschools/gallery/', blank=True, null=True)
    category = models.CharField(max_length=100, choices=CATEGORY_CHOICES, blank=True)
    description = models.TextField(blank=True)
    slug = models.SlugField(max_length=250, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
            original_slug = self.slug
            counter = 1
            while Gallery.objects.filter(slug=self.slug).exists():
                self.slug = f"{original_slug}-{counter}"
                counter += 1
        
        
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = "Gallery"
        verbose_name_plural = "Gallery"


class Creche_info(models.Model):
    image = CloudinaryField('image', folder='riseschools/creche/info/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Creche Info Page Images {self.id}"

    class Meta:
        verbose_name = "Creche Info"
        verbose_name_plural = "Creche Info"

class Np_info(models.Model):
    image = CloudinaryField('image', folder='riseschools/np/info/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    
    def __str__(self):
        return f"NP Info Page Images {self.id}"
    
    class Meta:
        verbose_name = "NP Info"
        verbose_name_plural = "NP Info"

class Jss_info(models.Model):
    image = CloudinaryField('image', folder='riseschools/jss/info/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    
    def __str__(self):
        return f"JSS Info Page Images {self.id}"
    
    class Meta:
        verbose_name = "JSS Info"
        verbose_name_plural = "JSS Info"

class Sss_info(models.Model):
    image = CloudinaryField('image', folder='riseschools/sss/info/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    
    def __str__(self):
        return f"SSS Info Page Images {self.id}"
    
    class Meta:
        verbose_name = "SSS Info"
        verbose_name_plural = "SSS Info"
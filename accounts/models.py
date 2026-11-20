from django.db import models
from django.contrib.auth.models import AbstractUser
# Жаңы колдонмодон Shop моделин импорттоо
from shops.models import Shop 

from django.db.models.signals import post_save
from django.dispatch import receiver


class User(AbstractUser):
    """Custom User model with roles"""
    
    ROLE_CHOICES = [
        ('seller', 'Продавец'),
        ('employee', 'Сотрудник'),
        ('courier', 'Курьер'),
        ('client', 'Клиент'),
    ]
    
    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=20, 
        choices=ROLE_CHOICES, 
        default='client'
    )

    phone_number = models.CharField(max_length=20, null=True, blank=True, verbose_name="Телефон номер")
    address = models.TextField(null=True, blank=True, verbose_name="Адрес доставки")
    
    # Башка колдонмодогу модель менен байланыш
    shops = models.ManyToManyField(
        Shop, 
        blank=True, 
        related_name='sellers', 
        verbose_name="Магазины продавца"
    )
    
    class Meta:
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'
    
    def __str__(self):
        name = self.get_full_name() if self.get_full_name() else self.username
        return f"{name} ({self.get_role_display()})"




# accounts/models.py ичине

class Profile(models.Model):
    user = models.OneToOneField(
        'accounts.User', 
        on_delete=models.CASCADE, 
        related_name='profile'
    )
    # Маалыматтар
    full_name = models.CharField(max_length=255, verbose_name="Аты-жөнү", blank=True)
    phone = models.CharField(max_length=20, verbose_name="Телефон", blank=True)
    address = models.TextField(verbose_name="Дарек", blank=True)
    preferred_pickup_point = models.CharField(max_length=255, verbose_name="Пункт выдачи", blank=True)
    language = models.CharField(max_length=10, choices=[('ky', 'Кыргызча'), ('ru', 'Русский')], default='ky')

    def __str__(self):
        return f"Профиль {self.user.username}"



@receiver(post_save, sender='accounts.User')
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender='accounts.User')
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()
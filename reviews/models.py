# reviews/models.py

from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Avg, Count


class Review(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name='Пользователь',
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name='Товар',
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name='Рейтинг',
    )
    text = models.TextField(
        blank=True,
        verbose_name='Текст отзыва',
    )
    verified_purchase = models.BooleanField(
        default=False,
        verbose_name='Подтверждённая покупка',
        db_index=True,
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен',
        db_index=True,
    )
    seller_reply = models.TextField(
        blank=True,
        verbose_name='Ответ продавца',
    )
    seller_reply_date = models.DateTimeField(
        null=True, blank=True,
        verbose_name='Дата ответа продавца',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Отзыв'
        verbose_name_plural = 'Отзывы'
        ordering = ['-created_at']
        # Один пользователь — один отзыв на один товар
        unique_together = ('user', 'product')
        indexes = [
            models.Index(fields=['product', 'is_active']),
            models.Index(fields=['product', 'rating']),
        ]

    def __str__(self):
        return f'{self.user.username} → {self.product.title} ({self.rating}★)'

    def save(self, *args, **kwargs):
        # Автоматически проверяем подтверждённую покупку
        if not self.pk:
            from orders.models import Order
            self.verified_purchase = Order.objects.filter(
                client=self.user,
                items__product=self.product,
                status='delivered',
            ).exists()
        super().save(*args, **kwargs)


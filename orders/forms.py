# orders/forms.py
from django import forms
from .models import Order

class OrderCheckoutForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['delivery_method', 'address', 'full_name', 'phone', 'payment_method', 'comment']
        widgets = {
            'delivery_method': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'payment_method': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Аты-жөнүңүз'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+996 XXX XXX XXX'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Кара-Суу, ул. Ленина 12/9'}),
            'comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Комментарий (милдеттүү эмес)'}),
        }
        labels = {
            'delivery_method': 'Жеткирүү ыкмасы',
            'payment_method': 'Төлөм ыкмасы',
            'full_name': 'Алуучунун аты-жөнү',
            'phone': 'Телефон номери',
            'address': 'Жеткирүү дареги',
            'comment': 'Комментарий',
        }
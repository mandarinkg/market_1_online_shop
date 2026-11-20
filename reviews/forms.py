# reviews/forms.py

from django import forms
from .models import Review


class ReviewForm(forms.ModelForm):
    rating = forms.ChoiceField(
        choices=[(i, i) for i in range(1, 6)],
        widget=forms.HiddenInput(),
        label='Рейтинг',
    )

    class Meta:
        model  = Review
        fields = ['rating', 'text']
        widgets = {
            'text': forms.Textarea(attrs={
                'placeholder': 'Расскажите о товаре — качество, доставка, соответствие описанию...',
                'rows': 4,
                'class': 'review-textarea',
            }),
        }
        labels = {
            'text': 'Ваш отзыв',
        }

    def clean_rating(self):
        rating = int(self.cleaned_data.get('rating', 0))
        if not (1 <= rating <= 5):
            raise forms.ValidationError('Выберите оценку от 1 до 5.')
        return rating


class SellerReplyForm(forms.ModelForm):
    class Meta:
        model  = Review
        fields = ['seller_reply']
        widgets = {
            'seller_reply': forms.Textarea(attrs={
                'placeholder': 'Ваш ответ на отзыв...',
                'rows': 3,
                'class': 'review-textarea',
            }),
        }
        labels = {
            'seller_reply': 'Ответ продавца',
        }
# reviews/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Avg, Count
from django.utils import timezone

from products.models import Product
from .models import Review
from .forms import ReviewForm, SellerReplyForm


def _get_rating_stats(product):
    """Статистика по звёздам для конкретного товара."""
    stats = {}
    total = product.reviews.filter(is_active=True).count()
    for star in range(5, 0, -1):
        count = product.reviews.filter(is_active=True, rating=star).count()
        percent = int(count / total * 100) if total > 0 else 0
        stats[star] = {'count': count, 'percent': percent}
    return stats, total


def review_list(request, slug):
    """
    Список отзывов к товару с пагинацией.
    Используется как самостоятельная страница ИЛИ
    подгружается через include в product_detail.html.
    """
    product  = get_object_or_404(
        Product.objects.prefetch_related('reviews__user'),
        slug=slug
    )
    reviews_qs = product.reviews.filter(
        is_active=True
    ).select_related('user').order_by('-created_at')

    # Фильтр по звёздам
    star_filter = request.GET.get('stars')
    if star_filter and star_filter.isdigit():
        reviews_qs = reviews_qs.filter(rating=int(star_filter))

    # Пагинация — 5 отзывов на страницу
    paginator = Paginator(reviews_qs, 5)
    page_num  = request.GET.get('page', 1)
    page_obj  = paginator.get_page(page_num)

    # Средний рейтинг
    avg_data  = product.reviews.filter(is_active=True).aggregate(avg=Avg('rating'))
    avg_rating = round(avg_data['avg'] or 0, 1)

    # Статистика по звёздам
    rating_stats, total_reviews = _get_rating_stats(product)

    # Форма нового отзыва
    user_review  = None
    review_form  = None
    can_review   = False

    if request.user.is_authenticated and request.user.role == 'client':
        user_review = Review.objects.filter(
            user=request.user, product=product
        ).first()
        if not user_review:
            can_review  = True
            review_form = ReviewForm()

    return render(request, 'products/product_detail.html', {
        'product':      product,
        'page_obj':     page_obj,
        'avg_rating':   avg_rating,
        'total_reviews': total_reviews,
        'rating_stats': rating_stats,
        'review_form':  review_form,
        'user_review':  user_review,
        'can_review':   can_review,
        'star_filter':  star_filter,
    })


@login_required
def review_create(request, slug):
    """Создать отзыв."""
    if request.user.role != 'client':
        messages.error(request, 'Только клиенты могут оставлять отзывы.')
        return redirect('products:detail', slug=slug)

    product = get_object_or_404(Product, slug=slug)

    if Review.objects.filter(user=request.user, product=product).exists():
        messages.warning(request, 'Вы уже оставили отзыв на этот товар.')
        return redirect('reviews:list', slug=slug)

    if request.method == 'POST':
        form = ReviewForm(request.POST)
        if form.is_valid():
            review          = form.save(commit=False)
            review.user     = request.user
            review.product  = product
            review.save()
            messages.success(request, 'Спасибо за ваш отзыв!')
            return redirect('reviews:list', slug=slug)
        else:
            messages.error(request, 'Проверьте правильность заполнения формы.')
    
    return redirect('reviews:list', slug=slug)


@login_required
def review_delete(request, pk):
    """Удалить свой отзыв."""
    review = get_object_or_404(Review, pk=pk, user=request.user)
    slug   = review.product.slug
    review.delete()
    messages.success(request, 'Отзыв удалён.')
    return redirect('reviews:list', slug=slug)


@login_required
def seller_reply(request, pk):
    """Продавец отвечает на отзыв."""
    review = get_object_or_404(Review, pk=pk)

    if review.product.seller != request.user:
        messages.error(request, 'Нет доступа.')
        return redirect('reviews:list', slug=review.product.slug)

    if request.method == 'POST':
        form = SellerReplyForm(request.POST, instance=review)
        if form.is_valid():
            r = form.save(commit=False)
            r.seller_reply_date = timezone.now()
            r.save()
            messages.success(request, 'Ответ сохранён.')

    return redirect('reviews:list', slug=review.product.slug)




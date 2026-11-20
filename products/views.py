from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Product, ProductImage
# Өзгөртүлгөн формалар туура импорттолду
from .forms import ProductCreateForm, ProductUpdateForm
from django.http import JsonResponse # AJAX жооптору үчүн

from .models import ProductAttribute

from shops.models import Shop
from django.db.models import Avg, Count
# Бардык колдонуучулар сайттын башкы баракчасында бардык активдүү товарларды көрө алышат
# products/views.py ичиндеги index_view функциясын ушул менен алмаштыр
# products/views.py ичиндеги index_view функциясын ушул менен алмаштыр

def index_view(request):
    # Акциядагы товарлар гана башкы бетте
    discounted_products = Product.objects.filter(
        discount_percent__gt=0,
        stock__gt=0,
    ).order_by('-discount_percent')[:12]

    favorite_product_ids = []
    if request.user.is_authenticated and request.user.role == 'client':
        from favorites.models import Favorite
        favorite_product_ids = Favorite.objects.filter(
            user=request.user
        ).values_list('product_id', flat=True)

    context = {
        'discounted_products': discounted_products,
        'favorite_product_ids': list(favorite_product_ids),
    }
    return render(request, 'products/index.html', context)
    

# Client жана башкалар товардун деталдарын көрөт, seller өзүнүн товарларынын деталдарын гана көрөт
# Замени функцию product_detail в products/views.py на эту версию


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.prefetch_related(
            'images',           # галерея
            'attributes',       # характеристики
            'reviews__user',    # отзывы + авторы
        ).select_related('seller', 'shop', 'category'),
        slug=slug
    )

    # Избранное
    is_favorite = False
    if request.user.is_authenticated and request.user.role == 'client':
        from favorites.models import Favorite
        is_favorite = Favorite.objects.filter(
            user=request.user, product=product
        ).exists()

    # ── Данные для отзывов ──
    from reviews.models import Review
    from reviews.forms import ReviewForm
    from django.core.paginator import Paginator

    reviews_qs = product.reviews.filter(
        is_active=True
    ).select_related('user').order_by('-created_at')

    # Фильтр по звёздам
    star_filter = request.GET.get('stars')
    if star_filter and star_filter.isdigit():
        reviews_qs = reviews_qs.filter(rating=int(star_filter))

    # Пагинация
    paginator = Paginator(reviews_qs, 5)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    # Средний рейтинг
    avg_data   = product.reviews.filter(is_active=True).aggregate(avg=Avg('rating'))
    avg_rating = round(avg_data['avg'] or 0, 1)

    # Статистика по звёздам
    total_reviews = product.reviews.filter(is_active=True).count()
    rating_stats  = {}
    for star in range(5, 0, -1):
        cnt = product.reviews.filter(is_active=True, rating=star).count()
        pct = int(cnt / total_reviews * 100) if total_reviews > 0 else 0
        rating_stats[star] = {'count': cnt, 'percent': pct}

    # Форма отзыва
    user_review = None
    review_form = None
    can_review  = False

    if request.user.is_authenticated and request.user.role == 'client':
        user_review = Review.objects.filter(
            user=request.user, product=product
        ).first()
        if not user_review:
            can_review  = True
            review_form = ReviewForm()

    return render(request, 'products/product_detail.html', {
        'product':       product,
        'is_favorite':   is_favorite,
        # отзывы
        'page_obj':      page_obj,
        'avg_rating':    avg_rating,
        'total_reviews': total_reviews,
        'rating_stats':  rating_stats,
        'review_form':   review_form,
        'user_review':   user_review,
        'can_review':    can_review,
        'star_filter':   star_filter,
    })




# Seller өзүнүн товарларын гана көрөт, client жана башкалар бардык товарларды көрөт
# product_list функциясын ушул менен алмаштыр

@login_required(login_url='accounts:login')
def product_list(request):
    category_id = request.GET.get('category')

    if request.user.role == 'seller':
        products = Product.objects.filter(seller=request.user)
    else:
        products = Product.objects.all()

    if category_id:
        products = products.filter(category_id=category_id)

    products = products.exclude(slug='').exclude(slug__isnull=True)

    # ← ЭНЕ ЖЕТИШПЕГЕН ЖЕРИ
    favorite_product_ids = []
    if request.user.is_authenticated and request.user.role == 'client':
        from favorites.models import Favorite
        favorite_product_ids = list(
            Favorite.objects.filter(user=request.user).values_list('product_id', flat=True)
        )

    return render(request, 'products/product_list.html', {
        'products': products,
        'favorite_product_ids': favorite_product_ids,  # ← ЭНЕ ЖЕТИШПЕГЕН ЖЕРИ
    })


# products/views.py ичиндеги product_create жана product_edit функцияларын ушул менен алмаштыр

@login_required(login_url='accounts:login')
def product_create(request):
    if request.user.role != 'seller':
        return redirect('dashboard:home')

    if not Shop.objects.filter(owner=request.user).exists():
        return redirect('shops:create')

    if request.method == 'POST':
        form = ProductCreateForm(request.POST, request.FILES, user=request.user)

        print(form.errors)  # ← ДОБАВЬ

        if form.is_valid():
            product = form.save(commit=False)
            product.seller = request.user
            product.discount_percent = product.discount_percent or 0

            product.save()

            gallery_images = request.FILES.getlist('gallery_images')

            for index, image in enumerate(gallery_images):
                ProductImage.objects.create(
                    product=product,
                    image=image,
                    order=index + 1
                )

            attributes_text = form.cleaned_data.get('attributes')

            if attributes_text:
                for line in attributes_text.split('\n'):
                    if ':' in line:
                        name, value = line.split(':', 1)

                        ProductAttribute.objects.create(
                            product=product,
                            name=name.strip(),
                            value=value.strip()
                        )

            return redirect('products:detail', slug=product.slug)

    else:
        form = ProductCreateForm(user=request.user)

    return render(request, 'products/product_form.html', {
        'form': form,
        'title': 'Товар кошуу'
    })


@login_required(login_url='accounts:login')
def product_edit(request, slug):
    if request.user.role != 'seller':
        return redirect('dashboard:home')

    product = get_object_or_404(Product, slug=slug, seller=request.user)

    if request.method == 'POST':
        form = ProductUpdateForm(request.POST, request.FILES, instance=product, user=request.user)
        if form.is_valid():
            product = form.save()

            gallery_images = request.FILES.getlist('gallery_images')

            for index, image in enumerate(gallery_images):
                ProductImage.objects.create(
                    product=product,
                    image=image,
                    order=product.images.count() + index + 1
                )

            ProductAttribute.objects.filter(
                product=product
            ).delete()

            attributes_text = form.cleaned_data.get('attributes')

            if attributes_text:
                for line in attributes_text.split('\n'):
                    if ':' in line:
                        name, value = line.split(':', 1)

                        ProductAttribute.objects.create(
                            product=product,
                            name=name.strip(),
                            value=value.strip()
                        )
            return redirect('products:detail', slug=product.slug)

    else:
        form = ProductUpdateForm(instance=product, user=request.user)

    return render(request, 'products/product_form.html', {
        'form': form,
        'title': 'Товарды түзөтүү'
    })


# Seller гана товарларды өчүрө алат
@login_required(login_url='accounts:login')
def product_delete(request, slug):
    product = get_object_or_404(
        Product,
        slug=slug,
        seller=request.user
    )
    product.delete()
    return redirect('products:list')




@login_required
def buy_now(request, product_id):
    from cart.views import get_or_create_cart
    from cart.models import CartItem

    product = get_object_or_404(Product, id=product_id)
    cart    = get_or_create_cart(request)

    item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        defaults={'quantity': 1}
    )

    if not created:
        item.quantity += 1
        item.save()

    from django.urls import reverse
    checkout_url = reverse('orders:checkout')
    return redirect(f'{checkout_url}?selected_items={item.id}')
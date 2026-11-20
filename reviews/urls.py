from django.urls import path
from . import views
 
app_name = 'reviews'
 
urlpatterns = [
    path('<slug:slug>/',              views.review_list,   name='list'),
    path('<slug:slug>/create/',       views.review_create, name='create'),
    path('<int:pk>/delete/',          views.review_delete, name='delete'),
    path('<int:pk>/seller-reply/',    views.seller_reply,  name='seller_reply'),
]
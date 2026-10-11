from django.urls import path
from .views import OrderCreateView, MyOrdersView

urlpatterns = [
    path("create/", OrderCreateView.as_view(), name="order-create"),
    path("mine/", MyOrdersView.as_view(), name="my-orders"),
    
]
"""
URL configuration for supplier_order_adapter project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from supplier_graph.demo_views import DemoPageView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('supplier_graph.urls')),
    # Phase 6: the demo page itself lives outside /api/ -- it's an HTML
    # page a person views in a browser, not a JSON endpoint.
    path('demo/', DemoPageView.as_view(), name='demo-page'),
]

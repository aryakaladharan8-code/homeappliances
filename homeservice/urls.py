from django.shortcuts import redirect
from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('', views.home, name='home'),

    # USER ROUTES
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path("profile/", views.profile, name="profile"),
    path("findservice/", views.findservice, name="findservice"),
    path("recentservices/", views.recentservices, name="recentservices"),
    path("logoutpage/", views.logoutpage, name="logoutpage"),
    path("logout_ajax/", views.logout_ajax, name="logout_ajax"),
    path("logout/", views.logout_view, name="logout"),

    # ADMIN ROUTES
    path("admindashboard/", views.admindashboard, name="admindashboard"),
    path("admin_leaderboard/", views.admin_leaderboard, name="admin_leaderboard"),
    path("admin_payments/", views.admin_payments, name="admin_payments"),
    path("admin_reports/", views.admin_reports, name="admin_reports"),
    path("approve_payment/<int:payment_id>/", views.approve_payment, name="approve_payment"),
    path("assign_technician/<int:request_id>/", views.assign_technician, name="assign_technician"),
    path("customerlist/", views.customerlist, name="customerlist"),
    path("technicians/", views.technicians, name="technicians"),

    # Export PDF endpoints
    path("export/customers/", views.export_customers_pdf, name="export_customers_pdf"),
    path("export/technicians/", views.export_technicians_pdf, name="export_technicians_pdf"),

    path("request_detail/<int:request_id>/", views.request_detail, name="request_detail"),

    # TECHNICIAN ROUTES
    path("techniciandashboard/", views.techniciandashboard, name="techniciandashboard"),
    path("my-jobs/", views.my_jobs, name="my_jobs"),
    path("accept-job/<int:job_id>/", views.accept_job, name="accept_job"),
    path("complete-job/<int:job_id>/", views.complete_job, name="complete_job"),
    path("technicianportal/", views.technicianportal, name="technicianportal"),
    path('technicianlogin/', views.technician_login, name='technicianlogin'),
    path('forgot_password/', views.forgot_password, name='forgot_password'),
    path('reset_password/<str:token>/', views.reset_password, name='reset_password'),
    path('forgot_password_customer/', views.forgot_password_customer, name='forgot_password_customer'),
    path('reset_password_customer/<str:token>/', views.reset_password_customer, name='reset_password_customer'),
    path("techniciansignup/", views.techniciansignup, name="techniciansignup"),

    # ⭐ TECHNICIAN APPROVAL SYSTEM ⭐
    path('technician/approve/<int:tech_id>/', views.approve_technician, name='approvetech'),
    path('technician/reject/<int:tech_id>/', views.reject_technician, name='rejecttech'),
    path('technician/edit/<int:tech_id>/', views.edit_technician_status, name='edittech'),
    path('view_invoice/<int:request_id>/', views.view_invoice, name='view_invoice'),
    path('rate_technician/<int:request_id>/', views.rate_technician, name='rate_technician'),
    path('technician_ratings/', views.technician_ratings, name='technician_ratings'),
    path('technician_payment/', views.technician_payment, name='technician_payment'),
    path('technician_profile/', views.technician_profile, name='technician_profile'),
    path('respond_reschedule/<int:request_id>/', views.respond_reschedule, name='respond_reschedule'),
    path('user_assign_technician/<int:request_id>/', views.user_assign_technician, name='user_assign_technician'),
    path('reassign_technician/<int:request_id>/', views.reassign_technician, name='reassign_technician'),


    
    
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

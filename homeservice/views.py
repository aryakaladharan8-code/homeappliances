from django.shortcuts import render, redirect, get_object_or_404, HttpResponse
from django.contrib.auth import get_user_model, authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache
from django.db.models import Q, Sum
from django.utils.timezone import now

from .models import ServiceRequest, Customer, Technician, Rating, TechnicianPayment
from .forms import TechnicianSignupForm
from .utils import get_monthly_scores, update_technician_status, get_final_amount

import io
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

User = get_user_model()

import logging
logger = logging.getLogger(__name__)


def _get_admin_recipient_list():
    """
    Helper to determine admin recipient emails:
    1. settings.ADMINS => list of (name, email) tuples
    2. settings.ADMIN_EMAIL => single email (string) if you set it
    3. settings.DEFAULT_FROM_EMAIL as a last fallback
    """
    recipients = []
    admins = getattr(settings, "ADMINS", None)
    if admins:
        recipients = [email for _, email in admins]
    else:
        admin_email = getattr(settings, "ADMIN_EMAIL", None)
        if admin_email:
            recipients = [admin_email]
        else:
            default_from = getattr(settings, "DEFAULT_FROM_EMAIL", None)
            if default_from:
                recipients = [default_from]
    return recipients


def home(request):
    # Simple landing page with Login and Signup buttons
    return render(request, "homeservice/home.html")


# ---------------- REGISTER ----------------
def register(request):
    if request.method == "POST":
        name = request.POST.get("name")
        email = request.POST.get("email")
        phone = request.POST.get("phone")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        # Basic server-side validation
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError

        # Password match
        if password != confirm_password:
            messages.error(request, "Passwords do not match")
            return redirect("register")

        # Email format
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Please enter a valid email address.")
            return redirect("register")

        # Phone format: digits only and exactly 10 digits
        if phone:
            digits = ''.join(ch for ch in phone if ch.isdigit())
            if len(digits) != 10:
                messages.error(request, "Please enter a valid 10-digit phone number.")
                return redirect("register")
            phone = digits
        else:
            messages.error(request, "Phone number is required.")
            return redirect("register")

        if User.objects.filter(username=email).exists():
            messages.error(request, "Email already registered")
            return redirect("register")

        user = User.objects.create_user(username=email, password=password)
        user.email = email
        user.first_name = name or ""
        user.save()

        Customer.objects.create(user=user, phone=phone)

        messages.success(request, "Account created successfully! Please login.")
        return redirect("login")

    return render(request, "homeservice/register.html")


# ---------------- TECHNICIAN SIGNUP (single canonical view) ----------------
def techniciansignup(request):
    if request.method == "POST":
        form = TechnicianSignupForm(request.POST, request.FILES)

        if form.is_valid():
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password"]

            # 1️⃣ Check if email already exists
            if User.objects.filter(username=email).exists():
                messages.error(request, "This email is already registered. Please use another email.")
                return redirect("techniciansignup")

            # 2️⃣ Create inactive user
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                is_active=False
            )

            # 3️⃣ Create technician entry
            tech = form.save(commit=False)
            tech.user = user
            tech.is_approved = False
            tech.save()

            # 4️⃣ Send email to technician
            send_mail(
                "Technician Signup Pending Approval",
                "Your signup was successful. Your account is waiting for admin approval.",
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=True,
            )

            # 5️⃣ Redirect to waiting (pending approval) page
            return render(request, "homeservice/technician_pending.html")
        else:
            # Provide a helpful message so user knows to correct validation errors
            messages.error(request, "Please fix the errors highlighted below and resubmit the form.")

    else:
        form = TechnicianSignupForm()

    return render(request, "homeservice/techniciansignup.html", {"form": form})

# ---------------- LOGIN ----------------
def login_view(request):
    if request.method == "POST":
        email = request.POST.get("username")
        password = request.POST.get("password")

        try:
            user_obj = User.objects.get(username=email)
        except User.DoesNotExist:
            messages.error(request, "Invalid email or password")
            return redirect("login")

        user = authenticate(request, username=user_obj.username, password=password)

        if user is None:
            messages.error(request, "Invalid email or password")
            return redirect("login")

        if not user.is_active:
            messages.error(request, "Account inactive. Waiting for admin approval.")
            return redirect("login")

        login(request, user)

        if user.is_superuser:
            return redirect("admindashboard")

        if Technician.objects.filter(user=user, is_approved=True).exists():
            return redirect("techniciandashboard")

        return redirect("dashboard")

    return render(request, "homeservice/login.html")


# ---------------- USER DASHBOARD ----------------
@never_cache
@login_required
def dashboard(request):
    # Prevent technicians from accessing customer dashboard
    if Technician.objects.filter(user=request.user).exists():
        return redirect('techniciandashboard')
    
    # Make sure customer exists and check profile completeness
    customer, _ = Customer.objects.get_or_create(user=request.user)
    missing_fields = []
    if not request.user.first_name:
        missing_fields.append('name')
    if not customer.phone:
        missing_fields.append('phone')
    if not customer.location:
        missing_fields.append('location')

    complete_profile_needed = len(missing_fields) > 0

    requests_qs = ServiceRequest.objects.filter(user=request.user).select_related('technician', 'rating_obj')

    pending_count = requests_qs.filter(status="pending").count()
    open_count = requests_qs.filter(status__iexact="open").count()
    progress_count = requests_qs.filter(status__iexact="assigned").count()
    completed_count = requests_qs.filter(status__iexact="completed").count()
    total_requests = requests_qs.count()  # include all statuses

    reassign_requests = ServiceRequest.objects.filter(
        user=request.user,
        technician__isnull=True,
        status__in=['pending', 'reschedule_rejected'],
    )
    rescheduled_requests = ServiceRequest.objects.filter(user=request.user, status="rescheduled")

    from .utils import get_eligible_technicians_for_request
    for req in reassign_requests:
        req.eligible_technicians = get_eligible_technicians_for_request(req.location)

    context = {
        "pending": pending_count,
        "open": open_count,
        "progress": progress_count,
        "completed": completed_count,
        "recent_requests": requests_qs.order_by("-created_at")[:10],
        "rescheduled_requests": rescheduled_requests,
        "reassign_requests": reassign_requests,
        "total_requests": total_requests,
        "complete_profile_needed": complete_profile_needed,
        "customer": customer,
    }
    return render(request, "homeservice/userdashboard.html", context)


@login_required
def recentservices(request):
    # Prevent technicians from accessing customer recentservices
    if Technician.objects.filter(user=request.user).exists():
        return redirect('techniciandashboard')
    
    services = ServiceRequest.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "homeservice/recentservices.html", {"services": services})


# ---------------- PROFILE ----------------
@login_required
@csrf_protect
def profile(request):
    customer, _created = Customer.objects.get_or_create(user=request.user)

    if request.method == "POST":
        customer.phone = request.POST.get("phone", customer.phone)
        customer.location = request.POST.get("location", customer.location)
        customer.save()
        messages.success(request, "Profile updated.")
        return redirect("profile")

    return render(request, "homeservice/profile.html", {"customer": customer})


# ---------------- FIND SERVICE ----------------
@login_required
@csrf_protect
def findservice(request):
    # Prevent technicians from accessing findservice
    if Technician.objects.filter(user=request.user).exists():
        return redirect('techniciandashboard')
    
    customer = Customer.objects.get(user=request.user)

    # Build a unique list of technician service areas (split by comma, trim, dedupe)
    areas_set = set()
    tech_qs = Technician.objects.filter(service_locations__isnull=False).exclude(service_locations__exact='')
    for tech in tech_qs:
        raw = tech.service_locations or ''
        for area in raw.split(','):
            a = area.strip()
            if a:
                areas_set.add(a)
    areas = sorted(areas_set)

    if request.method == "POST":
        appliance = request.POST.get("appliance_type")
        problem = request.POST.get("problem")
        # Prefer area select if chosen, otherwise fallback to location input
        selected_area = request.POST.get('area', '').strip()
        address_input = request.POST.get("location")

        # Keep the full address the user typed as the ServiceRequest.address
        # Use the selected area only for matching (ServiceRequest.location)
        if selected_area:
            location_for_matching = selected_area
        else:
            location_for_matching = address_input

        if appliance == "other_appliance":
            appliance = request.POST.get("other_appliance")

        if problem == "other_problem":
            problem = request.POST.get("other_problem")

        # Defensive check: prevent near-duplicate submissions (e.g., double clicks)
        from datetime import timedelta
        recent_cutoff = now() - timedelta(minutes=1)
        if ServiceRequest.objects.filter(
            user=request.user,
            service_type=appliance.strip() if isinstance(appliance, str) else appliance,
            problem_description=problem.strip() if isinstance(problem, str) else problem,
            address=(address_input.strip() if isinstance(address_input, str) else address_input),
            created_at__gte=recent_cutoff
        ).exclude(status__iexact="completed").exists():

            logger.info("Duplicate service request prevented for user %s: %s / %s / %s", request.user.id, appliance, problem, address_input)
            messages.warning(request, "We already received a similar request. Please wait for a technician to respond.")
            return redirect("dashboard")

        job = ServiceRequest.objects.create(
            user=request.user,
            service_type=appliance,
            problem_description=problem,
            address=address_input,
            location=location_for_matching,  # Add selected area (or address) for technician matching
            status="open",  # immediately open so technicians may be notified
        )
        logger.info("Created ServiceRequest %s for user %s: %s / %s / %s", job.id, request.user.id, appliance, problem, address_input)

        # notify eligible technicians right away (replacement for admin "send" step)
        from .utils import get_eligible_technicians_for_request
        eligible_technicians = get_eligible_technicians_for_request(job.location)

        # Use the configured SITE_URL for emails (falls back to request build if missing)
        site_url = getattr(settings, "SITE_URL", None)
        if site_url:
            site_url = site_url.rstrip("/")
        else:
            site_url = request.build_absolute_uri("/").rstrip("/")

        login_url = f"{site_url}{reverse('login')}"
        for tech in eligible_technicians:
            try:
                # build a link that directs technician to accept the specific job
                accept_link = f"{site_url}{reverse('accept_job', args=[job.id])}"
                # ensure login page redirects after authentication
                link = f"{login_url}?next={accept_link}"

                # Compose a detailed notification with a single actionable link
                customer_name = request.user.get_full_name() or request.user.username
                customer_phone = customer.phone or "(not provided)"

                email_body = (
                    f"New service request (Job #{job.id}) is available.\n\n"
                    f"Service: {job.service_type}\n"
                    f"Problem: {job.problem_description}\n"
                    f"Address: {job.address}\n"
                    f"Customer: {customer_name}\n"
                    f"Customer phone: {customer_phone}\n\n"
                    f"Open the technician portal to accept the job:\n{link}\n"
                )

                send_mail(
                    "New Service Job Available",
                    email_body,
                    settings.DEFAULT_FROM_EMAIL,
                    [tech.user.email],
                    fail_silently=True,
                )
            except Exception:
                logger.exception("Failed to send notification for ServiceRequest %s to technician %s", job.id, tech.id)

        messages.success(request, "Service request submitted successfully! Technicians have been notified.")
        return redirect("dashboard")

    return render(request, "homeservice/findservice.html", {"customer": customer, "areas": areas})


# ---------------- PROFILE ----------------
@login_required
def profile(request):
    # Prevent technicians from accessing customer profile
    if Technician.objects.filter(user=request.user).exists():
        return redirect('techniciandashboard')
    
    customer, _ = Customer.objects.get_or_create(user=request.user)

    if request.method == "POST":
        # Save name
        full_name = request.POST.get("full_name", "").strip()
        if full_name:
            parts = full_name.split(" ", 1)
            request.user.first_name = parts[0]
            request.user.last_name = parts[1] if len(parts) > 1 else ""
            request.user.save()

        # Save customer details
        customer.phone = request.POST.get("phone", customer.phone)
        customer.location = request.POST.get("location", customer.location)
        customer.save()

        messages.success(request, "Profile updated successfully.")
        return redirect("profile")

    return render(request, "homeservice/profile.html", {
        "customer": customer
    })



# ---------------- RECENT SERVICES ----------------
@login_required
def recentservices(request):
    # Prevent technicians from accessing recentservices
    if Technician.objects.filter(user=request.user).exists():
        return redirect('techniciandashboard')
    
    services = ServiceRequest.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "homeservice/recentservices.html", {"services": services})


# ---------------- ADMIN DASHBOARD ----------------
from django.views.decorators.http import require_GET

@login_required
@csrf_protect
@require_GET  # dashboard never needs to handle POST now
def admindashboard(request):
    if not request.user.is_superuser:
        return redirect('dashboard')

    # Service requests are automatically opened & emailed when created
    # in `findservice` view, so the old manual "send" form is gone.
    # the POST branch that used to exist has been removed completely
    # to avoid any CSRF issues; any legacy pending jobs should already
    # have been handled by the nightly backfill script.

    # All service requests (no filters)
    requests = ServiceRequest.objects.all().order_by('-created_at').select_related('technician', 'rating_obj', 'user__customer')

    # One-time admin notifications for new technician signups
    new_techs = Technician.objects.filter(is_approved=False, admin_notified=False)
    if new_techs.exists():
        cnt = new_techs.count()
        messages.info(request, f"{cnt} new technician signup request{'s' if cnt>1 else ''}. Review technicians to approve or reject.")
        # Mark as notified so notification is shown only once
        new_techs.update(admin_notified=True)

    # One-time admin notifications for new technician payments
    from .models import TechnicianPayment
    new_payments = TechnicianPayment.objects.filter(status='PENDING', admin_notified=False)
    if new_payments.exists():
        cnt = new_payments.count()
        messages.info(request, f"{cnt} new technician payment request{'s' if cnt>1 else ''}. Review payments to approve or reject.")
        # Mark as notified so notification is shown only once
        new_payments.update(admin_notified=True)

    context = {
        "requests": requests,
        "pending": requests.filter(status="pending").count(),
        "open": requests.filter(status="open").count(),
        "assigned": requests.filter(status="assigned").count(),
        "completed": requests.filter(status="completed").count(),
    }
    return render(request, "homeservice/admindashboard.html", context) 


def admin_leaderboard(request):
    if not request.user.is_superuser:
        return redirect('admindashboard')
    
    # Update performance discounts
    from .utils import update_performance_discounts
    update_performance_discounts()
    
    scores = get_monthly_scores()
    return render(request, "homeservice/admin_leaderboard.html", {"scores": scores})


def admin_payments(request):
    if not request.user.is_superuser:
        return redirect('admindashboard')
    
    payments = TechnicianPayment.objects.filter(status='PENDING').select_related('technician').order_by('-created_at')

    # Mark pending payments as notified when admin views payments page
    TechnicianPayment.objects.filter(status='PENDING', admin_notified=False).update(admin_notified=True)
    
    # Compute leaderboard ids and add discount info to each payment
    leaderboard_scores = get_monthly_scores()
    leaderboard_ids = {s['technician_id'] for s in leaderboard_scores}

    for payment in payments:
        original_amount = 300
        final_amount = get_final_amount(payment.technician)
        payment.original_amount = original_amount
        payment.final_amount = final_amount
        payment.has_discount = final_amount < original_amount
        payment.on_leaderboard = payment.technician.id in leaderboard_ids
        # Discount source: None/Monthly/Leaderboard (permanent)
        if payment.technician.discount_percent > 0:
            payment.discount_source = 'Leaderboard' if payment.technician.discount_valid_until is None else 'Monthly'
        else:
            payment.discount_source = None
    
    return render(request, "homeservice/admin_payments.html", {"payments": payments})


@login_required
def export_customers_pdf(request):
    if not request.user.is_superuser:
        return redirect('admindashboard')

    customers = Customer.objects.select_related('user').order_by('id')

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    elements = []

    styles = getSampleStyleSheet()
    elements.append(Paragraph("Customer List", styles['Title']))

    data = [["#", "Name", "Email", "Location", "Phone"]]
    for i, c in enumerate(customers, start=1):
        data.append([
            str(i),
            c.user.first_name or c.user.username,
            c.user.username,
            c.location or "-",
            c.phone or "-",
        ])

    table = Table(data, colWidths=[30, 150, 180, 120, 80])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2d347d')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
    ]))
    elements.append(table)

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="customers.pdf"'
    return response


@login_required
def export_technicians_pdf(request):
    if not request.user.is_superuser:
        return redirect('admindashboard')

    technicians = Technician.objects.order_by('id')

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    elements = []

    styles = getSampleStyleSheet()
    elements.append(Paragraph("Technician List", styles['Title']))

    data = [["#", "Name", "Email", "Phone", "Skill", "Service Areas", "Status"]]
    for i, t in enumerate(technicians, start=1):
        data.append([
            str(i),
            t.name,
            t.email or (t.user.email if t.user else '-'),
            t.phone or '-'
            ,t.skill or '-'
            ,t.service_locations or '-'
            ,('Approved' if t.is_approved else 'Pending')
        ])

    table = Table(data, colWidths=[30, 120, 140, 80, 100, 140, 60])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2d347d')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
    ]))
    elements.append(table)

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="technicians.pdf"'
    return response


@login_required
def admin_reports(request):
    if not request.user.is_superuser:
        return redirect('admindashboard')
    
    from django.db.models import Count, Sum, Avg
    from django.utils import timezone
    import datetime
    
    # Date filters
    today = timezone.now().date()
    this_month = today.replace(day=1)
    last_month = (this_month - datetime.timedelta(days=1)).replace(day=1)
    
    # Service Request Statistics
    total_requests = ServiceRequest.objects.count()
    pending_requests = ServiceRequest.objects.filter(status='pending').count()
    open_requests = ServiceRequest.objects.filter(status='open').count()
    assigned_requests = ServiceRequest.objects.filter(status='assigned').count()
    completed_requests = ServiceRequest.objects.filter(status='completed').count()
    
    # Monthly Statistics
    this_month_requests = ServiceRequest.objects.filter(created_at__date__gte=this_month).count()
    last_month_requests = ServiceRequest.objects.filter(
        created_at__date__gte=last_month, 
        created_at__date__lt=this_month
    ).count()
    
    # Revenue Statistics
    total_revenue = ServiceRequest.objects.filter(status='completed').aggregate(
        total=Sum('service_amount')
    )['total'] or 0
    
    this_month_revenue = ServiceRequest.objects.filter(
        status__iexact='completed', 
        completed_at__date__gte=this_month
    ).aggregate(total=Sum('service_amount'))['total'] or 0
    
    last_month_revenue = ServiceRequest.objects.filter(
        status='completed',
        completed_at__date__gte=last_month,
        completed_at__date__lt=this_month
    ).aggregate(total=Sum('service_amount'))['total'] or 0
    
    # Month names for display
    this_month_name = this_month.strftime('%B %Y')
    last_month_name = last_month.strftime('%B %Y')
    
    # Technician Statistics
    total_technicians = Technician.objects.count()
    active_technicians = Technician.objects.filter(is_active=True).count()
    approved_technicians = Technician.objects.filter(is_approved=True).count()
    pending_technicians = total_technicians - approved_technicians
    
    # Customer Statistics
    total_customers = Customer.objects.count()
    
    # Service Type Distribution - Removed
    # service_types = ServiceRequest.objects.values('service_type').annotate(
    #     count=Count('id')
    # ).order_by('-count')[:10]
    
    # Prepare JSON for JavaScript - Removed
    # import json
    # service_types_list = [{'name': item['service_type'], 'count': item['count']} for item in service_types]
    # if not service_types_list:
    #     service_types_list = [{'name': 'No Data', 'count': 0}]
    # service_types_json = json.dumps(service_types_list)
    
    # Top Performing Technicians
    top_technicians = Technician.objects.filter(is_approved=True).annotate(
        jobs_completed=Count('ratings'),
        avg_rating=Avg('ratings__stars'),
        total_earnings=Sum('ratings__job__service_amount')
    ).order_by('-jobs_completed')[:5]
    
    context = {
        'total_requests': total_requests,
        'pending_requests': pending_requests,
        'open_requests': open_requests,
        'assigned_requests': assigned_requests,
        'completed_requests': completed_requests,
        'this_month_requests': this_month_requests,
        'last_month_requests': last_month_requests,
        'total_revenue': total_revenue,
        'this_month_revenue': this_month_revenue,
        'last_month_revenue': last_month_revenue,
        'this_month_name': this_month_name,
        'last_month_name': last_month_name,
        'total_technicians': total_technicians,
        'active_technicians': active_technicians,
        'approved_technicians': approved_technicians,
        'pending_technicians': pending_technicians,
        'total_customers': total_customers,
        # 'service_types': service_types,  # Removed
        # 'service_types_json': service_types_json,  # Removed
        'top_technicians': top_technicians,
    }
    
    return render(request, "homeservice/admin_reports.html", context)


def approve_payment(request, payment_id):
    # Only admins may approve payments and only via POST
    if not request.user.is_superuser:
        return redirect('admindashboard')

    if request.method != 'POST':
        messages.error(request, "Invalid request method for approving payments.")
        return redirect('admin_payments')

    payment = get_object_or_404(TechnicianPayment, id=payment_id)

    # Idempotent update
    payment.status = 'APPROVED'
    payment.admin_notified = True
    payment.save()

    # Update technician subscription
    technician = payment.technician
    from datetime import date, timedelta
    expiry_date = date.today() + timedelta(days=30)
    technician.subscription_expiry = expiry_date
    technician.is_active = True
    technician.save()

    # Notify technician by email about approval
    try:
        send_mail(
            "Subscription Approved",
            f"Hello {technician.name},\n\nYour payment has been approved and your subscription is active until {expiry_date}. You can now access jobs on your dashboard.\n\nThank you,\nHomeFix Pro",
            settings.DEFAULT_FROM_EMAIL,
            [technician.user.email if technician.user else technician.email],
            fail_silently=True,
        )
    except Exception:
        logger.exception("Failed to send approval email to technician %s", technician.id)

    messages.success(request, f"Payment approved for {technician.name}")
    return redirect('admin_payments')


@login_required
@csrf_protect
def assign_technician(request, request_id):
    if not request.user.is_superuser:
        return redirect("admindashboard")
    
    service_request = get_object_or_404(ServiceRequest, id=request_id)
    
    # Get eligible technicians for this location
    from .utils import get_eligible_technicians_for_request
    eligible_technicians = get_eligible_technicians_for_request(service_request.location)
    
    if request.method == "POST":
        technician_id = request.POST.get("technician_id")
        if technician_id:
            technician_user = get_object_or_404(User, id=technician_id)
            # Check if selected technician is eligible
            if Technician.objects.filter(user=technician_user, id__in=eligible_technicians.values_list('id', flat=True)).exists():
                service_request.technician = technician_user
                service_request.status = "assigned"
                service_request.save()
                messages.success(request, f"Technician assigned to service request {service_request.id}.")
                return redirect("admindashboard")
            else:
                messages.error(request, "Selected technician is not eligible for this location.")
        else:
            messages.error(request, "Please select a technician.")
    
    context = {
        'service_request': service_request,
        'eligible_technicians': eligible_technicians,
    }
    return render(request, "homeservice/assign_technician.html", context)


@login_required
@csrf_protect
def accept_job(request, job_id):
    technician = get_object_or_404(Technician, user=request.user, is_approved=True)
    
    # Check subscription status
    if not technician.is_active:
        messages.error(request, "Your subscription has expired. Please renew to accept jobs.")
        return redirect('technician_payment')
    
    job = get_object_or_404(ServiceRequest, id=job_id, status__iexact="open")
    
    # Check if job is in technician's service area
    areas = technician.service_locations.lower().split(",")
    nearby_areas = [area.strip() for area in areas]
    job_address = job.address.lower()
    is_in_area = any(area in job_address for area in nearby_areas)
    if not is_in_area:
        messages.error(request, "This job is not in your service area.")
        return redirect('techniciandashboard')
    
    job.technician = request.user
    job.status = "assigned"
    job.save()

    messages.success(request, "Job accepted successfully.")
    return redirect("techniciandashboard")


@login_required
@csrf_protect
def complete_job(request, job_id):
    technician = get_object_or_404(Technician, user=request.user, is_approved=True)
    job = get_object_or_404(ServiceRequest, id=job_id, technician=request.user, status__iexact="assigned")

    if request.method == "POST":
        amount = request.POST.get("amount")

        if not amount:
            messages.error(request, "Please enter service amount.")
            return redirect("complete_job", job_id=job.id)

        import uuid
        from django.utils import timezone
        job.service_amount = amount
        job.invoice_number = f"INV-{uuid.uuid4().hex[:8].upper()}"
        job.invoice_generated = True
        job.status = "completed"
        job.completed_at = timezone.now()
        job.save()

        messages.success(request, "Job completed and invoice generated.")
        return redirect("techniciandashboard")

    return render(request, "homeservice/complete_job.html", {
        "job": job
    })


@login_required
@csrf_protect
def respond_reschedule(request, request_id):
    service_request = get_object_or_404(ServiceRequest, id=request_id, user=request.user)

    if service_request.status != 'rescheduled':
        messages.error(request, 'This request is not waiting for your reschedule response.')
        return redirect('dashboard')

    action = request.POST.get('action')
    if action == 'accept':
        service_request.status = 'accepted'
        service_request.save()

        # Notify technician
        technician = Technician.objects.filter(user=service_request.technician).first()
        if technician and technician.user.email:
            site_url = get_site_url(request)
            tech_dashboard = f"{site_url}{reverse('techniciandashboard')}"
            send_mail(
                'Reschedule accepted by user',
                (
                    f"Hello {technician.name},\n\n"
                    f"User {request.user.get_full_name() or request.user.username} accepted the suggested time for request #{service_request.id}.\n"
                    f"Suggested date: {service_request.suggested_date.strftime('%d %B %Y')}\n"
                    f"Suggested time: {service_request.suggested_time.strftime('%I:%M %p')}\n\n"
                    f"See details: {tech_dashboard}\n"
                ),
                settings.DEFAULT_FROM_EMAIL,
                [technician.user.email],
                fail_silently=True,
            )

        messages.success(request, 'Suggested time accepted.')
        return redirect('dashboard')

    if action == 'reject':
        previous_technician = service_request.technician
        service_request.technician = None
        service_request.status = 'reschedule_rejected'
        # Keep suggested_date/time for audit/history, but could be cleared if not needed
        service_request.save()

        # Notify previous technician
        technician = Technician.objects.filter(user=previous_technician).first()
        if technician and technician.user.email:
            send_mail(
                'Reschedule rejected by user',
                (
                    f"Hello {technician.name},\n\n"
                    f"User {request.user.get_full_name() or request.user.username} rejected the suggested time for request #{service_request.id}.\n"
                    f"The service request has been reopened for re-assignment.\n"
                ),
                settings.DEFAULT_FROM_EMAIL,
                [technician.user.email],
                fail_silently=True,
            )

        messages.success(request, 'Suggested time rejected. You can select a new technician below.')
        return redirect('dashboard')

    messages.error(request, 'Invalid action.')
    return redirect('dashboard')


@login_required
@csrf_protect
def user_assign_technician(request, request_id):
    service_request = get_object_or_404(
        ServiceRequest,
        id=request_id,
        user=request.user,
        technician__isnull=True,
        status__in=['pending', 'reschedule_rejected'],
    )

    if request.method == 'POST':
        technician_id = request.POST.get('technician_id')
        technician = get_object_or_404(Technician, id=technician_id, is_active=True, is_approved=True)

        # verify eligibility by location
        eligible = False
        from .utils import get_eligible_technicians_for_request
        eligible_techs = get_eligible_technicians_for_request(service_request.location)
        if technician in eligible_techs:
            eligible = True

        if not eligible:
            messages.error(request, 'Selected technician is not eligible at this location.')
            return redirect('dashboard')

        service_request.technician = technician.user
        service_request.status = 'pending'
        service_request.suggested_date = None
        service_request.suggested_time = None
        service_request.save()

        # notify technician about assignment request
        site_url = get_site_url(request)
        tech_login = f"{site_url}{reverse('technicianlogin')}"
        send_mail(
            'New Service Request Assigned',
            (
                f"Hello {technician.name},\n\n"
                f"A customer has selected you for service request #{service_request.id}.\n"
                f"Preferred date: {service_request.preferred_date.strftime('%d %B %Y')}\n"
                f"Preferred time: {service_request.preferred_time.strftime('%I:%M %p')}\n\n"
                f"Please respond from your dashboard: {tech_login}\n"
            ),
            settings.DEFAULT_FROM_EMAIL,
            [technician.user.email],
            fail_silently=True,
        )

        messages.success(request, 'Technician selection submitted. Await technician response.')
        return redirect('dashboard')

    messages.error(request, 'Invalid request method.')
    return redirect('dashboard')


@login_required
def customerlist(request):
    """
    Show ONLY real customers.
    Exclude:
    - Admin (superuser)
    - Technicians
    """

    customers = Customer.objects.filter(
        user__is_superuser=False          # exclude admin
    ).exclude(
        user__in=Technician.objects.values_list("user", flat=True)
    )

    return render(request, "homeservice/customer.html", {
        "customers": customers
    })


@login_required
def technicians(request):
    from django.db.models import Avg, Count
    technicians_qs = Technician.objects.filter(is_active=True).annotate(
        avg_rating=Avg('ratings__stars'),
        jobs_completed=Count('ratings')
    ).order_by('-discount_percent', '-avg_rating', '-jobs_completed')
    return render(request, "homeservice/technicians.html", {"technicians": technicians_qs})


# ---------------- TECHNICIAN APPROVAL ----------------
@login_required
def approve_technician(request, tech_id):
    tech = get_object_or_404(Technician, id=tech_id)
    tech.is_approved = True
    
    # Set 2-day free trial
    from datetime import timedelta
    from django.utils.timezone import now
    tech.subscription_expiry = now().date() + timedelta(days=2)
    tech.is_active = True
    tech.save()

    # Ensure user exists and activate
    if getattr(tech, "user", None):
        tech.user.is_active = True
        tech.user.save()

    # Send approval email (do not fail silently — surface errors while testing)
    subject = "Your technician account has been approved"
    message = (
        f"Hello {tech.name},\n\n"
        "Your technician account on Home Appliance has been approved by the admin. "
        "You can now log in at: http://127.0.0.1:8000/technicianlogin/ (or your site URL)\n\n"
        "Thanks,\nHome Appliance Team"
    )
    try:
        send_mail(
            subject,
            message,
            getattr(settings, "DEFAULT_FROM_EMAIL", settings.EMAIL_HOST_USER),
            [tech.user.email],
            fail_silently=False,
        )
    except Exception as e:
        # Log/display the error so you can debug email config in dev
        messages.warning(request, f"Approved but email sending failed: {e}")

    messages.success(request, f"{tech.name} has been approved and notified (if email succeeded).")
    return redirect("technicians")



@login_required
def reject_technician(request, tech_id):
    tech = get_object_or_404(Technician, id=tech_id)

    # option: mark rejected (keep record) OR delete. We'll mark as rejected and deactivate user.
    tech.is_approved = False
    tech.save()

    if getattr(tech, "user", None):
        tech.user.is_active = False
        tech.user.save()

        # Notify technician about rejection (surface errors)
        subject = "Technician application rejected"
        message = (
            f"Hello {tech.name},\n\n"
            "We are sorry to inform you that your technician application has been rejected by admin.\n\n"
            "If you believe this is a mistake contact support."
        )
        try:
            send_mail(
                subject,
                message,
                getattr(settings, "DEFAULT_FROM_EMAIL", settings.EMAIL_HOST_USER),
                [tech.user.email],
                fail_silently=False,
            )
        except Exception as e:
            messages.warning(request, f"Rejection saved but email sending failed: {e}")

    messages.success(request, f"{tech.name} has been rejected and notified (if email succeeded).")
    return redirect("technicians")


# ---------------- TECHNICIAN PORTAL (public) ----------------
def technicianportal(request):
    return render(request, "homeservice/technicianportal.html")


# ---------------- TECHNICIAN LOGIN ------------#
def technician_login(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        try:
            tech = Technician.objects.get(user__email=email)
            user = tech.user
            print(f"Login attempt for {user.username}, approved: {tech.is_approved}, active: {user.is_active}")
        except Technician.DoesNotExist:
            messages.error(request, "Invalid login credentials.")
            return redirect("technicianlogin")

        # If technician exists but not yet approved
        if not tech.is_approved or not user.is_active:
            messages.error(request, "Your account is pending admin approval. You cannot log in yet.")
            return redirect("technicianlogin")

        # All good: approved & active
        user = authenticate(request, username=user.username, password=password)
        if user is not None:
            login(request, user)
            return redirect("techniciandashboard")
        else:
            messages.error(request, "Invalid login credentials.")
            return redirect("technicianlogin")

    return render(request, "homeservice/technicianlogin.html")

    return render(request, "homeservice/technicianlogin.html")



# ---------------- FORGOT PASSWORD ----------------
# ---------------- FORGOT PASSWORD ----------------
def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email")

        try:
            tech = Technician.objects.get(user__email=email)
            print(f"Technician found: {tech.name}, approved: {tech.is_approved}")
        except Technician.DoesNotExist:
            messages.info(request, "If an account with that email exists, a reset link has been sent.")
            return redirect("forgot_password")

        # generate reset token
        import secrets
        from django.utils import timezone

        token = secrets.token_urlsafe(32)
        tech.reset_token = token
        tech.save()

        # build reset link
        reset_link = request.build_absolute_uri(
            reverse("reset_password", args=[token])
        )

        # send email
        print("Sending email")
        send_mail(
            subject="Password Reset - Home Appliance",
            message=(
                f"Hello {tech.name},\n\n"
                "You requested a password reset for your technician account.\n\n"
                f"Click the link below to reset your password:\n{reset_link}\n\n"
                "If you didn’t request this, ignore this email."
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", settings.EMAIL_HOST_USER),
            recipient_list=[email],
            fail_silently=False,
        )

        messages.success(request, "If an account with that email exists, a reset link has been sent.")
        return redirect("forgot_password")

    return render(request, "homeservice/forgot_password.html")


# ---------------- RESET PASSWORD ----------------
def reset_password(request, token):
    try:
        tech = Technician.objects.get(reset_token=token)
    except Technician.DoesNotExist:
        messages.error(request, "Invalid or expired reset link.")
        return redirect("technicianlogin")

    if request.method == "POST":
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        print(f"Reset password for {tech.user.username}: password='{password}', confirm='{confirm_password}'")

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect("reset_password", token=token)

        # Update password
        tech.user.set_password(password)
        tech.user.save()

        # Clear token
        tech.reset_token = None
        tech.save()

        messages.success(request, "Password reset successfully. You can now log in.")
        return redirect("technicianlogin")

    return render(request, "homeservice/reset_password.html", {"token": token})



# ---------------- FORGOT PASSWORD CUSTOMER ----------------
def forgot_password_customer(request):
    if request.method == "POST":
        email = request.POST.get("email")

        try:
            customer = Customer.objects.get(user__email=email)
        except Customer.DoesNotExist:
            messages.info(request, "If an account with that email exists, a reset link has been sent.")
            return redirect("forgot_password_customer")

        # generate reset token
        import secrets

        token = secrets.token_urlsafe(32)
        customer.reset_token = token
        customer.save()

        # build reset link
        reset_link = request.build_absolute_uri(
            reverse("reset_password_customer", args=[token])
        )

        # send email
        send_mail(
            subject="Password Reset - Home Appliance",
            message=(
                f"Hello {customer.user.username},\n\n"
                "You requested a password reset for your customer account.\n\n"
                f"Click the link below to reset your password:\n{reset_link}\n\n"
                "If you didn't request this, ignore this email."
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", settings.EMAIL_HOST_USER),
            recipient_list=[email],
            fail_silently=False,
        )

        messages.success(request, "If an account with that email exists, a reset link has been sent.")
        return redirect("forgot_password_customer")

    return render(request, "homeservice/forgot_password_customer.html")



# ---------------- RESET PASSWORD CUSTOMER ----------------
def reset_password_customer(request, token):
    try:
        customer = Customer.objects.get(reset_token=token)
    except Customer.DoesNotExist:
        messages.error(request, "Invalid or expired reset link.")
        return redirect("login")

    if request.method == "POST":
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect("reset_password_customer", token=token)

        # Update password
        customer.user.set_password(password)
        customer.user.save()

        # Clear token
        customer.reset_token = None
        customer.save()

        messages.success(request, "Password reset successfully. You can now log in.")
        return redirect("login")

    return render(request, "homeservice/reset_password_customer.html", {"token": token})



# ---------------- TECHNICIAN DASHBOARD ----------------
@login_required
def techniciandashboard(request):
    technician = get_object_or_404(Technician, user=request.user, is_approved=True)

    # Technician responses: accept / reschedule from available or pending assignment
    if request.method == 'POST':
        job_id = request.POST.get('job_id')
        action = request.POST.get('action')
        if action == 'reschedule':
            job = get_object_or_404(ServiceRequest, id=job_id)
        else:
            job = get_object_or_404(ServiceRequest, id=job_id, technician=request.user)

        if action == 'accept':
            if job.status in ['open']:
                # Take the job from available list
                job.technician = request.user
                job.status = 'pending'
                job.save()
                messages.success(request, 'Job taken for review. Please confirm or suggest new time from pending jobs.')
                return redirect('techniciandashboard')

            if job.status == 'pending':
                job.status = 'accepted'
                job.save()

                # Notify user
                site_url = get_site_url(request)
                user_dashboard = f"{site_url}{reverse('dashboard')}"
                pref_date_text = job.preferred_date.strftime('%d %B %Y') if job.preferred_date else 'N/A'
                pref_time_text = job.preferred_time.strftime('%I:%M %p') if job.preferred_time else 'N/A'
                send_mail(
                    "Service Request Accepted",
                    (
                        f"Hello {job.user.first_name or job.user.username},\n\n"
                        f"Your service request #{job.id} has been accepted by the technician {technician.name}.\n"
                        f"Scheduled date: {pref_date_text}\n"
                        f"Scheduled time: {pref_time_text}\n\n"
                        f"You can view updates here: {user_dashboard}\n"
                    ),
                    settings.DEFAULT_FROM_EMAIL,
                    [job.user.email],
                    fail_silently=True,
                )

                messages.success(request, "Request accepted and user notified.")
                return redirect('techniciandashboard')

        if action == 'reschedule':
            suggested_date = request.POST.get('suggested_date')
            suggested_time = request.POST.get('suggested_time')
            if not suggested_date or not suggested_time:
                messages.error(request, "Please provide suggested date and time for rescheduling.")
                return redirect('techniciandashboard')

            from datetime import datetime
            job.suggested_date = datetime.strptime(suggested_date, '%Y-%m-%d').date()
            job.suggested_time = datetime.strptime(suggested_time, '%H:%M').time()
            job.status = 'rescheduled'
            job.technician = request.user
            job.save()

            site_url = get_site_url(request)
            user_dashboard = f"{site_url}{reverse('dashboard')}"
            pref_date_text = job.preferred_date.strftime('%d %B %Y') if job.preferred_date else 'N/A'
            pref_time_text = job.preferred_time.strftime('%I:%M %p') if job.preferred_time else 'N/A'
            send_mail(
                "Service Request Rescheduled",
                (
                    f"Hello {job.user.first_name or job.user.username},\n\n"
                    f"Technician {technician.name} has suggested a new schedule for your request #{job.id}.\n"
                    f"Original date: {pref_date_text}\n"
                    f"Original time: {pref_time_text}\n"
                    f"Suggested date: {job.suggested_date.strftime('%d %B %Y')}\n"
                    f"Suggested time: {job.suggested_time.strftime('%I:%M %p')}\n\n"
                    f"Please review in your dashboard: {user_dashboard}\n"
                ),
                settings.DEFAULT_FROM_EMAIL,
                [job.user.email],
                fail_silently=True,
            )

            messages.success(request, "Suggestion sent to user and status updated to rescheduled.")
            return redirect('techniciandashboard')

    # Update technician status (auto-block if expired)
    update_technician_status()
    
    # Check subscription status - no redirect, show on dashboard
    # if not technician.is_active:
    #     messages.warning(request, "Your subscription has expired. Please renew to continue.")
    #     return redirect('technician_payment')

    # Only show jobs where the address matches technician's service areas
    areas = technician.service_locations.lower().split(",")
    nearby_areas = [area.strip() for area in areas]
    from django.db.models import Q
    q_objects = Q()
    for area in nearby_areas:
        q_objects |= Q(address__icontains=area)
    available_jobs = ServiceRequest.objects.filter(status="open").filter(q_objects)
    
    # Only show assigned/pending jobs and completed jobs from last 7 days
    from django.utils import timezone
    seven_days_ago = timezone.now() - timezone.timedelta(days=7)
    my_jobs = ServiceRequest.objects.filter(
        technician=request.user
    ).exclude(
        status="completed",
        completed_at__lt=seven_days_ago
    )

    pending_jobs = ServiceRequest.objects.filter(technician=request.user, status="pending")
    rescheduled_jobs = ServiceRequest.objects.filter(technician=request.user, status="rescheduled")
    accepted_jobs = ServiceRequest.objects.filter(technician=request.user, status="accepted")

    return render(
        request,
        "homeservice/techniciandashboard.html",
        {
            "technician": technician,
            "available_jobs": available_jobs,
            "pending_jobs": pending_jobs,
            "rescheduled_jobs": rescheduled_jobs,
            "accepted_jobs": accepted_jobs,
            "services": my_jobs,
            "total_jobs": ServiceRequest.objects.filter(technician=request.user).count(),
            "inprogress_jobs": ServiceRequest.objects.filter(technician=request.user, status__iexact="assigned").count(),
            "completed_jobs": ServiceRequest.objects.filter(technician=request.user, status__iexact="completed").count(),
            "active_page": "dashboard",
        },
    )


@login_required
@csrf_protect
def technician_profile(request):
    technician = get_object_or_404(Technician, user=request.user)

    if request.method == "POST":
        email = request.POST.get("email", technician.email)
        technician.name = request.POST.get("name", technician.name)
        technician.phone = request.POST.get("phone", technician.phone)
        technician.address = request.POST.get("address", technician.address)
        technician.service_locations = request.POST.get("service_locations", technician.service_locations)
        technician.skill = request.POST.get("skill", technician.skill)
        
        # Handle experience_years as integer
        experience_years_str = request.POST.get("experience_years", "").strip()
        if experience_years_str:
            try:
                technician.experience_years = int(experience_years_str)
            except ValueError:
                technician.experience_years = 0
        else:
            technician.experience_years = 0

        # Handle uploaded photo (validate type & size)
        photo = request.FILES.get('photo')
        if photo:
            content_type = getattr(photo, 'content_type', '')
            if content_type not in ['image/jpeg', 'image/png']:
                messages.error(request, 'Only JPEG and PNG images are allowed for profile photo.')
                return redirect('technician_profile')
            if photo.size > 2 * 1024 * 1024:
                messages.error(request, 'Photo size should be less than 2MB.')
                return redirect('technician_profile')
            technician.photo = photo
        
        if email != technician.email:
            if User.objects.filter(username=email).exclude(pk=technician.user.pk).exists():
                messages.error(request, "This email is already in use.")
                technician.save()  # Save the other changes
                return redirect("technician_profile")
            technician.email = email
            technician.user.email = email
            technician.user.username = email
            technician.user.save()
        
        technician.save()
        messages.success(request, "Profile updated successfully.")
        return redirect("technician_profile")

    return render(request, "homeservice/technician_profile.html", {"technician": technician, "active_page": "profile"})


@login_required
def technician_ratings(request):
    technician = get_object_or_404(Technician, user=request.user, is_approved=True)
    
    ratings = Rating.objects.filter(technician=technician).select_related('job__user__customer').order_by('-created_at')

    # Calculate rating statistics
    total_ratings = ratings.count()
    if total_ratings > 0:
        total_score = sum(rating.stars for rating in ratings)
        average_rating = round(total_score / total_ratings, 1)
        five_star_count = sum(1 for rating in ratings if rating.stars == 5)
    else:
        average_rating = 0
        five_star_count = 0

    return render(
        request,
        "homeservice/technician_ratings.html",
        {
            "technician": technician,
            "ratings": ratings,
            "total_ratings": total_ratings,
            "average_rating": average_rating,
            "five_star_count": five_star_count,
            "active_page": "ratings",
        },
    )
@login_required
def technician_payment(request):
    technician = get_object_or_404(Technician, user=request.user, is_approved=True)
    today = now().date()

    # Auto-block if expired
    if technician.subscription_expiry and technician.subscription_expiry < today:
        technician.is_active = False
        technician.save()

    expired = technician.subscription_expiry and technician.subscription_expiry < today
    
    # If no expiry date is set, calculate it (shouldn't happen for approved technicians, but safety check)
    if not technician.subscription_expiry:
        from datetime import timedelta
        technician.subscription_expiry = today + timedelta(days=2)
        technician.save()
    
    final_amount = get_final_amount(technician)

    # Determine if discount is active and its source
    is_discount_active = False
    discount_source = None
    if technician.discount_percent > 0 and (technician.discount_valid_until is None or technician.discount_valid_until >= today):
        is_discount_active = True
        discount_source = 'Leaderboard' if technician.discount_valid_until is None else 'Monthly Reward'

    if request.method == 'POST' and expired:
        screenshot = request.FILES.get('screenshot')
        if screenshot:
            TechnicianPayment.objects.create(
                technician=technician,
                amount=final_amount,
                screenshot=screenshot
            )
            messages.success(request, "Payment screenshot uploaded successfully! Waiting for admin approval.")
            return redirect('technician_payment')
        else:
            messages.error(request, "Please upload a screenshot.")

    # Check if there's a pending payment
    pending_payment = TechnicianPayment.objects.filter(
        technician=technician, 
        status='PENDING'
    ).first()
    
    context = {
        "expired": expired,
        "amount": final_amount,
        "expiry": technician.subscription_expiry,
        "tech": technician,
        "pending_payment": pending_payment,
        "is_discount_active": is_discount_active,
        "discount_source": discount_source,
        "active_page": "payment",
    }
    return render(request, "homeservice/technician_payment.html", context)

@login_required
def edit_technician_status(request, tech_id):
    tech = get_object_or_404(Technician, id=tech_id)

    if request.method == "POST":
        new_status = request.POST.get("status")

        if new_status == "approved":
            tech.is_approved = True

            # safe user update
            if tech.user_id:
                tech.user.is_active = True
                tech.user.save()

            messages.success(request, f"{tech.name} is now Approved.")

        elif new_status == "rejected":
            tech.is_approved = False

            if tech.user_id:
                tech.user.is_active = False
                tech.user.save()

            messages.success(request, f"{tech.name} is now Rejected.")

        tech.save()
        return redirect("technicians")

    return render(request, "homeservice/edittech.html", {"tech": tech})


# ---------------- TECHNICIAN LOGOUT ----------------
def technician_logout(request):
    logout(request)
    return redirect("technicianlogin")


# ---------------- USER LOGOUT ----------------
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def logoutpage(request):
    if request.method == "POST":
        logout(request)
        return redirect("login")
    return render(request, "homeservice/logoutpage.html")


@login_required
@csrf_protect
def logout_ajax(request):
    """AJAX logout endpoint for dashboards. Returns JSON."""
    if request.method != 'POST':
        return HttpResponse(status=405)

    logout(request)
    return HttpResponse('{"success": true}', content_type='application/json')


@login_required
def view_invoice(request, request_id):
    service_request = get_object_or_404(ServiceRequest, id=request_id, user=request.user)
    
    context = {
        'service_request': service_request,
        'customer': request.user.customer,
        'technician': service_request.technician.technician if service_request.technician else None,
        'center_name': 'Home Appliance Service Center',
    }
    return render(request, 'homeservice/view_invoice.html', context)


@login_required
def request_detail(request, request_id):
    service_request = get_object_or_404(ServiceRequest, id=request_id)
    
    # Allow superusers or the request owner
    if not (request.user.is_superuser or service_request.user == request.user):
        return redirect('dashboard')
    
    context = {
        'service_request': service_request,
        'customer': service_request.user.customer,
        'technician': Technician.objects.get(user=service_request.technician) if service_request.technician else None,
    }
    return render(request, 'homeservice/request_detail.html', context)


@login_required
def rate_technician(request, request_id):
    # Prevent technicians from rating
    if Technician.objects.filter(user=request.user).exists():
        return redirect('techniciandashboard')
    
    # Allow case-insensitive matching for status (e.g., 'Completed', 'completed')
    service_request = get_object_or_404(ServiceRequest, id=request_id, user=request.user, status__iexact='completed')
    
    if request.method == 'POST':
        rating_value = request.POST.get('rating')
        review = request.POST.get('review', '').strip()
        
        if rating_value and rating_value.isdigit():
            rating_int = int(rating_value)
            try:
                technician = Technician.objects.get(user=service_request.technician)  # Get the Technician instance
            except Technician.DoesNotExist:
                messages.error(request, "Technician profile not found for this service — cannot rate.")
                return redirect('dashboard')
            
            # Create or update rating
            rating_obj, created = Rating.objects.get_or_create(
                job=service_request,
                defaults={
                    'technician': technician,
                    'stars': rating_int,
                    'auto_generated': False,
                }
            )
            if not created:
                rating_obj.stars = rating_int
                # If the rating was previously auto-generated, mark it as user submitted now
                if rating_obj.auto_generated:
                    rating_obj.auto_generated = False
                rating_obj.save()

            # Also save review to ServiceRequest for backward compatibility
            service_request.review = review if review else None
            # Keep numeric rating on ServiceRequest synced too
            if service_request.rating != rating_int:
                service_request.rating = rating_int
            service_request.save()
            
            messages.success(request, "Thank you for rating the technician!")
        else:
            messages.error(request, "Please select a rating.")
        
        return redirect('dashboard')
    
    return redirect('dashboard')


# ---------------- MY JOBS (Technician) ----------------
@login_required
def my_jobs(request):
    technician = get_object_or_404(Technician, user=request.user, is_approved=True)
    
    # Only show completed services
    completed_jobs = ServiceRequest.objects.filter(
        technician=request.user, 
        status="completed"
    ).select_related('user__customer').order_by('-completed_at')
    
    return render(request, "homeservice/my_jobs.html", {
        "technician": technician,
        "completed_jobs": completed_jobs,
        "active_page": "jobs",
    })
from .utils import send_sms

def submit_service_request(request):

    # after saving the request
    service_type = request.POST.get("service_type")
    user_location = request.POST.get("location")

    message = f"""
New Home Appliance Service Request

Service: {service_type}
Location: {user_location}

Full request details have been sent to your email.
Please login to the portal.

https://homeappliances-1qf6.onrender.com
"""

    technicians = Technician.objects.filter(service_area=user_location)

    for tech in technicians:
        send_sms(tech.phone_number, message)
from django.db import models
from django.contrib.auth.models import User


# ------------------ CUSTOMER MODEL ------------------
class Customer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(max_length=15, blank=True)
    location = models.CharField(max_length=100, blank=True)
    reset_token = models.CharField(max_length=100, blank=True, null=True)  # For password reset

    def __str__(self):
        return self.user.username


# ------------------ TECHNICIAN MODEL ------------------
# Includes:
# - Skill dropdown
# - Email stored in model
# - Admin approval
# - File upload for ID proof
SKILL_CHOICES = [
    ("AC Repair", "AC Repair"),
    ("Refrigerator Repair", "Refrigerator Repair"),
    ("Washing Machine Repair", "Washing Machine Repair"),
    ("Microwave Repair", "Microwave Repair"),
    ("Television Repair", "Television Repair"),
    ("Plumbing", "Plumbing"),
    ("Electrical Work", "Electrical Work"),
    ("Others", "Others"),
]


class Technician(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    name = models.CharField(max_length=100)
    email = models.EmailField()  # easier for admin lookup + views.py compatibility
    phone = models.CharField(max_length=20)

    skill = models.CharField(max_length=100, choices=SKILL_CHOICES)
    address = models.TextField(help_text="Technician's home address")
    service_locations = models.TextField(help_text="Comma separated areas where technician can work")

    experience_years = models.PositiveIntegerField(default=0)

    idproof = models.FileField(upload_to="idproofs/")
    experience_certificate = models.FileField(upload_to="experience_certificates/", null=True, blank=True)

    # Optional profile photo for technician
    photo = models.ImageField(upload_to="technicians/photos/", null=True, blank=True) 

    is_approved = models.BooleanField(default=False)  # admin must approve
    admin_notified = models.BooleanField(default=False, help_text="Set True when admin has been shown a one-time notification for this signup")
    reset_token = models.CharField(max_length=100, blank=True, null=True)  # For password reset

    # New fields for rating system
    discount_percent = models.IntegerField(default=0)
    discount_valid_until = models.DateField(null=True, blank=True)
    subscription_expiry = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.skill})"


# ------------------ SERVICE REQUEST MODEL ------------------
class ServiceRequest(models.Model):

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('open', 'Open for Technicians'),
        ('assigned', 'Assigned'),
        ('completed', 'Completed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='requests')
    technician = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_jobs'
    )

    service_type = models.CharField(max_length=100)
    problem_description = models.TextField()
    address = models.TextField()
    location = models.CharField(max_length=100, default='')  # Service area for technician matching

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # Check constraint removed for compatibility with installed Django version.
        # Original intent: prevent a ServiceRequest from being marked completed without a technician.
        pass

    service_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True
    )

    invoice_number = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    invoice_generated = models.BooleanField(default=False)

    rating = models.IntegerField(
        null=True,
        blank=True,
        choices=[(1, '1 Star'), (2, '2 Stars'), (3, '3 Stars'), (4, '4 Stars'), (5, '5 Stars')]
    )
    review = models.TextField(null=True, blank=True)


# ------------------ RATING MODEL ------------------
class Rating(models.Model):
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name='ratings')
    job = models.OneToOneField(ServiceRequest, on_delete=models.CASCADE, related_name='rating_obj')
    stars = models.IntegerField(choices=[(1, '1'), (2, '2'), (3, '3'), (4, '4'), (5, '5')])
    auto_generated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Rating {self.stars} for {self.technician.name} on job {self.job.id}"


# ------------------ TECHNICIAN PAYMENT MODEL ------------------
class TechnicianPayment(models.Model):
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE)
    amount = models.IntegerField()
    screenshot = models.ImageField(upload_to="payments/")
    status = models.CharField(max_length=20, default="PENDING", choices=[
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected')
    ])
    # One-time admin notification flag: when False and status=PENDING, admin dashboard should show a message
    admin_notified = models.BooleanField(default=False, help_text='Set True when admin has been shown a one-time notification for this payment')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment {self.amount} by {self.technician.name} - {self.status}"


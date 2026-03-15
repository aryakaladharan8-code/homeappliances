from django.db.models import Avg, Count, Max
from django.utils.timezone import now
from datetime import date, timedelta
from .models import Rating, Technician, ServiceRequest


# Nearby location mapping for technician dispatch
NEARBY_LOCATIONS = {
    "Perumbavoor": ["Perumbavoor", "Kothamangalam", "Muvattupuzha", "Aluva"],
    "Aluva": ["Aluva", "Perumbavoor", "Kochi"],
    "Kothamangalam": ["Kothamangalam", "Perumbavoor", "Muvattupuzha"],
    "Muvattupuzha": ["Muvattupuzha", "Perumbavoor", "Kothamangalam"],
    "Kochi": ["Kochi", "Aluva", "Ernakulam"],
    "Ernakulam": ["Ernakulam", "Kochi", "Aluva"],
}


def get_nearby_areas(location):
    """Get list of nearby areas for a given location"""
    return NEARBY_LOCATIONS.get(location, [location])


def get_eligible_technicians_for_request(request_address):
    """Get technicians eligible to handle a request in the given address"""
    user_address = request_address.lower()
    technicians = Technician.objects.filter(is_active=True, is_approved=True)
    matched = []
    
    for tech in technicians:
        areas = tech.service_locations.lower().split(",")
        for area in areas:
            area = area.strip()
            if area in user_address:
                matched.append(tech)
                break
    
    return matched


def get_monthly_scores():
    today = now().date()
    month_start = today.replace(day=1)

    # First, get technicians who meet the criteria: minimum 5 completed jobs and avg rating > 4.5
    eligible_technicians = []
    technicians = Technician.objects.filter(is_approved=True)
    for tech in technicians:
        completed_jobs = ServiceRequest.objects.filter(technician=tech.user, status='completed').count()
        avg_rating = Rating.objects.filter(technician=tech).aggregate(avg=Avg('stars'))['avg'] or 0
        if completed_jobs >= 5 and avg_rating > 4.5:
            eligible_technicians.append(tech.id)

    # Now, get monthly scores only for eligible technicians
    data = Rating.objects.filter(
        created_at__date__gte=month_start,
        technician__in=eligible_technicians
    ).values('technician').annotate(
        avg_rating=Avg('stars'),
        jobs=Count('id'),
        technician_name=Max('technician__name')
    )

    scores = []
    for row in data:
        score = row['avg_rating'] * row['jobs']
        scores.append({
            "technician_id": row['technician'],
            "technician_name": row['technician_name'],
            "avg_rating": row['avg_rating'],
            "jobs": row['jobs'],
            "score": score
        })

    return sorted(scores, key=lambda x: x['score'], reverse=True)


def give_monthly_rewards():
    scores = get_monthly_scores()
    today = now().date()

    Technician.objects.update(discount_percent=0, discount_valid_until=None)

    # Give 20% discount to all eligible technicians who appeared on the leaderboard
    for score in scores:
        tech = Technician.objects.get(id=score['technician_id'])
        tech.discount_percent = 20
        tech.discount_valid_until = today + timedelta(days=30)
        tech.save()


def update_performance_discounts():
    """Update discounts for technicians with minimum 5 completed jobs and avg rating > 4.5"""
    from .models import ServiceRequest
    
    technicians = Technician.objects.filter(is_approved=True)
    
    for tech in technicians:
        completed_jobs = ServiceRequest.objects.filter(technician=tech.user, status='completed').count()
        avg_rating = Rating.objects.filter(technician=tech).aggregate(avg=Avg('stars'))['avg'] or 0
        
        if completed_jobs >= 5 and avg_rating > 4.5:
            tech.discount_percent = 20
            tech.discount_valid_until = None  # Permanent discount
            tech.save()
        else:
            # If they don't qualify, remove the performance discount, but keep monthly if active
            if tech.discount_valid_until is None:  # Only remove if it's the performance discount
                tech.discount_percent = 0
                tech.save()


def get_final_amount(technician):
    base = 300

    if technician.discount_percent > 0 and (technician.discount_valid_until is None or technician.discount_valid_until >= now().date()):
        discount = base * technician.discount_percent / 100
        return base - discount

    return base


def check_subscriptions():
    today = now().date()
    Technician.objects.filter(subscription_expiry__lt=today).update(is_active=False)


def update_technician_status():
    """Update technician status - call this when technician logs in or accesses dashboard"""
    today = now().date()
    Technician.objects.filter(subscription_expiry__lt=today).update(is_active=False)

import os
from twilio.rest import Client

def send_sms(phone, message):

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")

    client = Client(account_sid, auth_token)

    client.messages.create(
        body=message,
        from_="+16562695997",
        to=phone
    )
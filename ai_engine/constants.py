"""
Centralized AI Engine constants, categories, priorities, and visual styles.
Reused across AI classification, UI badges, filters, and dashboard analytics.
"""

# The 10 Primary Objective Categories
PRIMARY_CATEGORIES = [
    "Education",
    "Job/Internship",
    "Work",
    "Finance",
    "Personal",
    "Shopping",
    "Promotion",
    "Newsletter",
    "Notification",
    "Other",
]

EMAIL_CATEGORIES = [
    "Education",
    "Job/Internship",
    "Work",
    "Finance",
    "Personal",
    "Shopping",
    "Promotion",
    "Newsletter",
    "Notification",
    "Other",
    # Extended domains for backwards compatibility
    "Bills",
    "Travel",
    "Social",
    "Jobs",
    "Promotions",
    "Notifications",
    "Government",
    "Healthcare",
    "Technology",
]

# Case-insensitive lookup set
EMAIL_CATEGORIES_LOOKUP = {c.lower(): c for c in EMAIL_CATEGORIES}

# Backward-compatibility & synonym alias map (maps variants to canonical primary categories)
CATEGORY_ALIASES = {
    "job & internship": "Job/Internship",
    "job/internship": "Job/Internship",
    "jobs": "Job/Internship",
    "job": "Job/Internship",
    "internship": "Job/Internship",
    "internships": "Job/Internship",
    "career": "Job/Internship",
    "careers": "Job/Internship",
    "promotion": "Promotion",
    "promotions": "Promotion",
    "marketing": "Promotion",
    "newsletter": "Newsletter",
    "newsletters": "Newsletter",
    "notification": "Notification",
    "notifications": "Notification",
    "alert": "Notification",
    "alerts": "Notification",
    "bills & payments": "Finance",
    "bills": "Finance",
    "bill": "Finance",
    "banking": "Finance",
    "transaction": "Finance",
    "social": "Personal",
    "travel": "Personal",
    "technology": "Work",
    "healthcare": "Personal",
    "government": "Notification",
}

CATEGORY_META = {
    "Education": {
        "icon": "bi-mortarboard",
        "color": "primary",
        "bg": "bg-primary-subtle",
        "text": "text-primary",
        "border": "border-primary-subtle"
    },
    "Work": {
        "icon": "bi-briefcase",
        "color": "info",
        "bg": "bg-info-subtle",
        "text": "text-info",
        "border": "border-info-subtle"
    },
    "Finance": {
        "icon": "bi-currency-dollar",
        "color": "warning",
        "bg": "bg-warning-subtle",
        "text": "text-warning",
        "border": "border-warning-subtle"
    },
    "Personal": {
        "icon": "bi-heart",
        "color": "danger",
        "bg": "bg-danger-subtle",
        "text": "text-danger",
        "border": "border-danger-subtle"
    },
    "Shopping": {
        "icon": "bi-bag",
        "color": "secondary",
        "bg": "bg-secondary-subtle",
        "text": "text-secondary",
        "border": "border-secondary-subtle"
    },
    "Bills": {
        "icon": "bi-receipt",
        "color": "danger",
        "bg": "bg-danger-subtle",
        "text": "text-danger",
        "border": "border-danger-subtle"
    },
    "Travel": {
        "icon": "bi-airplane",
        "color": "primary",
        "bg": "bg-primary-subtle",
        "text": "text-primary",
        "border": "border-primary-subtle"
    },
    "Social": {
        "icon": "bi-people",
        "color": "info",
        "bg": "bg-info-subtle",
        "text": "text-info",
        "border": "border-info-subtle"
    },
    "Promotions": {
        "icon": "bi-tag",
        "color": "warning",
        "bg": "bg-warning-subtle",
        "text": "text-warning",
        "border": "border-warning-subtle"
    },
    "Jobs": {
        "icon": "bi-person-badge",
        "color": "success",
        "bg": "bg-success-subtle",
        "text": "text-success",
        "border": "border-success-subtle"
    },
    "Government": {
        "icon": "bi-building",
        "color": "dark",
        "bg": "bg-dark-subtle",
        "text": "text-emphasis-dark",
        "border": "border-dark-subtle"
    },
    "Healthcare": {
        "icon": "bi-hospital",
        "color": "danger",
        "bg": "bg-danger-subtle",
        "text": "text-danger",
        "border": "border-danger-subtle"
    },
    "Technology": {
        "icon": "bi-cpu",
        "color": "info",
        "bg": "bg-info-subtle",
        "text": "text-info",
        "border": "border-info-subtle"
    },
    "Job/Internship": {
        "icon": "bi-person-badge",
        "color": "success",
        "bg": "bg-success-subtle",
        "text": "text-success",
        "border": "border-success-subtle"
    },
    "Promotion": {
        "icon": "bi-tag",
        "color": "warning",
        "bg": "bg-warning-subtle",
        "text": "text-warning",
        "border": "border-warning-subtle"
    },
    "Newsletter": {
        "icon": "bi-newspaper",
        "color": "info",
        "bg": "bg-info-subtle",
        "text": "text-info",
        "border": "border-info-subtle"
    },
    "Notification": {
        "icon": "bi-bell",
        "color": "secondary",
        "bg": "bg-secondary-subtle",
        "text": "text-secondary",
        "border": "border-secondary-subtle"
    },
    "Notifications": {
        "icon": "bi-bell",
        "color": "secondary",
        "bg": "bg-secondary-subtle",
        "text": "text-secondary",
        "border": "border-secondary-subtle"
    },
    "Other": {
        "icon": "bi-folder",
        "color": "secondary",
        "bg": "bg-secondary-subtle",
        "text": "text-secondary",
        "border": "border-secondary-subtle"
    },
}

ALLOWED_PRIORITIES = ["High", "Medium", "Low"]

PRIORITY_META = {
    "High": {
        "badge": "bg-danger-subtle text-danger border border-danger-subtle",
        "icon": "bi-exclamation-circle-fill",
    },
    "Medium": {
        "badge": "bg-warning-subtle text-warning-emphasis border border-warning-subtle",
        "icon": "bi-dash-circle",
    },
    "Low": {
        "badge": "bg-secondary-subtle text-secondary border border-secondary-subtle",
        "icon": "bi-arrow-down-circle",
    },
}


def normalize_category(raw_category: str) -> str:
    """
    Normalizes a category string to the canonical controlled category list.
    Returns 'Other' if no match is found.
    """
    if not raw_category:
        return "Other"
    clean = str(raw_category).strip()
    lower = clean.lower()
    # Check alias first for canonical mapping (e.g. 'jobs' -> 'Job/Internship')
    if lower in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[lower]
    # Direct match
    if clean in EMAIL_CATEGORIES:
        return clean
    # Case-insensitive match
    if lower in EMAIL_CATEGORIES_LOOKUP:
        return EMAIL_CATEGORIES_LOOKUP[lower]
    return "Other"

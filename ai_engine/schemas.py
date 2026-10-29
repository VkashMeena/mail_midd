"""
Strict schema definition and validation for AI classification outputs.
Ensures AI responses are rigorously validated before writing to the database.
"""
from dataclasses import dataclass
from typing import Dict, Any, Union
from .constants import EMAIL_CATEGORIES, ALLOWED_PRIORITIES, EMAIL_CATEGORIES_LOOKUP, CATEGORY_ALIASES
from .exceptions import AIValidationError


@dataclass
class AIClassificationResult:
    category: str
    importance: bool
    priority: str
    confidence: float
    reason: str
    objective: str = ""
    action_required: bool = False

    @property
    def is_important(self) -> bool:
        return self.importance

    def to_dict(self) -> Dict[str, Any]:
        return {
            'category': self.category,
            'is_important': self.importance,
            'importance': self.importance,
            'priority': self.priority,
            'confidence': self.confidence,
            'objective': self.objective,
            'reason': self.reason,
            'action_required': self.action_required,
        }


def validate_classification_payload(data: Dict[str, Any]) -> AIClassificationResult:
    """
    Validates raw dictionary from AI output against strict requirements:
    1. category ∈ EMAIL_CATEGORIES (no arbitrary categories)
    2. priority ∈ ['High', 'Medium', 'Low']
    3. importance is boolean
    4. confidence is float in [0.0, 1.0] (safely converts 0-100 or '94%')
    5. reason is non-empty string <= 500 characters
    """
    if not isinstance(data, dict):
        raise AIValidationError(f"Expected JSON object, got {type(data).__name__}")

    # 1. Validate Category
    raw_category = data.get('category')
    if not raw_category or not isinstance(raw_category, str):
        raise AIValidationError("Missing or non-string 'category' in AI response.")

    clean_category = raw_category.strip()
    lower_cat = clean_category.lower()
    if clean_category in EMAIL_CATEGORIES:
        pass
    elif lower_cat in EMAIL_CATEGORIES_LOOKUP:
        clean_category = EMAIL_CATEGORIES_LOOKUP[lower_cat]
    elif lower_cat in CATEGORY_ALIASES:
        clean_category = CATEGORY_ALIASES[lower_cat]
    else:
        raise AIValidationError(f"Invalid category '{raw_category}'. Allowed: {', '.join(EMAIL_CATEGORIES)}")

    # 2. Validate Priority
    raw_priority = data.get('priority')
    if not raw_priority or not isinstance(raw_priority, str):
        raise AIValidationError("Missing or non-string 'priority' in AI response.")

    clean_priority = raw_priority.strip().capitalize()
    if clean_priority not in ALLOWED_PRIORITIES:
        raise AIValidationError(f"Invalid priority '{raw_priority}'. Allowed: {', '.join(ALLOWED_PRIORITIES)}")

    # 3. Validate Importance
    raw_importance = data.get('importance')
    if raw_importance is None and 'is_important' in data:
        raw_importance = data.get('is_important')
    if isinstance(raw_importance, bool):
        importance = raw_importance
    elif isinstance(raw_importance, str):
        imp_lower = raw_importance.strip().lower()
        if imp_lower in ('true', 'yes', 'important', '1', 'high'):
            importance = True
        elif imp_lower in ('false', 'no', 'normal', '0', 'low', 'medium'):
            importance = False
        else:
            raise AIValidationError(f"Cannot parse boolean importance from '{raw_importance}'")
    elif isinstance(raw_importance, (int, float)):
        importance = bool(raw_importance)
    else:
        raise AIValidationError("Missing or invalid 'importance' in AI response.")

    # 4. Validate Confidence (Range 0.0 - 1.0)
    raw_confidence = data.get('confidence')
    if raw_confidence is None:
        confidence = 0.85  # Reasonable fallback default if omitted
    else:
        try:
            if isinstance(raw_confidence, str):
                cleaned_str = raw_confidence.strip().rstrip('%')
                val = float(cleaned_str)
                if '%' in raw_confidence or val > 1.0:
                    val = val / 100.0
            else:
                val = float(raw_confidence)
                if val > 1.0:
                    val = val / 100.0

            if not (0.0 <= val <= 1.0):
                raise AIValidationError(f"Confidence {val} is outside [0.0, 1.0]")
            confidence = round(val, 2)
        except (ValueError, TypeError) as exc:
            raise AIValidationError(f"Invalid confidence value '{raw_confidence}': {exc}")

    # 5. Validate Reason
    raw_reason = data.get('reason', '')
    if not isinstance(raw_reason, str):
        reason = str(raw_reason)
    else:
        reason = raw_reason.strip()

    # Bound reason length to 500 characters
    if len(reason) > 500:
        reason = reason[:497] + '...'

    if not reason:
        reason = f"Classified as {clean_category} ({clean_priority} priority)."

    # 6. Validate Objective & Action Required
    raw_objective = data.get('objective', '')
    objective = str(raw_objective).strip() if raw_objective else f"{clean_category} communication"
    if len(objective) > 500:
        objective = objective[:497] + '...'

    raw_action = data.get('action_required')
    if isinstance(raw_action, bool):
        action_required = raw_action
    elif isinstance(raw_action, str):
        action_required = raw_action.strip().lower() in ('true', 'yes', '1', 'required')
    else:
        action_required = bool(importance and clean_priority == 'High')

    return AIClassificationResult(
        category=clean_category,
        importance=importance,
        priority=clean_priority,
        confidence=confidence,
        reason=reason,
        objective=objective,
        action_required=action_required
    )


@dataclass
class AISummaryResult:
    overview: str
    important_points: list
    action_items: list
    category_summary: list

    def to_dict(self) -> Dict[str, Any]:
        return {
            'overview': self.overview,
            'important_points': self.important_points,
            'action_items': self.action_items,
            'category_summary': self.category_summary,
        }


def validate_summary_payload(data: Dict[str, Any]) -> AISummaryResult:
    """
    Validates structured daily summary JSON payload against strict schema:
    1. overview: non-empty string summarizing the day
    2. important_points: list of strings (key updates)
    3. action_items: list of strings (concrete tasks)
    4. category_summary: list of {"category": str, "highlight": str}
    """
    if not isinstance(data, dict):
        raise AIValidationError(f"Expected JSON object for daily summary, got {type(data).__name__}")

    # 1. Validate Overview
    raw_overview = data.get('overview') or data.get('daily_summary')
    if not raw_overview or not isinstance(raw_overview, str) or not raw_overview.strip():
        raise AIValidationError("Missing or empty 'overview' in daily summary response.")
    overview = raw_overview.strip()
    if len(overview) > 3000:
        overview = overview[:2997] + '...'

    # 2. Validate Important Points
    raw_important = data.get('important_points') or data.get('important_items') or []
    if isinstance(raw_important, str):
        raw_important = [raw_important]
    elif not isinstance(raw_important, list):
        raw_important = []

    important_points = []
    for item in raw_important:
        if isinstance(item, str) and item.strip():
            txt = item.strip()
            important_points.append(txt[:300] if len(txt) > 300 else txt)

    # 3. Validate Action Items
    raw_actions = data.get('action_items') or []
    if isinstance(raw_actions, str):
        raw_actions = [raw_actions]
    elif not isinstance(raw_actions, list):
        raw_actions = []

    action_items = []
    for item in raw_actions:
        if isinstance(item, str) and item.strip():
            txt = item.strip()
            action_items.append(txt[:300] if len(txt) > 300 else txt)

    # 4. Validate Category Summary
    raw_cat_summary = data.get('category_summary') or []
    category_summary = []
    if isinstance(raw_cat_summary, list):
        for entry in raw_cat_summary:
            if isinstance(entry, dict):
                cat = str(entry.get('category', 'Other')).strip()
                hl = str(entry.get('highlight', '')).strip()
                if hl:
                    category_summary.append({
                        'category': cat,
                        'highlight': hl[:300]
                    })
    elif isinstance(raw_cat_summary, dict):
        for cat, hl in raw_cat_summary.items():
            if str(hl).strip():
                category_summary.append({
                    'category': str(cat).strip(),
                    'highlight': str(hl).strip()[:300]
                })

    return AISummaryResult(
        overview=overview,
        important_points=important_points,
        action_items=action_items,
        category_summary=category_summary
    )


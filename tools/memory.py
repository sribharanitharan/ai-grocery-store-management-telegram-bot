"""
Owner preference / memory tools.
Preferences persist across sessions in the owner_preferences SQLite table.
"""
from db.database import get_db
from db.models import OwnerPreference


def set_preference(key: str, value: str) -> str:
    """
    Save an owner preference that persists across all sessions. Use when the owner
    sets a default or configures the store (e.g. 'always use UPI', 'my GSTIN is X',
    'shop name is Y', 'my phone number is Z').

    Common preference keys:
    - default_payment: 'cash', 'upi', or 'card'
    - shop_name: Name of the store
    - gstin: GST Identification Number (15-char alphanumeric)
    - shop_address: Full shop address for invoices
    - shop_owner: Owner's name
    - phone: Contact phone number

    Args:
        key: Preference key (e.g. 'default_payment', 'shop_name', 'gstin')
        value: Preference value to store
    """
    key = key.strip().lower().replace(" ", "_")
    value = value.strip()

    if not key or not value:
        return "❌ Both key and value must be non-empty."

    with get_db() as db:
        pref = db.query(OwnerPreference).filter_by(key=key).first()
        if pref:
            old_value = pref.value
            pref.value = value
            return f"✅ Updated '{key}': '{old_value}' → '{value}'"
        else:
            db.add(OwnerPreference(key=key, value=value))
            return f"✅ Saved '{key}' = '{value}'"


def get_preference(key: str) -> str:
    """
    Retrieve a stored owner preference by key.

    Args:
        key: Preference key to look up
    """
    key = key.strip().lower().replace(" ", "_")

    with get_db() as db:
        pref = db.query(OwnerPreference).filter_by(key=key).first()
        if pref:
            return f"🔧 {key} = '{pref.value}'"
        return f"ℹ️ No preference set for '{key}'."


def list_preferences() -> str:
    """
    List all stored owner preferences. Useful to review what has been configured
    for the store.
    """
    with get_db() as db:
        prefs = db.query(OwnerPreference).order_by(OwnerPreference.key).all()
        if not prefs:
            return "ℹ️ No preferences configured yet."

        lines = ["🔧 Store Preferences:\n"]
        for p in prefs:
            lines.append(f"  {p.key}: {p.value}")
        return "\n".join(lines)


def get_all_preferences_dict() -> dict:
    """
    Internal helper — returns all preferences as a plain dict.
    Used by the agent core to inject into system prompt context.
    """
    with get_db() as db:
        prefs = db.query(OwnerPreference).all()
        return {p.key: p.value for p in prefs}

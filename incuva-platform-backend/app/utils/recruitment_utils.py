from datetime import datetime, timezone


def to_datetime(value, default=None):
    """Normalise une date Firestore / ISO / datetime en datetime aware (UTC).

    Firestore renvoie des DatetimeWithNanoseconds (sous-classe de datetime, sans
    méthode `to_datetime`) ; les dates naïves sont considérées comme UTC.
    Renvoie `default` si la valeur est absente ou illisible.
    """
    if value is None:
        return default
    if hasattr(value, 'to_datetime'):
        value = value.to_datetime()
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return default
    if not isinstance(value, datetime):
        return default
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def application_date(application, default=None):
    """Date d'une candidature : `applied_at`, sinon `submitted_at` (ancien champ)."""
    return to_datetime(application.get('applied_at') or application.get('submitted_at'), default)


def display_name(user, fallback=''):
    """Nom complet d'un utilisateur, quel que soit le schéma (first_name/name ou firstName/lastName)."""
    if not user:
        return fallback
    first = user.get('first_name') or user.get('firstName') or ''
    last = user.get('name') or user.get('lastName') or ''
    return f"{first} {last}".strip() or fallback

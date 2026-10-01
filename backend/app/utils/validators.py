import re


def validate_password(password):
    """
    Validate password strength
    Returns (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if len(password) > 128:
        return False, "Password must be less than 128 characters"
    if not re.search(r'[A-Za-z]', password):
        return False, "Password must contain at least one letter"
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    return True, None


def validate_display_name(name):
    """
    Validate display name
    Returns (is_valid, error_message)
    """
    if not name or len(name.strip()) == 0:
        return False, "Display name is required"
    if len(name) < 2:
        return False, "Display name must be at least 2 characters"
    if len(name) > 50:
        return False, "Display name must be less than 50 characters"
    # Allow letters, numbers, spaces, and some special chars
    if not re.match(r'^[\w\s\-\.]+$', name, re.UNICODE):
        return False, "Display name contains invalid characters"
    return True, None


def validate_config_name(name):
    """Validate LLM config name"""
    if not name or len(name.strip()) == 0:
        return False, "Config name is required"
    if len(name) < 2:
        return False, "Config name must be at least 2 characters"
    if len(name) > 100:
        return False, "Config name must be less than 100 characters"
    return True, None


def validate_system_prompt(prompt):
    """Validate system prompt"""
    if prompt and len(prompt) > 10000:
        return False, "System prompt must be less than 10000 characters"
    return True, None

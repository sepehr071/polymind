"""
DLP rule catalog — compiled regexes + validator helpers + BUILTIN_RULES list.

All regexes are compiled once at module import. Validator callables accept
a single str (the matched text) and return bool (True = keep the match).
"""
import re
import math


# ---------------------------------------------------------------------------
# Validator helpers
# ---------------------------------------------------------------------------

def luhn_valid(s: str) -> bool:
    """Luhn checksum — strip non-digits first."""
    digits = re.sub(r'\D', '', s)
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def iban_mod97(s: str) -> bool:
    """
    ISO 13616 IBAN mod-97 check.
    Move first 4 chars to end, replace A→10..Z→35, compute int mod 97 == 1.
    """
    # Remove spaces/dashes
    iban = re.sub(r'[\s-]', '', s).upper()
    if len(iban) < 5:
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = ''
    for ch in rearranged:
        if ch.isdigit():
            numeric += ch
        elif ch.isalpha():
            numeric += str(ord(ch) - ord('A') + 10)
        else:
            return False
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def iran_id_check(s: str) -> bool:
    """
    Iran national ID (10-digit) checksum validator.
    Rejects all-same-digit IDs.
    Algorithm: sum(d[i] * (10 - i) for i in 0..8) % 11 => remainder;
    if remainder < 2: last digit must equal remainder;
    else: last digit must equal 11 - remainder.
    """
    digits = re.sub(r'\D', '', s)
    if len(digits) != 10:
        return False
    # Reject all-same-digit
    if len(set(digits)) == 1:
        return False
    total = sum(int(digits[i]) * (10 - i) for i in range(9))
    remainder = total % 11
    last = int(digits[9])
    if remainder < 2:
        return last == remainder
    return last == (11 - remainder)


def shannon_entropy(s: str) -> float:
    """Shannon entropy in bits per character."""
    if not s:
        return 0.0
    length = len(s)
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    entropy = 0.0
    for count in freq.values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy


def is_high_entropy(s: str) -> bool:
    """
    Return True if s looks like a machine-generated secret:
    - Shannon entropy > 4.5
    - >= 12 distinct characters (proxy for charset diversity >= 32 expected)
    - not purely digits
    - not purely alpha
    """
    if not s or len(s) < 24:
        return False
    if s.isdigit():
        return False
    if s.isalpha():
        return False
    distinct = len(set(s))
    if distinct < 12:
        return False
    return shannon_entropy(s) > 4.5


# ---------------------------------------------------------------------------
# Compiled regexes (case-sensitive unless noted)
# ---------------------------------------------------------------------------

_AWS_ACCESS_RE = re.compile(r'\bAKIA[0-9A-Z]{16}\b')

# AWS secret key: 40-char base64-ish token not adjacent to other token chars
_AWS_SECRET_RE = re.compile(
    r'(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])'
)

_OPENAI_RE = re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b')

_ANTHROPIC_RE = re.compile(
    r'\bsk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_-]{20,}\b'
)

_GITHUB_PAT_RE = re.compile(r'\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{30,}\b')

_GOOGLE_API_RE = re.compile(r'\bAIza[0-9A-Za-z_-]{35}\b')

_SLACK_RE = re.compile(r'\bxox[abprs]-[A-Za-z0-9-]{10,}\b')

_STRIPE_RE = re.compile(r'\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}\b')

_PRIVATE_KEY_RE = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')

_JWT_RE = re.compile(
    r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b'
)

_CREDIT_CARD_RE = re.compile(r'\b(?:\d[ -]*?){13,19}\b')

# Cheap hotspot pre-filter for digit-cluster regexes (credit card, Iran ID).
# Matches either a 10+ digit run or a 4-digit / 4-digit pair. If neither is
# present we can skip the heavy regex + Luhn pass — Luhn was O(n) per span and
# `_CREDIT_CARD_RE` runs the validator on every match, so on a 100KB chat
# message with no digits the savings are large.
_DIGIT_HOTSPOT_RE = re.compile(r'\d{10,}|\d{4}[ -]\d{4}')

_IBAN_RE = re.compile(r'\b[A-Z]{2}\d{2}[A-Z0-9]{1,30}\b')

_IRAN_ID_RE = re.compile(r'\b\d{10}\b')

_EMAIL_RE = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
)

_PHONE_INTL_RE = re.compile(
    r'(?<!\d)\+?\d{1,3}[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}(?!\d)'
)

_IPV4_PRIVATE_RE = re.compile(
    r'\b(?:'
    r'10\.(?:\d{1,3}\.){2}\d{1,3}'
    r'|172\.(?:1[6-9]|2\d|3[01])\.(?:\d{1,3}\.)\d{1,3}'
    r'|192\.168\.(?:\d{1,3}\.)\d{1,3}'
    r')\b'
)

# Generic high-entropy catch-all (24–512 chars, base64-ish charset)
_HIGH_ENTROPY_RE = re.compile(r'\b[A-Za-z0-9_/+=-]{24,512}\b')

# Generic credential assignment — catches "api_key = <value>", "password: <value>",
# "client_secret=<value>", "Authorization: Bearer <token>" regardless of vendor.
# Requires an explicit ``:``/``=`` separator after the keyword (or the literal
# "Bearer " prefix) so prose like "the token authentication system" doesn't match.
_GENERIC_API_KEY_RE = re.compile(
    r'(?i)(?:'
    r'\b(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?key|auth[_-]?token'
    r'|client[_-]?secret|password|passwd|pwd|token)\b\s*[:=]\s*'
    r'|\bbearer\s+'
    r')["\']?[A-Za-z0-9_\-./+=]{12,}["\']?'
)


# ---------------------------------------------------------------------------
# BUILTIN_RULES catalog
# ---------------------------------------------------------------------------

BUILTIN_RULES: list[dict] = [
    {
        "id": "aws_access_key",
        "name": "AWS Access Key",
        "severity": "critical",
        "default_action": "block",
        "category": "secrets",
        "description": "Looks like an AWS access-key ID — leaking this can grant full account access.",
        "regex": _AWS_ACCESS_RE,
        "validate": None,
        "min_len": 20,
    },
    {
        "id": "aws_secret_key",
        "name": "AWS Secret Key",
        "severity": "critical",
        "default_action": "block",
        "category": "secrets",
        "description": "Looks like an AWS secret access key — pairs with the access ID to control your cloud.",
        "regex": _AWS_SECRET_RE,
        # Filter false-positives: require high entropy
        "validate": is_high_entropy,
        "min_len": 40,
    },
    {
        "id": "anthropic_api_key",
        "name": "Anthropic API Key",
        "severity": "critical",
        "default_action": "block",
        "category": "secrets",
        "description": "Looks like an Anthropic API key — exposes paid API access tied to your account.",
        "regex": _ANTHROPIC_RE,
        "validate": None,
        "min_len": 20,
    },
    {
        "id": "openai_api_key",
        "name": "OpenAI API Key",
        "severity": "critical",
        "default_action": "block",
        "category": "secrets",
        "description": "Looks like an OpenAI API key — exposes paid API access tied to your account.",
        "regex": _OPENAI_RE,
        "validate": None,
        "min_len": 20,
    },
    {
        "id": "github_pat",
        "name": "GitHub Personal Access Token",
        "severity": "critical",
        "default_action": "block",
        "category": "secrets",
        "description": "Looks like a GitHub personal access token — can read or push to your repositories.",
        "regex": _GITHUB_PAT_RE,
        "validate": None,
        "min_len": 30,
    },
    {
        "id": "google_api_key",
        "name": "Google API Key",
        "severity": "critical",
        "default_action": "block",
        "category": "secrets",
        "description": "Looks like a Google Cloud API key — can be billed or abused if leaked.",
        "regex": _GOOGLE_API_RE,
        "validate": None,
        "min_len": 35,
    },
    {
        "id": "slack_token",
        "name": "Slack Token",
        "severity": "critical",
        "default_action": "block",
        "category": "secrets",
        "description": "Looks like a Slack token — can read messages and post on behalf of a workspace.",
        "regex": _SLACK_RE,
        "validate": None,
        "min_len": 10,
    },
    {
        "id": "stripe_secret",
        "name": "Stripe Secret Key",
        "severity": "critical",
        "default_action": "block",
        "category": "secrets",
        "description": "Looks like a Stripe secret key — exposes payment-processing access to your account.",
        "regex": _STRIPE_RE,
        "validate": None,
        "min_len": 20,
    },
    {
        "id": "private_key_pem",
        "name": "PEM Private Key",
        "severity": "critical",
        "default_action": "block",
        "category": "secrets",
        "description": "Looks like a PEM-formatted private key — never paste cryptographic private keys.",
        "regex": _PRIVATE_KEY_RE,
        "validate": None,
        "min_len": 0,
    },
    {
        "id": "jwt_token",
        "name": "JSON Web Token",
        "severity": "high",
        "default_action": "block",
        "category": "secrets",
        "description": "Looks like a JSON Web Token — can be replayed to impersonate a logged-in session.",
        "regex": _JWT_RE,
        "validate": None,
        "min_len": 30,
    },
    {
        "id": "credit_card",
        "name": "Credit Card Number",
        "severity": "high",
        "default_action": "block",
        "category": "financial",
        "description": "Looks like a credit-card number — sharing this can enable fraud.",
        "regex": _CREDIT_CARD_RE,
        "validate": luhn_valid,
        "min_len": 13,
        # Cheap pre-filter — skip heavy regex + Luhn unless a 10+ digit run
        # or 4-4 digit grouping shows up somewhere in the text.
        "pre_filter": _DIGIT_HOTSPOT_RE,
    },
    {
        "id": "iban",
        "name": "IBAN",
        "severity": "high",
        "default_action": "block",
        "category": "financial",
        "description": "Looks like an IBAN — exposing bank-account identifiers can enable financial abuse.",
        "regex": _IBAN_RE,
        "validate": iban_mod97,
        "min_len": 5,
    },
    {
        "id": "national_id_iran",
        "name": "Iran National ID",
        "severity": "high",
        "default_action": "block",
        "category": "identity",
        "description": "Looks like an Iranian national ID — government identifier subject to privacy rules.",
        "regex": _IRAN_ID_RE,
        "validate": iran_id_check,
        "min_len": 10,
        # Same cheap hotspot — `_IRAN_ID_RE` matches every 10-digit run, and
        # the Iran-ID checksum runs on each. Bail early when no run is present.
        "pre_filter": _DIGIT_HOTSPOT_RE,
    },
    {
        "id": "email",
        "name": "Email Address",
        "severity": "low",
        "default_action": "warn",
        "category": "pii",
        "description": "Looks like an email address — sharing personal contact info may violate privacy rules.",
        "regex": _EMAIL_RE,
        "validate": None,
        "min_len": 5,
    },
    {
        "id": "phone_intl",
        "name": "International Phone Number",
        "severity": "low",
        "default_action": "warn",
        "category": "pii",
        "description": "Looks like a phone number — personal contact info that may breach privacy policy.",
        "regex": _PHONE_INTL_RE,
        "validate": None,
        "min_len": 7,
    },
    {
        "id": "ipv4_private",
        "name": "Private IPv4 Address",
        "severity": "medium",
        "default_action": "warn",
        "category": "network",
        "description": "Looks like an internal IP address — could expose internal network structure.",
        "regex": _IPV4_PRIVATE_RE,
        "validate": None,
        "min_len": 7,
    },
    # Note: "internal_hostname" is NOT in this static list.
    # It is built dynamically from policy["internal_hostname_suffixes"] at scan time.
    {
        "id": "high_entropy_token",
        "name": "High-Entropy Token",
        "severity": "medium",
        "default_action": "warn",
        "category": "secrets",
        "description": "Looks like a high-entropy secret or token — may be a credential.",
        "regex": _HIGH_ENTROPY_RE,
        "validate": is_high_entropy,
        "min_len": 24,
    },
    {
        "id": "generic_api_key",
        "name": "API Key or Password",
        "severity": "high",
        "default_action": "block",
        "category": "secrets",
        "description": "Looks like an API key, token, or password written as a key=value pair — credentials should not be shared in chat.",
        "regex": _GENERIC_API_KEY_RE,
        "validate": None,
        "min_len": 12,
    },
]

from email_validator import EmailNotValidError, validate_email


def normalize_email(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return validate_email(value, check_deliverability=False).normalized
    except EmailNotValidError as error:
        raise ValueError("Escribe un correo electrónico válido.") from error

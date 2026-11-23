"""Durable rental credentials; scanning requests handover, never proves it."""
import secrets

from .parking_qr import qr_svg


def issue_rental_qr(hold, now):
    return dict(token='emobility:rental:' + secrets.token_urlsafe(32),
                issued_at=now, expires_at=hold['expires_at'])


def rental_qr_details(hold, now):
    qr = hold['qr']
    status = hold['status']
    usable = status == 'ACTIVE' and now < qr['expires_at']
    messages = {
        'ACTIVE': 'Valid for a pickup request. Vehicle readiness will be checked again.',
        'HANDOVER_PENDING': 'Pickup requested; awaiting handover evidence.',
        'CONSUMED': 'Already used. This code cannot start another journey.',
        'CANCELLED': 'Hold cancelled. This code is no longer valid.',
        'EXPIRED': 'Hold expired. This code is no longer valid.',
    }
    message = messages.get(status, 'This code is not valid for pickup.')
    if status == 'ACTIVE' and not usable:
        message = 'Hold expired. This code is no longer valid.'
    return dict(hold_id=hold['id'], owner_id=hold['owner_id'], vehicle_id=hold['vehicle_id'],
                pickup_hub_id=hold.get('pickup_hub_id'), **qr, status=status, usable=usable,
                message=message, svg=qr_svg(qr['token']))

"""Local QR encoding and durable, opaque parking confirmation codes.

The code is a reservation credential, not device evidence. Authorization,
expiry and receipt idempotency remain inside the domain transaction.
"""
import secrets

import qrcode
from qrcode.image.svg import SvgPathFillImage

from .shared import POLICY


def issue_parking_qr(right, now):
    return dict(token='emobility:parking:' + secrets.token_urlsafe(32),
                issued_at=now, expires_at=right['start'] + POLICY['no_show'])


def qr_svg(token):
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                         box_size=8, border=4)
    code.add_data(token)
    code.make(fit=True)
    return code.make_image(image_factory=SvgPathFillImage).to_string(encoding='unicode')


def qr_details(right, now):
    qr = right['qr']
    status = right['status']
    usable = status == 'CONFIRMED' and now <= qr['expires_at']
    messages = {
        'CONFIRMED': 'Valid for an arrival request. Reception conditions will be checked again.',
        'HANDOVER_PENDING': 'Arrival requested; awaiting reception evidence. Do not check in again.',
        'CONSUMED': 'Already used. This code cannot start a second parking visit.',
        'CANCELLED': 'Reservation cancelled. This code is no longer valid.',
        'EXPIRED': 'Reservation expired. This code is no longer valid.',
        'OFFERED': 'Alternative reception has not yet been accepted.',
    }
    message = messages.get(status, 'This code is not valid for check-in.')
    if status == 'CONFIRMED' and not usable:
        message = 'Arrival grace period has elapsed. This code is no longer valid.'
    return dict(right_id=right['id'], **qr, status=status, usable=usable,
                message=message, svg=qr_svg(qr['token']))

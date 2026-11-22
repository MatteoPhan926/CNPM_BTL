"""Count a user's live service groups from one committed domain snapshot.

No expiry clock or synthetic statuses: Service.tick resolves expiry before this
projection. Physical handovers remain active until evidence resolves them.
"""
from .shared import LIVE_SESSION


def active_service_count(state, actor_id):
    def owned(kind):
        return [row for row in state.get(kind, {}).values() if row.get('owner_id') == actor_id]

    services = set()
    for request in owned('charge_requests'):
        if request['status'] == 'PENDING':
            services.add(('charge_request', request['id']))
    trips = owned('trips')
    rental_key = lambda trip: ('rental', trip.get('hold_id') or trip['id'])
    return_groups = {trip['return_right_id']: rental_key(trip)
                     for trip in trips if trip.get('return_right_id')}
    returned = {trip['return_right_id'] for trip in trips
                if trip['status'] == 'CLOSED' and trip.get('return_right_id')}

    def parking_key(right_id):
        return return_groups.get(right_id, ('parking', right_id))

    for hold in owned('holds'):
        if hold['status'] in ('ACTIVE', 'HANDOVER_PENDING'):
            services.add(('rental', hold['id']))
    for trip in trips:
        if trip['status'] in ('OPEN', 'HANDOVER_PENDING', 'ASSISTANCE_PENDING'):
            services.add(rental_key(trip))
    for right in owned('rights'):
        # An unaccepted recovery proposal is not an additional booked service.
        if right['status'] in ('CONFIRMED', 'HANDOVER_PENDING'):
            services.add(parking_key(right['id']))
    for visit in owned('visits'):
        if visit['status'] not in ('PARKED', 'HANDOVER_PENDING'):
            continue
        if visit.get('right_id') in returned:
            # Rental has ended; this is now fleet occupancy, not student parking.
            continue
        services.add(parking_key(visit['right_id']) if visit.get('right_id')
                     else ('visit', visit['id']))
    for session in owned('sessions'):
        if session['status'] not in LIVE_SESSION:
            continue
        right = state['rights'].get(session.get('right_id'), {})
        bundled = session.get('created_parking') or right.get('created_by_charge')
        services.add(parking_key(session['right_id']) if bundled
                     else ('charging', session['id']))
    return len(services)

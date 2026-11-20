# bank/context_processors.py
def pending_payouts(request):
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
        from bank.models import PayoutRequest, PayoutStatus, TopUpRequest, TopUpStatus
        return {
            'pending_payouts_count': PayoutRequest.objects.filter(status=PayoutStatus.PENDING).count(),
            'pending_topups_count': TopUpRequest.objects.filter(status=TopUpStatus.PENDING).count(),
        }
    return {'pending_payouts_count': 0, 'pending_topups_count': 0}
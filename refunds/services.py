from django.utils import timezone


def create_refund_from_resignation(resignation):
    """
    Create a Refund record when a manager APPROVES a resignation.
    Idempotent: returns the existing refund if already created.
    """
    from .models import Refund, RefundSourceType

    existing = Refund.objects.filter(resignation=resignation).first()
    if existing:
        return existing

    if resignation.estimated_payout <= 0:
        return None

    return Refund.objects.create(
        source_type=RefundSourceType.RESIGNATION,
        resignation=resignation,
        member=resignation.member,
        amount=resignation.estimated_payout,
        approved_at=timezone.now(),
    )


def create_refund_from_installment(installment):
    """
    Create a Refund record when staff REJECTS a BANK_TRANSFER installment.
    Only creates a refund for BANK_TRANSFER since SAVINGS rejections are
    handled by reversing the savings balance directly.
    Idempotent: returns the existing refund if already created.
    """
    from .models import Refund, RefundSourceType

    if installment.payment_method != 'BANK_TRANSFER':
        return None

    existing = Refund.objects.filter(installment=installment).first()
    if existing:
        return existing

    return Refund.objects.create(
        source_type=RefundSourceType.INSTALLMENT,
        installment=installment,
        member=installment.loan.member,
        amount=installment.amount,
        approved_at=timezone.now(),
    )


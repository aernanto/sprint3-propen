from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from members.models import Member
from savings.models import SavingsBalance, SavingTransaction, SavingStatus, SavingType


class Command(BaseCommand):
    help = 'Recalculate SavingsBalance for all members from SavingTransaction records with status=SUCCESS.'

    def handle(self, *args, **options):
        zero = Decimal('0')
        members = Member.objects.all()
        self.stdout.write(f'Recalculating balance for {members.count()} member(s)...')

        for member in members:
            with transaction.atomic():
                balance, _ = SavingsBalance.objects.get_or_create(member=member)
                balance.total_pokok = zero
                balance.total_wajib = zero
                balance.total_sukarela = zero

                txs = SavingTransaction.objects.filter(member=member, status=SavingStatus.SUCCESS)
                for tx in txs:
                    if tx.saving_type == SavingType.POKOK:
                        balance.total_pokok += tx.amount
                    elif tx.saving_type == SavingType.WAJIB:
                        balance.total_wajib += tx.amount
                    elif tx.saving_type == SavingType.SUKARELA:
                        balance.total_sukarela += tx.amount
                balance.save()

                self.stdout.write(
                    f'  {member.full_name}: '
                    f'Pokok={balance.total_pokok}, Wajib={balance.total_wajib}, '
                    f'Sukarela={balance.total_sukarela}'
                )

        self.stdout.write(self.style.SUCCESS('Done.'))

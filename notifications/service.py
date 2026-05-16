"""
notifications/service.py

Helper functions untuk membuat notifikasi + kirim email.
Setiap fungsi akan:
1. Bikin in-app notification utk recipient utama (biasanya member)
2. Broadcast in-app notification ke staff/manager yg relevan (kalau applicable)
3. Kirim email ke semua recipient (sync, fail_silently)

Catatan:
- Semua email dikirim sync pakai send_mail dengan fail_silently=True
- Kegagalan email tidak boleh nge-block flow utama
- Role yg dipake: STAFF, MANAGER (sesuai User.role di members app)
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail

from .models import Notification

User = get_user_model()


# ── Internal Helpers ───────────────────────────────────────────────────────

def _get_staff_users():
    """Ambil semua user dengan role STAFF (utk broadcast notif staff)."""
    try:
        return list(User.objects.filter(role='STAFF', is_active=True))
    except Exception:
        return []


def _get_manager_users():
    """Ambil semua user dengan role MANAGER (utk broadcast notif manager)."""
    try:
        return list(User.objects.filter(role='MANAGER', is_active=True))
    except Exception:
        return []


def _send_email_safe(subject, body, recipients):
    """
    Kirim email sync dengan fail_silently=True.
    `recipients` = list of email string. Duplicate dan empty akan di-filter.
    """
    if not recipients:
        return
    clean_recipients = list({r for r in recipients if r})
    if not clean_recipients:
        return

    full_subject = f'[SI-MAPAN] {subject}'
    try:
        send_mail(
            full_subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            clean_recipients,
            fail_silently=True,
        )
    except Exception:
        pass


def _create_notifications_bulk(users, notif_type, title, message, redirect_url):
    """Bikin in-app notif untuk list of users sekaligus."""
    notifications = [
        Notification(
            recipient=user,
            type=notif_type,
            title=title,
            message=message,
            redirect_url=redirect_url,
        )
        for user in users if user is not None
    ]
    if notifications:
        try:
            Notification.objects.bulk_create(notifications)
        except Exception:
            # Fallback ke create satu-satu kalau bulk_create error
            for notif in notifications:
                try:
                    notif.save()
                except Exception:
                    pass


def _broadcast(
    member_user,
    member_email,
    staff_message,
    staff_title,
    staff_redirect_url,
    notif_type,
    member_title,
    member_message,
    member_redirect_url,
    broadcast_to='STAFF',
    email_body_member=None,
    email_body_staff=None,
    email_subject_member=None,
    email_subject_staff=None,
):
    """
    Core broadcast: bikin notif ke member + staff/manager, kirim email ke semua.
    """
    # 1. In-app notif ke member
    if member_user is not None and member_title and member_message:
        try:
            Notification.objects.create(
                recipient=member_user,
                type=notif_type,
                title=member_title,
                message=member_message,
                redirect_url=member_redirect_url,
            )
        except Exception:
            pass

    # 2. In-app notif broadcast ke staff/manager
    if broadcast_to == 'STAFF':
        broadcast_users = _get_staff_users()
    elif broadcast_to == 'MANAGER':
        broadcast_users = _get_manager_users()
    elif broadcast_to == 'STAFF_AND_MANAGER':
        broadcast_users = _get_staff_users() + _get_manager_users()
    else:
        broadcast_users = []

    if broadcast_users and staff_title and staff_message:
        _create_notifications_bulk(
            broadcast_users,
            notif_type,
            staff_title,
            staff_message,
            staff_redirect_url,
        )

    # 3. Kirim email ke member
    if member_email and email_subject_member and email_body_member:
        _send_email_safe(email_subject_member, email_body_member, [member_email])

    # 4. Kirim email ke staff/manager
    if broadcast_users and email_subject_staff and email_body_staff:
        staff_emails = [u.email for u in broadcast_users if u.email]
        _send_email_safe(email_subject_staff, email_body_staff, staff_emails)


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════

def notify_registration_pending(member):
    """Member baru register → member dapet notif, staff dapet notif verifikasi."""
    member_msg = (
        'Pendaftaran keanggotaan Anda telah kami terima dan sedang dalam proses review. '
        'Kami akan mengirim notifikasi apabila verifikasi selesai.'
    )
    staff_msg = (
        f'Calon anggota baru atas nama {member.full_name} ({member.user.email}) '
        'telah mendaftar dan menunggu verifikasi.'
    )

    email_member = (
        f'Yth. {member.full_name},\n\n'
        'Pendaftaran keanggotaan Anda di SI-MAPAN telah kami terima '
        'dan sedang dalam proses review oleh petugas kami.\n\n'
        'Anda akan menerima notifikasi lanjutan setelah verifikasi selesai.\n\n'
        'Salam,\nTim SI-MAPAN'
    )
    email_staff = (
        f'Ada pendaftaran anggota baru yang perlu diverifikasi:\n\n'
        f'Nama    : {member.full_name}\n'
        f'Email   : {member.user.email}\n'
        f'NIK     : {member.nik}\n\n'
        'Silakan login ke dashboard SI-MAPAN untuk memproses verifikasi.\n\n'
        'Salam,\nSistem SI-MAPAN'
    )

    _broadcast(
        member_user=member.user,
        member_email=member.user.email,
        notif_type='REGISTRATION',
        member_title='Pendaftaran Diterima',
        member_message=member_msg,
        member_redirect_url='/status',
        staff_title='Pendaftaran Anggota Baru',
        staff_message=staff_msg,
        staff_redirect_url='/dashboard/staff/members/pending',
        broadcast_to='STAFF',
        email_subject_member='Pendaftaran Anda Telah Diterima',
        email_body_member=email_member,
        email_subject_staff='Pendaftaran Anggota Baru Menunggu Verifikasi',
        email_body_staff=email_staff,
    )


def notify_registration_verified(member):
    """Staff approve member → member dapet notif + email."""
    member_msg = (
        'Selamat! Pendaftaran keanggotaan Anda telah disetujui. '
        'Silakan lakukan setoran simpanan pokok untuk mengaktifkan keanggotaan.'
    )
    email_member = (
        f'Yth. {member.full_name},\n\n'
        'Selamat! Pendaftaran keanggotaan Anda di SI-MAPAN telah diverifikasi '
        'dan status keanggotaan Anda sekarang adalah VERIFIED.\n\n'
        'Langkah selanjutnya: silakan lakukan setoran simpanan pokok '
        'untuk mengaktifkan keanggotaan Anda.\n\n'
        'Login ke aplikasi SI-MAPAN untuk melanjutkan.\n\n'
        'Salam,\nTim SI-MAPAN'
    )

    _broadcast(
        member_user=member.user,
        member_email=member.user.email,
        notif_type='REGISTRATION',
        member_title='Pendaftaran Disetujui',
        member_message=member_msg,
        member_redirect_url='/dashboard/member',
        staff_title='',
        staff_message='',
        staff_redirect_url='',
        broadcast_to=None,
        email_subject_member='Pendaftaran Anda Telah Disetujui',
        email_body_member=email_member,
    )


def notify_registration_rejected(member, reason=''):
    """Staff reject member → member dapet notif + email."""
    member_msg = 'Pendaftaran keanggotaan Anda ditolak.'
    if reason:
        member_msg += f' Alasan: {reason}'

    email_member = (
        f'Yth. {member.full_name},\n\n'
        'Mohon maaf, pendaftaran keanggotaan Anda di SI-MAPAN tidak dapat disetujui.\n'
    )
    if reason:
        email_member += f'Alasan penolakan: {reason}\n'
    email_member += (
        '\nApabila ada pertanyaan, silakan hubungi petugas kami.\n\n'
        'Salam,\nTim SI-MAPAN'
    )

    _broadcast(
        member_user=member.user,
        member_email=member.user.email,
        notif_type='REGISTRATION',
        member_title='Pendaftaran Ditolak',
        member_message=member_msg,
        member_redirect_url='/status',
        staff_title='',
        staff_message='',
        staff_redirect_url='',
        broadcast_to=None,
        email_subject_member='Pendaftaran Anda Ditolak',
        email_body_member=email_member,
    )


# ═══════════════════════════════════════════════════════════════════════════
# SAVINGS
# ═══════════════════════════════════════════════════════════════════════════

def notify_saving_received(saving):
    """Member submit setoran → member + staff dapet notif."""
    member_msg = (
        f'Setoran {saving.saving_type} ({saving.saving_id}) telah kami terima '
        'dan menunggu verifikasi petugas.'
    )
    staff_msg = (
        f'Setoran baru dari {saving.member.full_name} '
        f'({saving.saving_type}, Rp {saving.amount:,.0f}) menunggu verifikasi.'
    )

    email_member = (
        f'Yth. {saving.member.full_name},\n\n'
        f'Bukti setoran simpanan {saving.saving_type} Anda ({saving.saving_id}) '
        f'senilai Rp {saving.amount:,.0f} telah kami terima '
        'dan sedang dalam proses verifikasi oleh petugas.\n\n'
        'Anda akan menerima notifikasi setelah verifikasi selesai.\n\n'
        'Salam,\nTim SI-MAPAN'
    )
    email_staff = (
        f'Ada setoran simpanan baru yang menunggu verifikasi:\n\n'
        f'Anggota    : {saving.member.full_name}\n'
        f'Jenis      : {saving.saving_type}\n'
        f'Nominal    : Rp {saving.amount:,.0f}\n'
        f'ID Setoran : {saving.saving_id}\n\n'
        'Silakan login ke dashboard untuk memproses verifikasi.\n\n'
        'Salam,\nSistem SI-MAPAN'
    )

    _broadcast(
        member_user=saving.member.user,
        member_email=saving.member.user.email,
        notif_type='SAVING',
        member_title='Setoran Diterima',
        member_message=member_msg,
        member_redirect_url='/savings',
        staff_title='Setoran Simpanan Baru',
        staff_message=staff_msg,
        staff_redirect_url='/dashboard/staff/savings/pending',
        broadcast_to='STAFF',
        email_subject_member='Setoran Anda Telah Diterima',
        email_body_member=email_member,
        email_subject_staff='Setoran Simpanan Menunggu Verifikasi',
        email_body_staff=email_staff,
    )


def notify_saving_verified(saving):
    """Staff verify setoran → member dapet notif + email."""
    member_msg = (
        f'Setoran Anda ({saving.saving_id}) telah berhasil diverifikasi '
        'dan ditambahkan ke saldo simpanan.'
    )
    email_member = (
        f'Yth. {saving.member.full_name},\n\n'
        f'Setoran simpanan Anda ({saving.saving_id}) senilai Rp {saving.amount:,.0f} '
        'telah berhasil diverifikasi dan ditambahkan ke saldo simpanan Anda.\n\n'
        'Terima kasih.\n\n'
        'Salam,\nTim SI-MAPAN'
    )

    _broadcast(
        member_user=saving.member.user,
        member_email=saving.member.user.email,
        notif_type='SAVING',
        member_title='Setoran Terverifikasi',
        member_message=member_msg,
        member_redirect_url='/savings',
        staff_title='', staff_message='', staff_redirect_url='',
        broadcast_to=None,
        email_subject_member='Setoran Anda Telah Diverifikasi',
        email_body_member=email_member,
    )


def notify_saving_rejected(saving, reason=''):
    """Staff reject setoran → member dapet notif + email."""
    member_msg = f'Setoran ({saving.saving_id}) tidak dapat diverifikasi.'
    if reason:
        member_msg += f' Alasan: {reason}'
    member_msg += ' Silakan submit ulang dengan bukti transfer yang valid.'

    email_member = (
        f'Yth. {saving.member.full_name},\n\n'
        f'Setoran simpanan Anda ({saving.saving_id}) tidak dapat diverifikasi.\n'
    )
    if reason:
        email_member += f'Alasan: {reason}\n'
    email_member += (
        '\nSilakan submit ulang dengan bukti transfer yang valid.\n\n'
        'Salam,\nTim SI-MAPAN'
    )

    _broadcast(
        member_user=saving.member.user,
        member_email=saving.member.user.email,
        notif_type='SAVING',
        member_title='Setoran Ditolak',
        member_message=member_msg,
        member_redirect_url='/savings',
        staff_title='', staff_message='', staff_redirect_url='',
        broadcast_to=None,
        email_subject_member='Setoran Anda Ditolak',
        email_body_member=email_member,
    )


# ═══════════════════════════════════════════════════════════════════════════
# LOANS
# ═══════════════════════════════════════════════════════════════════════════

def notify_loan_submitted(loan):
    """Member ajuin loan → member + manager dapet notif."""
    member_msg = (
        f'Pengajuan pinjaman Anda ({loan.loan_id}) telah dikirim '
        'dan menunggu review manajer.'
    )
    manager_msg = (
        f'Pengajuan pinjaman baru dari {loan.member.full_name} '
        f'({loan.loan_id}, Rp {loan.amount:,.0f}) menunggu review.'
    )

    email_member = (
        f'Yth. {loan.member.full_name},\n\n'
        f'Pengajuan pinjaman Anda ({loan.loan_id}) senilai Rp {loan.amount:,.0f} '
        f'dengan tenor {loan.tenor} bulan telah kami terima '
        'dan sedang dalam proses review oleh manajer.\n\n'
        'Anda akan menerima notifikasi setelah review selesai.\n\n'
        'Salam,\nTim SI-MAPAN'
    )
    email_manager = (
        f'Ada pengajuan pinjaman baru yang menunggu review:\n\n'
        f'Anggota   : {loan.member.full_name}\n'
        f'Loan ID   : {loan.loan_id}\n'
        f'Nominal   : Rp {loan.amount:,.0f}\n'
        f'Tenor     : {loan.tenor} bulan\n'
        f'Kategori  : {loan.get_category_display() if hasattr(loan, "get_category_display") else loan.category}\n\n'
        'Silakan login ke dashboard untuk memproses review.\n\n'
        'Salam,\nSistem SI-MAPAN'
    )

    _broadcast(
        member_user=loan.member.user,
        member_email=loan.member.user.email,
        notif_type='LOAN',
        member_title='Pengajuan Pinjaman Diterima',
        member_message=member_msg,
        member_redirect_url=f'/dashboard/member/loans/{loan.id}',
        staff_title='Pengajuan Pinjaman Baru',
        staff_message=manager_msg,
        staff_redirect_url='/dashboard/manager/loans/pending',
        broadcast_to='MANAGER',
        email_subject_member='Pengajuan Pinjaman Anda Telah Diterima',
        email_body_member=email_member,
        email_subject_staff='Pengajuan Pinjaman Menunggu Review',
        email_body_staff=email_manager,
    )


def notify_loan_approved(loan):
    """Manager approve loan → member + staff (utk disbursement) dapet notif."""
    member_msg = (
        f'Pengajuan pinjaman Anda ({loan.loan_id}) telah disetujui. '
        'Dana akan segera dicairkan ke rekening bank Anda.'
    )
    staff_msg = (
        f'Pinjaman {loan.loan_id} milik {loan.member.full_name} '
        f'telah disetujui dan menunggu pencairan dana.'
    )

    email_member = (
        f'Yth. {loan.member.full_name},\n\n'
        f'Pengajuan pinjaman Anda ({loan.loan_id}) senilai Rp {loan.amount:,.0f} '
        'telah DISETUJUI oleh manajer.\n\n'
        'Dana akan segera dicairkan ke rekening bank Anda oleh petugas kami. '
        'Anda akan menerima notifikasi setelah pencairan selesai.\n\n'
        'Salam,\nTim SI-MAPAN'
    )
    email_staff = (
        f'Pinjaman berikut telah disetujui dan menunggu pencairan:\n\n'
        f'Anggota : {loan.member.full_name}\n'
        f'Loan ID : {loan.loan_id}\n'
        f'Nominal : Rp {loan.amount:,.0f}\n'
        f'Tenor   : {loan.tenor} bulan\n\n'
        'Silakan login ke dashboard untuk memproses pencairan.\n\n'
        'Salam,\nSistem SI-MAPAN'
    )

    _broadcast(
        member_user=loan.member.user,
        member_email=loan.member.user.email,
        notif_type='LOAN',
        member_title='Pinjaman Disetujui',
        member_message=member_msg,
        member_redirect_url=f'/dashboard/member/loans/{loan.id}',
        staff_title='Pinjaman Menunggu Pencairan',
        staff_message=staff_msg,
        staff_redirect_url='/dashboard/staff/loans/approved',
        broadcast_to='STAFF',
        email_subject_member='Pinjaman Anda Telah Disetujui',
        email_body_member=email_member,
        email_subject_staff='Pinjaman Menunggu Pencairan',
        email_body_staff=email_staff,
    )


def notify_loan_rejected(loan, reason=''):
    """Manager reject loan → member dapet notif + email."""
    member_msg = f'Pengajuan pinjaman Anda ({loan.loan_id}) ditolak.'
    if reason:
        member_msg += f' Alasan: {reason}'

    email_member = (
        f'Yth. {loan.member.full_name},\n\n'
        f'Mohon maaf, pengajuan pinjaman Anda ({loan.loan_id}) '
        'tidak dapat disetujui.\n'
    )
    if reason:
        email_member += f'Alasan: {reason}\n'
    email_member += (
        '\nApabila ada pertanyaan, silakan hubungi petugas kami.\n\n'
        'Salam,\nTim SI-MAPAN'
    )

    _broadcast(
        member_user=loan.member.user,
        member_email=loan.member.user.email,
        notif_type='LOAN',
        member_title='Pinjaman Ditolak',
        member_message=member_msg,
        member_redirect_url=f'/dashboard/member/loans/{loan.id}',
        staff_title='', staff_message='', staff_redirect_url='',
        broadcast_to=None,
        email_subject_member='Pengajuan Pinjaman Anda Ditolak',
        email_body_member=email_member,
    )


def notify_loan_disbursed(loan):
    """Staff cairkan loan → member dapet notif + email."""
    member_msg = (
        f'Dana pinjaman ({loan.loan_id}) telah dicairkan. '
        'Silakan cek rekening bank Anda.'
    )
    email_member = (
        f'Yth. {loan.member.full_name},\n\n'
        f'Dana pinjaman Anda ({loan.loan_id}) senilai Rp {loan.amount:,.0f} '
        'telah dicairkan ke rekening bank Anda.\n\n'
        'Silakan cek saldo rekening Anda. Cicilan pertama akan jatuh tempo '
        'sesuai jadwal yang dapat dilihat di dashboard.\n\n'
        'Salam,\nTim SI-MAPAN'
    )

    _broadcast(
        member_user=loan.member.user,
        member_email=loan.member.user.email,
        notif_type='LOAN',
        member_title='Dana Pinjaman Dicairkan',
        member_message=member_msg,
        member_redirect_url=f'/dashboard/member/loans/{loan.id}',
        staff_title='', staff_message='', staff_redirect_url='',
        broadcast_to=None,
        email_subject_member='Dana Pinjaman Anda Telah Dicairkan',
        email_body_member=email_member,
    )


def notify_installment_submitted(installment):
    """Member submit pembayaran cicilan → member + staff dapet notif."""
    loan = installment.loan
    member_msg = (
        f'Laporan pembayaran cicilan ke-{installment.installment_number} '
        f'untuk pinjaman {loan.loan_id} telah dikirim '
        'dan menunggu verifikasi petugas.'
    )
    staff_msg = (
        f'Pembayaran cicilan dari {loan.member.full_name} '
        f'({loan.loan_id}, cicilan ke-{installment.installment_number}, '
        f'Rp {installment.amount:,.0f}) menunggu verifikasi.'
    )

    email_member = (
        f'Yth. {loan.member.full_name},\n\n'
        f'Laporan pembayaran cicilan ke-{installment.installment_number} '
        f'untuk pinjaman {loan.loan_id} senilai Rp {installment.amount:,.0f} '
        'telah kami terima dan sedang dalam proses verifikasi.\n\n'
        'Anda akan menerima notifikasi setelah verifikasi selesai.\n\n'
        'Salam,\nTim SI-MAPAN'
    )
    email_staff = (
        f'Ada pembayaran cicilan yang menunggu verifikasi:\n\n'
        f'Anggota         : {loan.member.full_name}\n'
        f'Loan ID         : {loan.loan_id}\n'
        f'Cicilan ke      : {installment.installment_number}\n'
        f'Nominal         : Rp {installment.amount:,.0f}\n'
        f'Metode          : {getattr(installment, "payment_method", "-")}\n\n'
        'Silakan login ke dashboard untuk memproses verifikasi.\n\n'
        'Salam,\nSistem SI-MAPAN'
    )

    _broadcast(
        member_user=loan.member.user,
        member_email=loan.member.user.email,
        notif_type='LOAN',
        member_title='Pembayaran Cicilan Dikirim',
        member_message=member_msg,
        member_redirect_url=f'/dashboard/member/loans/{loan.id}',
        staff_title='Pembayaran Cicilan Baru',
        staff_message=staff_msg,
        staff_redirect_url='/dashboard/staff/installments/pending',
        broadcast_to='STAFF',
        email_subject_member='Pembayaran Cicilan Anda Telah Dikirim',
        email_body_member=email_member,
        email_subject_staff='Pembayaran Cicilan Menunggu Verifikasi',
        email_body_staff=email_staff,
    )


def notify_installment_recorded(installment):
    """Staff verify pembayaran cicilan → member dapet notif + email."""
    loan = installment.loan
    member_msg = (
        f'Pembayaran cicilan ke-{installment.installment_number} '
        f'untuk pinjaman {loan.loan_id} telah berhasil diverifikasi.'
    )
    email_member = (
        f'Yth. {loan.member.full_name},\n\n'
        f'Pembayaran cicilan ke-{installment.installment_number} '
        f'untuk pinjaman {loan.loan_id} senilai Rp {installment.amount:,.0f} '
        'telah berhasil diverifikasi.\n\n'
        'Terima kasih atas pembayaran tepat waktu Anda.\n\n'
        'Salam,\nTim SI-MAPAN'
    )

    _broadcast(
        member_user=loan.member.user,
        member_email=loan.member.user.email,
        notif_type='LOAN',
        member_title='Pembayaran Cicilan Terverifikasi',
        member_message=member_msg,
        member_redirect_url=f'/dashboard/member/loans/{loan.id}',
        staff_title='', staff_message='', staff_redirect_url='',
        broadcast_to=None,
        email_subject_member='Pembayaran Cicilan Anda Terverifikasi',
        email_body_member=email_member,
    )


def notify_installment_rejected(installment, reason=''):
    """Staff reject pembayaran cicilan → member dapet notif + email."""
    loan = installment.loan
    member_msg = (
        f'Pembayaran cicilan ke-{installment.installment_number} '
        f'untuk pinjaman {loan.loan_id} ditolak.'
    )
    if reason:
        member_msg += f' Alasan: {reason}'
    member_msg += ' Silakan submit ulang dengan bukti transfer yang valid.'

    email_member = (
        f'Yth. {loan.member.full_name},\n\n'
        f'Pembayaran cicilan ke-{installment.installment_number} '
        f'untuk pinjaman {loan.loan_id} tidak dapat diverifikasi.\n'
    )
    if reason:
        email_member += f'Alasan: {reason}\n'
    email_member += (
        '\nSilakan submit ulang dengan bukti transfer yang valid.\n\n'
        'Salam,\nTim SI-MAPAN'
    )

    _broadcast(
        member_user=loan.member.user,
        member_email=loan.member.user.email,
        notif_type='LOAN',
        member_title='Pembayaran Cicilan Ditolak',
        member_message=member_msg,
        member_redirect_url=f'/dashboard/member/loans/{loan.id}',
        staff_title='', staff_message='', staff_redirect_url='',
        broadcast_to=None,
        email_subject_member='Pembayaran Cicilan Anda Ditolak',
        email_body_member=email_member,
    )


def notify_loan_lunas(loan):
    """Semua cicilan lunas → member dapet notif + email."""
    member_msg = (
        f'Selamat! Pinjaman Anda ({loan.loan_id}) telah lunas. '
        'Terima kasih telah memenuhi kewajiban pembayaran tepat waktu.'
    )
    email_member = (
        f'Yth. {loan.member.full_name},\n\n'
        f'Selamat! Pinjaman Anda ({loan.loan_id}) senilai Rp {loan.amount:,.0f} '
        'telah LUNAS.\n\n'
        'Terima kasih telah memenuhi seluruh kewajiban pembayaran.\n\n'
        'Salam,\nTim SI-MAPAN'
    )

    _broadcast(
        member_user=loan.member.user,
        member_email=loan.member.user.email,
        notif_type='LOAN',
        member_title='Pinjaman Lunas',
        member_message=member_msg,
        member_redirect_url=f'/dashboard/member/loans/{loan.id}',
        staff_title='', staff_message='', staff_redirect_url='',
        broadcast_to=None,
        email_subject_member='Pinjaman Anda Telah Lunas',
        email_body_member=email_member,
    )


def notify_loan_overdue(loan):
    """Loan jadi overdue → member + staff dapet notif."""
    member_msg = (
        f'Pinjaman Anda ({loan.loan_id}) telah melewati tanggal jatuh tempo. '
        'Mohon segera lakukan pembayaran untuk menghindari penalti tambahan.'
    )
    staff_msg = (
        f'Pinjaman {loan.loan_id} milik {loan.member.full_name} telah masuk status OVERDUE.'
    )

    email_member = (
        f'Yth. {loan.member.full_name},\n\n'
        f'Pinjaman Anda ({loan.loan_id}) telah melewati tanggal jatuh tempo '
        'pembayaran cicilan.\n\n'
        'Mohon segera lakukan pembayaran untuk menghindari penalti tambahan.\n\n'
        'Salam,\nTim SI-MAPAN'
    )
    email_staff = (
        f'Pinjaman berikut telah masuk status OVERDUE:\n\n'
        f'Anggota : {loan.member.full_name}\n'
        f'Loan ID : {loan.loan_id}\n'
        f'Nominal : Rp {loan.amount:,.0f}\n\n'
        'Mohon lakukan follow-up ke anggota terkait.\n\n'
        'Salam,\nSistem SI-MAPAN'
    )

    _broadcast(
        member_user=loan.member.user,
        member_email=loan.member.user.email,
        notif_type='LOAN',
        member_title='Pinjaman Anda Overdue',
        member_message=member_msg,
        member_redirect_url=f'/dashboard/member/loans/{loan.id}',
        staff_title='Pinjaman Overdue',
        staff_message=staff_msg,
        staff_redirect_url='/dashboard/staff/loans/overdue',
        broadcast_to='STAFF',
        email_subject_member='Pinjaman Anda Overdue',
        email_body_member=email_member,
        email_subject_staff='Pinjaman Masuk Status Overdue',
        email_body_staff=email_staff,
    )



# ═══════════════════════════════════════════════════════════════════════════
# RESIGNATION
# ═══════════════════════════════════════════════════════════════════════════

def notify_resignation_received(resignation):
    """Member ajuin pengunduran diri → member + manager dapet notif."""
    member_msg = (
        'Permintaan pengunduran diri Anda telah diterima '
        'dan menunggu persetujuan manajer.'
    )
    manager_msg = (
        f'Permintaan pengunduran diri dari {resignation.member.full_name} '
        'menunggu persetujuan.'
    )

    email_member = (
        f'Yth. {resignation.member.full_name},\n\n'
        'Permintaan pengunduran diri Anda telah kami terima '
        'dan sedang menunggu persetujuan manajer.\n\n'
        'Anda akan menerima notifikasi setelah keputusan selesai.\n\n'
        'Salam,\nTim SI-MAPAN'
    )
    email_manager = (
        f'Ada permintaan pengunduran diri yang menunggu persetujuan:\n\n'
        f'Anggota : {resignation.member.full_name}\n\n'
        'Silakan login ke dashboard untuk memprosesnya.\n\n'
        'Salam,\nSistem SI-MAPAN'
    )

    _broadcast(
        member_user=resignation.member.user,
        member_email=resignation.member.user.email,
        notif_type='RESIGNATION',
        member_title='Permintaan Pengunduran Diri Diterima',
        member_message=member_msg,
        member_redirect_url='/dashboard/member/resignation',
        staff_title='Permintaan Pengunduran Diri Baru',
        staff_message=manager_msg,
        staff_redirect_url='/dashboard/manager/resignations/pending',
        broadcast_to='MANAGER',
        email_subject_member='Permintaan Pengunduran Diri Anda Telah Diterima',
        email_body_member=email_member,
        email_subject_staff='Permintaan Pengunduran Diri Menunggu Persetujuan',
        email_body_staff=email_manager,
    )


def notify_resignation_approved(resignation):
    """Manager approve pengunduran diri → member dapet notif + email."""
    member_msg = (
        'Permintaan pengunduran diri Anda telah disetujui. '
        'Pengembalian simpanan akan segera diproses.'
    )
    email_member = (
        f'Yth. {resignation.member.full_name},\n\n'
        'Permintaan pengunduran diri Anda telah disetujui oleh manajer.\n'
        'Pengembalian saldo simpanan Anda akan segera diproses oleh petugas.\n\n'
        'Terima kasih atas partisipasi Anda di SI-MAPAN.\n\n'
        'Salam,\nTim SI-MAPAN'
    )

    _broadcast(
        member_user=resignation.member.user,
        member_email=resignation.member.user.email,
        notif_type='RESIGNATION',
        member_title='Pengunduran Diri Disetujui',
        member_message=member_msg,
        member_redirect_url='/dashboard/member',
        staff_title='', staff_message='', staff_redirect_url='',
        broadcast_to=None,
        email_subject_member='Pengunduran Diri Anda Telah Disetujui',
        email_body_member=email_member,
    )


def notify_resignation_rejected(resignation, reason=''):
    """Manager reject pengunduran diri → member dapet notif + email."""
    member_msg = 'Permintaan pengunduran diri Anda ditolak.'
    if reason:
        member_msg += f' Alasan: {reason}'

    email_member = (
        f'Yth. {resignation.member.full_name},\n\n'
        'Mohon maaf, permintaan pengunduran diri Anda tidak dapat disetujui.\n'
    )
    if reason:
        email_member += f'Alasan: {reason}\n'
    email_member += (
        '\nApabila ada pertanyaan, silakan hubungi petugas kami.\n\n'
        'Salam,\nTim SI-MAPAN'
    )

    _broadcast(
        member_user=resignation.member.user,
        member_email=resignation.member.user.email,
        notif_type='RESIGNATION',
        member_title='Pengunduran Diri Ditolak',
        member_message=member_msg,
        member_redirect_url='/dashboard/member',
        staff_title='', staff_message='', staff_redirect_url='',
        broadcast_to=None,
        email_subject_member='Permintaan Pengunduran Diri Anda Ditolak',
        email_body_member=email_member,
    )
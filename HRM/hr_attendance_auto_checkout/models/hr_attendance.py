# -*- coding: utf-8 -*-

from babel import messages
import logging
from datetime import datetime
import pytz

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Auto checkout time: 8:00 PM Asia/Dhaka
AUTO_CHECKOUT_HOUR = 20       # 8 PM
AUTO_CHECKOUT_MINUTE = 0
DHAKA_TZ = 'Asia/Dhaka'


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    is_auto_checkout = fields.Boolean(
        string='Auto Checkout',
        default=False,
        readonly=True,
        help='If checked, this checkout was done automatically by the system '
             'because the employee forgot to check out.',
    )

    # -------------------------------------------------------------------------
    # Cron Method
    # -------------------------------------------------------------------------

    def _cron_auto_checkout(self):
        """
        Scheduled action: runs daily at 8:00 PM (Asia/Dhaka).

        Finds all attendance records where:
          - check_out is missing (employee forgot to check out)
          - check_in date is today (Dhaka local date)

        Sets check_out to today 8:00 PM Dhaka time (stored as UTC in DB).
        Logs a note on each employee's chatter for traceability.
        """
        dhaka_tz   = pytz.timezone(DHAKA_TZ)
        now_dhaka  = datetime.now(dhaka_tz)
        today_dhaka = now_dhaka.date()

        _logger.info(
            'Auto-checkout cron started | Dhaka time: %s',
            now_dhaka.strftime('%Y-%m-%d %H:%M:%S %Z'),
        )

        # Build the 8:00 PM Dhaka datetime and convert to UTC (naive) for DB
        checkout_dhaka = dhaka_tz.localize(
            datetime(
                today_dhaka.year,
                today_dhaka.month,
                today_dhaka.day,
                AUTO_CHECKOUT_HOUR,
                AUTO_CHECKOUT_MINUTE,
                0,
            )
        )
        checkout_utc = checkout_dhaka.astimezone(pytz.utc).replace(tzinfo=None)

        # Today's boundaries in UTC — used to filter check_in records for today
        start_of_day_dhaka = dhaka_tz.localize(
            datetime(today_dhaka.year, today_dhaka.month, today_dhaka.day, 0, 0, 0)
        )
        end_of_day_dhaka = dhaka_tz.localize(
            datetime(today_dhaka.year, today_dhaka.month, today_dhaka.day, 23, 59, 59)
        )
        start_utc = start_of_day_dhaka.astimezone(pytz.utc).replace(tzinfo=None)
        end_utc   = end_of_day_dhaka.astimezone(pytz.utc).replace(tzinfo=None)

        # Find attendances: checked in today but NOT checked out
        missing_checkout = self.search([
            ('check_in', '>=', fields.Datetime.to_string(start_utc)),
            ('check_in', '<=', fields.Datetime.to_string(end_utc)),
            ('check_out', '=', False),
        ])

        if not missing_checkout:
            _logger.info('Auto-checkout cron: no missing checkouts found for today.')
            return

        _logger.info(
            'Auto-checkout cron: %d record(s) found without checkout.',
            len(missing_checkout),
        )

        for attendance in missing_checkout:
            employee = attendance.employee_id

            # Safety guard: do not override if check_in is AFTER 8 PM
            # (edge case: someone checks in exactly at/after 8 PM)
            if attendance.check_in >= checkout_utc:
                _logger.warning(
                    'Skipping employee %s — check_in (%s UTC) is at or after '
                    'auto-checkout time (%s UTC).',
                    employee.name,
                    attendance.check_in,
                    checkout_utc,
                )
                continue

            attendance.write({
                'check_out': checkout_utc,
                'is_auto_checkout': True,
            })

            partner = employee.user_id.partner_id if employee.user_id else None

            msg = (
                f'⚠️ Auto Checkout Applied.\n'
                f'System automatically set check-out to 8:00 PM '
                f'on {today_dhaka.strftime("%d %B %Y")}.'
            )

            attendance.message_post(
                body=msg,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
                partner_ids=[partner.id] if partner else [],
            )

            _logger.info(
                'Auto-checkout applied | Employee: %s | Check-in: %s UTC | '
                'Check-out set: %s UTC',
                employee.name,
                attendance.check_in,
                checkout_utc,
            )

        _logger.info('Auto-checkout cron finished successfully.')
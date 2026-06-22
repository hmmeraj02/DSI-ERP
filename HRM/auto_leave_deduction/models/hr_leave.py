# models/hr_leave.py
from odoo import fields, models, api
from datetime import date, timedelta
import logging

_logger = logging.getLogger(__name__)


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    auto_absent = fields.Boolean(
        string='Auto Generated (Absent)',
        default=False,
        readonly=True,
        help="True if leave generated for Absence",
    )

    # Auto-deduction flag
    # post_noon / early_checkout / 15min_late deduction
    is_auto_deduction = fields.Boolean(
        string='Auto Deduction Leave',
        default=False,
        readonly=True,
        help="True if leave generated for Attendance Violation",
    )

    is_manual_request = fields.Boolean(
        string='Manual Leave Request',
        default=False,
        readonly=True,
        help="True if leave was manually requested by the employee",
    )

    # ════════════════════════════════════════════════════════════════════════
    #  OVERRIDE: action_validate — dummy attendance create on leave approval
    # ════════════════════════════════════════════════════════════════════════

    def action_validate(self):
        res = super().action_validate()
        self._sync_leave_dummy_attendance()
        return res

    def action_validate1(self):
        res = super().action_validate1()
        # validate1 = first approval (2-step), dummy এখনই বানাই
        self._sync_leave_dummy_attendance()
        return res

    # ════════════════════════════════════════════════════════════════════════
    #  OVERRIDE: action_refuse / action_draft — dummy attendance delete
    # ════════════════════════════════════════════════════════════════════════

    def action_refuse(self):
        res = super().action_refuse()
        self._delete_leave_dummy_attendance()
        return res

    def action_draft(self):
        res = super().action_draft()
        self._delete_leave_dummy_attendance()
        return res

    # ════════════════════════════════════════════════════════════════════════
    #  HELPERS
    # ════════════════════════════════════════════════════════════════════════

    def _is_manual_leave(self):
        """
        True হলে এই leave টি manual — অর্থাৎ absent deduction বা
        attendance violation deduction নয়।
        এই ধরনের leave এর জন্যই dummy attendance বানাতে হবে।
        """
        self.ensure_one()
        return not self.auto_absent and not self.is_auto_deduction

    def _get_leave_date_range(self):
        """
        Leave এর request_date_from থেকে request_date_to পর্যন্ত
        সব date এর list return করে।
        """
        self.ensure_one()
        date_from = self.request_date_from
        date_to = self.request_date_to

        if not date_from or not date_to:
            return []

        dates = []
        current = date_from
        while current <= date_to:
            dates.append(current)
            current += timedelta(days=1)
        return dates

    def _sync_leave_dummy_attendance(self):
        """
        Validated manual leave গুলোর প্রতিটি date এর জন্য
        dummy attendance row (type='leave') create করো।
        Already existing হলে create_dummy_attendance() নিজেই skip করে।
        """
        HrAttendance = self.env['hr.attendance']

        for leave in self:
            if not leave._is_manual_leave():
                continue

            if leave.state not in ('validate', 'validate1'):
                continue

            employee = leave.employee_id
            if not employee:
                continue

            for check_date in leave._get_leave_date_range():
                try:
                    HrAttendance.create_dummy_attendance(
                        employee, check_date, 'leave'
                    )
                    _logger.info(
                        "Leave dummy attendance created: %s on %s",
                        employee.name, check_date,
                    )
                except Exception as e:
                    _logger.error(
                        "Failed to create leave dummy attendance for %s on %s: %s",
                        employee.name, check_date, str(e),
                    )

    def _delete_leave_dummy_attendance(self):
        """
        Leave refuse বা reset হলে সেই leave এর date range এর
        dummy attendance (auto_generated_type='leave') delete করো।
        তবে শুধু তখনই delete করবে যদি ওই date এ অন্য কোনো
        validated leave না থাকে।
        """
        HrAttendance = self.env['hr.attendance']

        for leave in self:
            if not leave._is_manual_leave():
                continue

            employee = leave.employee_id
            if not employee:
                continue

            for check_date in leave._get_leave_date_range():
                try:
                    # ── অন্য কোনো active leave আছে কিনা check করো ──────────
                    other_leave = self.env['hr.leave'].search([
                        ('id', '!=', leave.id),
                        ('employee_id', '=', employee.id),
                        ('request_date_from', '<=', check_date),
                        ('request_date_to', '>=', check_date),
                        ('state', 'in', ['validate', 'validate1']),
                        ('auto_absent', '=', False),
                        ('is_auto_deduction', '=', False),
                    ], limit=1)

                    if other_leave:
                        # অন্য leave আছে — dummy রেখে দাও
                        continue

                    # ── Dummy attendance খুঁজে delete করো ──────────────────
                    dummy = HrAttendance.search([
                        ('employee_id', '=', employee.id),
                        ('auto_generated', '=', True),
                        ('auto_generated_type', '=', 'leave'),
                        ('check_in', '>=', fields.Datetime.to_datetime(
                            f"{check_date} 00:00:00"
                        )),
                        ('check_in', '<=', fields.Datetime.to_datetime(
                            f"{check_date} 23:59:59"
                        )),
                    ])

                    if dummy:
                        dummy.with_context(skip_deduction=True).sudo().unlink()
                        _logger.info(
                            "Leave dummy attendance deleted: %s on %s",
                            employee.name, check_date,
                        )
                except Exception as e:
                    _logger.error(
                        "Failed to delete leave dummy attendance for %s on %s: %s",
                        employee.name, check_date, str(e),
                    )

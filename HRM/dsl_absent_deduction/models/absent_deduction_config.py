import logging
from datetime import date, datetime, time, timedelta

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class AbsentDeductionConfig(models.Model):
    _name = 'absent.deduction.config'
    _description = 'Absent Leave Deduction Configuration'
    _rec_name = 'company_id'

    # ── Basic Config ────────────────────────────────────────────────────────
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)
    time_off_type_id = fields.Many2one(
        'hr.leave.type',
        string='Time-Off Type for Deduction',
        required=True,
        help="If an employee is marked absent, which leave type will be deducted?",
    )
    auto_create_allocation = fields.Boolean(
        string='Auto-Create Allocation',
        default=False,
        help="Should it automatically create an allocation if the employee has no leave balance?",
    )

    # ── Scheduling ──────────────────────────────────────────────────────────
    check_previous_days = fields.Integer(
        string='Check Previous Day(s)',
        default=1,
        help="1 = Checks yesterday's attendance. Usually keep it as 1.",
    )

    # ── Info ────────────────────────────────────────────────────────────────
    last_run = fields.Datetime(string='Last Run', readonly=True)
    log_ids = fields.One2many('absent.deduction.log', 'config_id', string='Deduction Logs')
    log_count = fields.Integer(compute='_compute_log_count', string='Total Logs')

    _sql_constraints = [
        ('unique_company', 'unique(company_id)',
         'একটি company-র জন্য শুধুমাত্র একটি Absent Deduction Config থাকতে পারবে।'),
    ]

    @api.depends('log_ids')
    def _compute_log_count(self):
        for rec in self:
            rec.log_count = len(rec.log_ids)

    def action_view_logs(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Deduction Logs',
            'res_model': 'absent.deduction.log',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.id)],
            'context': {'default_config_id': self.id},
        }

    def action_run_now(self):
        """Manual trigger — form এর 'Run Now' বাটন থেকে"""
        self.run_absent_deduction()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Done'),
                'message': _('Absent deduction process completed. Check logs for details.'),
                'type': 'success',
                'sticky': False,
            },
        }

    # ════════════════════════════════════════════════════════════════════════
    #  MAIN ENTRY POINT
    # ════════════════════════════════════════════════════════════════════════

    @api.model
    def run_absent_deduction(self):
        configs = self.search([('active', '=', True)])
        for config in configs:
            config._process_absent_deduction()

    def _process_absent_deduction(self):
        self.ensure_one()

        check_date = fields.Date.today() - timedelta(days=self.check_previous_days)
        _logger.info(
            "DSL Absent Deduction: Running for company=%s, check_date=%s",
            self.company_id.name, check_date,
        )

        employees = self.env['hr.employee'].search([
            ('active', '=', True),
            ('company_id', '=', self.company_id.id),
        ])

        deducted = []
        skipped = []

        for employee in employees:
            reason = self._get_skip_reason(employee, check_date)
            if reason:
                skipped.append((employee, reason))
                _logger.debug("SKIP: %s on %s — %s", employee.name, check_date, reason)
            else:
                success = self._create_absent_leave(employee, check_date)
                if success:
                    deducted.append(employee)
                else:
                    skipped.append((employee, "Deduction failed — check logs/allocation"))

        self._write_log(check_date, deducted, skipped)
        self.last_run = fields.Datetime.now()

        _logger.info(
            "DSL Absent Deduction: Done — %d deducted, %d skipped",
            len(deducted), len(skipped),
        )

    # ════════════════════════════════════════════════════════════════════════
    #  SKIP CHECKS
    # ════════════════════════════════════════════════════════════════════════

    def _get_skip_reason(self, employee, check_date):
        work_schedule = employee.resource_calendar_id
        if not work_schedule:
            return "No work schedule assigned"

        if not self._is_working_day(employee, check_date):
            return f"Not a working day (weekday={check_date.weekday()})"

        holiday = self._get_public_holiday(check_date, work_schedule)
        if holiday:
            return f"Public Holiday: {holiday.name}"

        if check_date.weekday() == 5:
            if self._is_saturday_off_for_employee(employee, check_date):
                return f"Saturday Roster OFF — {employee.roster_set_name or ''}"

        existing_leave = self._get_existing_leave(employee, check_date)
        if existing_leave:
            return f"Existing leave: {existing_leave.holiday_status_id.name} [{existing_leave.state}]"

        # ✅ dummy attendance (auto_generated=True) কে real attendance হিসেবে count করব না
        if self._has_real_attendance(employee, check_date):
            return "Attendance recorded (late/early handled by other module)"

        if self._already_auto_absent(employee, check_date):
            return "Already auto-absent deducted for this date"

        return None

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _is_working_day(self, employee, check_date):
        work_schedule = employee.resource_calendar_id
        if not work_schedule:
            return False
        scheduled_weekdays = work_schedule.attendance_ids.mapped('dayofweek')
        check_weekday = str(check_date.weekday())
        return check_weekday in scheduled_weekdays

    def _get_public_holiday(self, check_date, work_schedule):
        dt_start = datetime.combine(check_date, time.min)
        dt_end = datetime.combine(check_date, time.max)

        return self.env['resource.calendar.leaves'].search([
            ('date_from', '<=', dt_end),
            ('date_to', '>=', dt_start),
            ('holiday_id', '=', False),
            '|',
            ('calendar_id', '=', work_schedule.id),
            ('calendar_id', '=', False),
        ], limit=1)

    def _is_saturday_off_for_employee(self, employee, check_date):
        try:
            if not employee.is_in_saturday_roster:
                return False
            status = employee.get_saturday_status(check_date)
            return status.get('is_off', False)
        except Exception as e:
            _logger.error(
                "Error in _is_saturday_off_for_employee for %s on %s: %s",
                employee.name, check_date, str(e),
            )
            return False

    def _get_existing_leave(self, employee, check_date):
        dt_start = datetime.combine(check_date, time.min)
        dt_end = datetime.combine(check_date, time.max)

        return self.env['hr.leave'].search([
            ('employee_id', '=', employee.id),
            ('date_from', '<=', dt_end),
            ('date_to', '>=', dt_start),
            ('state', 'in', ['draft', 'confirm', 'validate1', 'validate']),
        ], limit=1)

    def _has_attendance(self, employee, check_date):
        """Backward compat — kept for safety"""
        return self._has_real_attendance(employee, check_date)

    def _has_real_attendance(self, employee, check_date):
        """
        শুধু real attendance check করে।
        auto_generated=True dummy rows বাদ দেয়।
        """
        dt_start = datetime.combine(check_date, time.min)
        dt_end = datetime.combine(check_date, time.max)

        return bool(self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', dt_start),
            ('check_in', '<=', dt_end),
            ('auto_generated', '=', False),      # ✅ dummy বাদ
        ], limit=1))

    def _already_auto_absent(self, employee, check_date):
        return bool(self.env['absent.deduction.log'].search([
            ('employee_id', '=', employee.id),
            ('check_date', '=', check_date),
            ('status', '=', 'deducted'),
        ], limit=1))

    # ════════════════════════════════════════════════════════════════════════
    #  DEDUCTION
    # ════════════════════════════════════════════════════════════════════════

    def _create_absent_leave(self, employee, check_date):
        """
        Absent এর জন্য hr.leave তৈরি করে validate করো।
        Success হলে dummy attendance create করো।
        """
        self.ensure_one()

        leave_type = self._get_leave_type_for_employee(employee)
        if not leave_type:
            _logger.error(
                "No leave type configured for absent deduction. Employee: %s",
                employee.name,
            )
            return False

        work_schedule = employee.resource_calendar_id
        day_start_time, day_end_time = self._get_work_hours(work_schedule, check_date)

        dt_from = datetime.combine(check_date, day_start_time)
        dt_to = datetime.combine(check_date, day_end_time)

        if dt_to.date() != check_date:
            dt_to = datetime.combine(check_date, time(23, 59, 59))

        try:
            leave = self.env['hr.leave'].sudo().create({
                'employee_id': employee.id,
                'holiday_status_id': leave_type.id,
                'request_date_from': check_date,
                'request_date_to': check_date,
                'name': _('Auto Absent — %s') % check_date.strftime('%d/%m/%Y'),
                'auto_absent': True,
            })

            leave.sudo().action_validate()

            _logger.info(
                "Absent leave created & validated: %s on %s — leave_id=%s, type=%s",
                employee.name, check_date, leave.id, leave_type.name,
            )

            # ✅ NEW: Dummy attendance create for Status display
            self._create_absent_dummy_attendance(employee, check_date)

            return True

        except Exception as e:
            _logger.error(
                "Failed to create absent leave for %s on %s: %s",
                employee.name, check_date, str(e),
            )
            return False

    def _create_absent_dummy_attendance(self, employee, check_date):
        """
        Absent এর জন্য dummy attendance row তৈরি করো।
        hr.attendance.create_dummy_attendance() helper use করে।
        """
        try:
            self.env['hr.attendance'].create_dummy_attendance(
                employee, check_date, 'absent'
            )
        except Exception as e:
            _logger.error(
                "Failed to create dummy attendance for absent: %s on %s: %s",
                employee.name, check_date, str(e),
            )

    def _get_work_hours(self, work_schedule, check_date):
        if not work_schedule:
            return time(9, 0), time(18, 0)

        check_weekday = str(check_date.weekday())
        day_attendances = work_schedule.attendance_ids.filtered(
            lambda a: a.dayofweek == check_weekday
        )

        if day_attendances:
            hour_from = min(day_attendances.mapped('hour_from'))
            hour_to = max(day_attendances.mapped('hour_to'))

            def float_to_time(fh):
                if fh >= 24.0:
                    return time(23, 59, 59)
                h = int(fh)
                m = int(round((fh - h) * 60))
                if m == 60:
                    h += 1
                    m = 0
                if h >= 24:
                    return time(23, 59, 59)
                return time(h, m)

            return float_to_time(hour_from), float_to_time(hour_to)

        return time(9, 0), time(18, 0)

    def _get_leave_type_for_employee(self, employee):
        if (hasattr(employee, 'use_custom_deduction_leave_type')
                and employee.use_custom_deduction_leave_type
                and employee.custom_deduction_leave_type_id):
            return employee.custom_deduction_leave_type_id
        return self.time_off_type_id

    def _get_allocation(self, employee, leave_type):
        return self.env['hr.leave.allocation'].search([
            ('employee_id', '=', employee.id),
            ('holiday_status_id', '=', leave_type.id),
            ('state', '=', 'validate'),
        ], limit=1, order='id desc')

    def _create_allocation(self, employee, leave_type):
        try:
            allocation = self.env['hr.leave.allocation'].sudo().create({
                'name': _('%s - %s (Auto-created by Absent Deduction)') % (
                    leave_type.name, employee.name
                ),
                'holiday_status_id': leave_type.id,
                'employee_id': employee.id,
                'number_of_days': 30.0,
                'date_from': fields.Date.today(),
                'date_to': fields.Date.today().replace(
                    year=fields.Date.today().year + 1
                ),
            })
            try:
                allocation.action_validate()
            except Exception:
                allocation.sudo().write({'state': 'validate'})

            _logger.info(
                "Auto-created allocation for %s: 30 days of %s",
                employee.name, leave_type.name,
            )
            return allocation
        except Exception as e:
            _logger.error(
                "Failed to auto-create allocation for %s: %s",
                employee.name, str(e),
            )
            return False

    # ════════════════════════════════════════════════════════════════════════
    #  LOGGING
    # ════════════════════════════════════════════════════════════════════════

    def _write_log(self, check_date, deducted_employees, skipped_list):
        log_lines = []

        for emp in deducted_employees:
            log_lines.append({
                'config_id': self.id,
                'employee_id': emp.id,
                'check_date': check_date,
                'status': 'deducted',
                'reason': 'Absent — leave deducted',
            })

        for emp, reason in skipped_list:
            log_lines.append({
                'config_id': self.id,
                'employee_id': emp.id,
                'check_date': check_date,
                'status': 'skipped',
                'reason': reason,
            })

        if log_lines:
            self.env['absent.deduction.log'].create(log_lines)
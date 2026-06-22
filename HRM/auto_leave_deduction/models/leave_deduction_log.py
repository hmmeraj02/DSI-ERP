from odoo import models, fields, api
from odoo.exceptions import AccessError
import logging

_logger = logging.getLogger(__name__)


class LeaveDeductionLog(models.Model):
    _name = "leave.deduction.log"
    _description = "Leave Deduction Log"
    _order = "deduction_date desc, id desc"
    _rec_name = "employee_id"

    employee_id = fields.Many2one(
        "hr.employee", string="Employee", required=True, ondelete="cascade"
    )
    deduction_date = fields.Date(
        string="Deduction Date", required=True, default=fields.Date.today
    )
    deduction_type = fields.Selection(
        [
            ("15min_late", "3 Days 15-Min Late"),
            ("post_noon", "Post-Noon Arrival (After 12 PM)"),
            ("early_checkout", "Early Check-out"),
            ("absent", "Absent — Full Day"),
        ],
        string="Deduction Type",
        required=True,
    )
    attendance_ids = fields.Many2many("hr.attendance", string="Related Attendances")
    leave_allocation_id = fields.Many2one("hr.leave.allocation", string="Leave Allocation")
    leave_request_id = fields.Many2one(
        "hr.leave",
        string="Leave Request",
        readonly=True,
        help="The validated leave request created for this deduction",
    )
    days_deducted = fields.Float(
        string="Days Deducted",
        compute="_compute_days_deducted",
        store=True,
        readonly=True,
    )
    notes = fields.Text(string="Notes")
    company_id = fields.Many2one(
        "res.company", string="Company", related="employee_id.company_id", store=True
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("processed", "Processed"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
    )
    error_message = fields.Text(string="Error Message", readonly=True)

    @api.depends('deduction_type')
    def _compute_days_deducted(self):
        for log in self:
            if log.deduction_type in ('15min_late', 'absent'):
                log.days_deducted = 1.0
            else:
                log.days_deducted = 0.5

    def write(self, vals):
        for log in self:
            if 'state' in vals and vals.get('state') == 'draft' and log.state == 'failed':
                continue
            if log.state in ['processed', 'failed']:
                if set(vals.keys()) == {'state'} and vals.get('state') == 'cancelled':
                    continue
                raise AccessError(
                    f'Cannot modify {log.state} deduction logs. '
                    f'These records are read-only for audit purposes.'
                )
        return super().write(vals)

    def unlink(self):
        if any(log.state == 'processed' for log in self):
            raise AccessError(
                'Cannot delete processed deduction logs. '
                'These records must be kept for audit purposes. '
                'You can cancel them instead.'
            )
        if not self.env.context.get('force_delete'):
            raise AccessError(
                'Deduction logs cannot be deleted manually. '
                'They are automatically managed by the system.'
            )
        return super().unlink()

    def action_cancel(self):
        for log in self:
            if log.state == 'processed':
                if log.leave_request_id and log.leave_request_id.state == 'validate':
                    try:
                        log.leave_request_id.sudo().action_refuse()
                        _logger.info(
                            f'Cancelled leave request {log.leave_request_id.id} '
                            f'for {log.employee_id.name}'
                        )
                    except Exception as e:
                        _logger.error(f'Failed to cancel leave request: {str(e)}')
            log.write({'state': 'cancelled'})

    def action_process(self):
        for log in self:
            if log.state == "processed":
                continue

            try:
                leave_type = log.employee_id.get_deduction_leave_type()

                if not leave_type:
                    error_msg = "No leave type configured for deductions!"
                    log.write({"state": "failed", "error_message": error_msg})
                    _logger.error(f"{error_msg} Employee: {log.employee_id.name}")
                    continue

                allocation = self._get_allocation(log.employee_id, leave_type)

                if not allocation:
                    config = self.env["leave.deduction.config"].get_config(
                        log.employee_id.company_id.id
                    )
                    if config and config.auto_create_allocation:
                        allocation = self._create_allocation(
                            log.employee_id, leave_type, config
                        )
                    else:
                        error_msg = (
                            f"No validated allocation found for employee "
                            f"{log.employee_id.name} with leave type "
                            f'"{leave_type.name}". Please create an allocation first '
                            f"or enable auto-create in configuration."
                        )
                        log.write({"state": "failed", "error_message": error_msg})
                        _logger.error(error_msg)
                        continue

                if allocation.number_of_days < log.days_deducted:
                    _logger.warning(
                        f"Insufficient balance! {log.employee_id.name} has "
                        f"{allocation.number_of_days} days but deducting "
                        f"{log.days_deducted} days."
                    )

                leave_request = self._create_leave_request(
                    log.employee_id,
                    leave_type,
                    log.days_deducted,
                    log.deduction_date,
                    log.deduction_type,
                )

                log.write({
                    'leave_allocation_id': allocation.id,
                    'leave_request_id': leave_request.id,
                    'state': 'processed',
                    'error_message': False,
                })

                new_balance = allocation.number_of_days - log.days_deducted
                _logger.info(
                    f"Successfully deducted {log.days_deducted} days from "
                    f"{log.employee_id.name}. Leave type: {leave_type.name}, "
                    f"New balance: {new_balance}"
                )

            except Exception as e:
                error_msg = f"Error processing deduction: {str(e)}"
                log.write({"state": "failed", "error_message": error_msg})
                _logger.error(f"{error_msg} for employee {log.employee_id.name}")

    def _create_leave_request(self, employee, leave_type, days, date, deduction_type):
        """
        Create and validate a leave request for the deduction.
        Success হলে dummy attendance create করো — Status display এর জন্য।
        """
        Leave = self.env['hr.leave']

        leave_descriptions = {
            '15min_late': 'Auto-deduction: 3 Days 15-Min Late',
            'post_noon': 'Auto-deduction: Post-Noon Arrival',
            'early_checkout': 'Auto-deduction: Early Check-out',
        }

        name = leave_descriptions.get(deduction_type, 'Auto-deduction: Attendance Violation')
        is_half_day = (days == 0.5)

        leave_vals = {
            'name': name,
            'holiday_status_id': leave_type.id,
            'employee_id': employee.id,
            'request_date_from': date,
            'request_date_to': date,
            'is_auto_deduction': True,   # Status column এ Leave দেখাবে না
        }

        if is_half_day:
            leave_vals.update({
                'request_unit_half': True,
                'request_date_from_period': 'am',
            })
        else:
            leave_vals.update({'request_unit_half': False})

        leave = Leave.sudo().create(leave_vals)

        if is_half_day:
            leave.sudo().write({'number_of_days': 0.5})

        try:
            leave.action_approve()
            if leave.state != 'validate':
                leave.action_validate()
            _logger.info(
                f'Created and validated leave request {leave.id} for {employee.name}: '
                f'{leave.number_of_days} days of {leave_type.name}'
            )
        except Exception as e:
            _logger.error(f'Failed to validate leave request: {str(e)}')
            leave.sudo().write({'state': 'validate'})

        # NEW: Dummy attendance create — Leave status দেখানোর জন্য
        # এই deduction-এর জন্য related attendance date তে dummy row দরকার
        # (শুধু post_noon বা 15min_late নয় — leave create হলেই দরকার নেই)
        # এই dummy টা attendance-based deduction এর জন্য নয়,
        # তাই এখানে create করব না — attendance row already আছে।
        # Leave status হবে _compute_status() তে hr.leave check থেকে।

        return leave

    def _get_allocation(self, employee, leave_type):
        return self.env["hr.leave.allocation"].search([
            ("employee_id", "=", employee.id),
            ("holiday_status_id", "=", leave_type.id),
            ("state", "=", "validate"),
        ], limit=1, order="id desc")

    def _create_allocation(self, employee, leave_type, config):
        allocation = self.env["hr.leave.allocation"].sudo().create({
            "name": f"{leave_type.name} - {employee.name} (Auto-created)",
            "holiday_status_id": leave_type.id,
            "employee_id": employee.id,
            "number_of_days": config.initial_allocation_days,
            "date_from": fields.Date.today(),
            "date_to": fields.Date.today().replace(
                year=fields.Date.today().year + 1
            ),
        })
        try:
            allocation.action_validate()
            _logger.info(
                f"Auto-created allocation for {employee.name} "
                f"with {config.initial_allocation_days} days of {leave_type.name}"
            )
        except Exception as e:
            _logger.error(f"Failed to validate auto-created allocation: {str(e)}")
            allocation.sudo().write({"state": "validate"})

        return allocation

    def action_retry(self):
        failed_logs = self.filtered(lambda l: l.state == "failed")
        if failed_logs:
            failed_logs.write({"state": "draft", "error_message": False})
            failed_logs.action_process()
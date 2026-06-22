from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AttendanceSummaryWizard(models.TransientModel):
    _name = "attendance.summary.wizard"
    _description = "Attendance Summary Report Wizard"

    date_from = fields.Date(
        string="From Date",
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(
        string="To Date",
        required=True,
        default=fields.Date.today,
    )
    employee_ids = fields.Many2many(
        "hr.employee",
        string="Employees",
        help="Leave empty to include all employees.",
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        help="Filter by department (optional).",
    )

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rec in self:
            if rec.date_from > rec.date_to:
                raise ValidationError("'From Date' must be earlier than 'To Date'.")

    def action_print_report(self):
        self.ensure_one()
        data = {
            "date_from": str(self.date_from),
            "date_to": str(self.date_to),
            "employee_ids": self.employee_ids.ids,
            "department_id": self.department_id.id if self.department_id else False,
        }
        return self.env.ref(
            "auto_leave_deduction.action_attendance_summary_report"
        ).report_action(self, data=data)

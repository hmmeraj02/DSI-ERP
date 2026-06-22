from odoo import models, fields, api


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    late_check_in_count = fields.Integer(
        string="Late Check-in Count",
        default=0,
        help="Number of times employee was late (15+ minutes). Resets after deduction.",
    )
    last_late_reset_date = fields.Date(
        string="Last Late Count Reset Date",
        help="Date when late count was last reset after deduction",
    )
    deduction_log_ids = fields.One2many(
        "leave.deduction.log", "employee_id", string="Deduction Logs"
    )
    total_deductions = fields.Float(
        string="Total Deductions", compute="_compute_total_deductions", store=True
    )

    # Employee-specific override
    use_custom_deduction_leave_type = fields.Boolean(
        string="Use Custom Deduction Leave Type",
        default=False,
        help="Enable to override company default leave type for this employee",
    )

    custom_deduction_leave_type_id = fields.Many2one(
        "hr.leave.type",
        string="Custom Deduction Leave Type",
        help="Leave type to deduct from for this employee (overrides company setting)",
    )

    @api.depends("deduction_log_ids.days_deducted")
    def _compute_total_deductions(self):
        for employee in self:
            employee.total_deductions = sum(
                employee.deduction_log_ids.mapped("days_deducted")
            )

    def reset_late_count(self):
        """Reset late check-in count"""
        self.write(
            {"late_check_in_count": 0, "last_late_reset_date": fields.Date.today()}
        )

    def get_deduction_leave_type(self):
        """Get the leave type to use for deductions"""
        self.ensure_one()

        # Check if employee has custom override
        if self.use_custom_deduction_leave_type and self.custom_deduction_leave_type_id:
            return self.custom_deduction_leave_type_id

        # Otherwise use company configuration
        config = self.env["leave.deduction.config"].get_config(self.company_id.id)
        return config.leave_type_id

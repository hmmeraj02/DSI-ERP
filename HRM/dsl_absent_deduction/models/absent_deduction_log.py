from odoo import fields, models


class AbsentDeductionLog(models.Model):
    _name = 'absent.deduction.log'
    _description = 'Absent Deduction Log'
    _order = 'check_date desc, employee_id asc'

    config_id = fields.Many2one(
        'absent.deduction.config',
        string='Config',
        required=True,
        ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
    )
    check_date = fields.Date(
        string='Date Checked',
        required=True,
    )
    status = fields.Selection([
        ('deducted', 'Deducted'),
        ('skipped', 'Skipped'),
    ], string='Status', required=True)
    reason = fields.Char(string='Reason / Note')
    run_at = fields.Datetime(
        string='Processed At',
        default=fields.Datetime.now,
    )

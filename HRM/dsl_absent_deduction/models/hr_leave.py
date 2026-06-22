from odoo import fields, models


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    auto_absent = fields.Boolean(
        string='Auto Generated (Absent)',
        default=False,
        readonly=True,
        help="True হলে এই leave টি Absent Deduction system দ্বারা automatically তৈরি হয়েছে।",
    )

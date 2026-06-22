# -*- coding: utf-8 -*-
from odoo import models, api, fields

class DslStudyNotice(models.Model):
    _inherit = "dsl.study.notice"

    read_partner_ids = fields.Many2many('res.partner', 'notice_read_rel', 'notice_id', 'partner_id', string="Read By")

    def action_publish(self):
        # Call super to perform original publish logic (state change, message_post, etc.)
        res = super(DslStudyNotice, self).action_publish()
        
        for rec in self:
            # Send real-time notification to portal only if target includes portal
            if rec.target in ['all', 'portal']:
                self.env['bus.bus']._sendone(
                    'dsl_student_portal_notices',
                    'notice_published',
                    {
                        'id': rec.id,
                        'title': rec.name,
                        'from_date': rec.from_date,
                        'type': 'notice_published'
                    }
                )
        return res

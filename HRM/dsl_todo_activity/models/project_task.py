from odoo import api, fields, models
from datetime import date


class ProjectTask(models.Model):
    _inherit = 'project.task'

    schedule_date = fields.Datetime(string='Schedule Date')
    todo_activity_id = fields.Many2one('mail.activity', string='Todo Activity', ondelete='set null',)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.schedule_date:
                rec._create_or_update_todo_activity()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'schedule_date' in vals or 'user_ids' in vals:
            for rec in self:
                rec._create_or_update_todo_activity()
        return res

    def _create_or_update_todo_activity(self):
        self.ensure_one()
        schedule_date = self.schedule_date
        assigned_user = self.user_ids[0] if self.user_ids else self.env.user

        if self.todo_activity_id:
            try:
                self.todo_activity_id.write({
                    'date_deadline': schedule_date,
                    'summary': self.name or '',
                    'user_id': assigned_user.id,
                })
            except Exception:
                self.todo_activity_id = False
                self._create_or_update_todo_activity()
            return

        if not schedule_date or schedule_date.date() < date.today():
            return

        activity_type = self.env['mail.activity.type'].search(
            [('name', 'in', ['To-Do', 'Reminder', 'todo'])], limit=1
        )
        if not activity_type:
            activity_type = self.env['mail.activity.type'].search([], limit=1)

        if not activity_type:
            return

        model_id = self.env['ir.model']._get('project.task').id

        description = ''
        if hasattr(self, 'description') and self.description:
            description = self.description
        elif hasattr(self, 'x_description') and self.x_description:
            description = self.x_description

        mail_activity = self.env['mail.activity'].create({
            'activity_type_id': activity_type.id,
            'res_model_id': model_id,
            'res_id': self.id,
            'user_id': assigned_user.id,
            'date_deadline': schedule_date,
            'summary': self.name or '',
            'note': description,
        })

        if mail_activity:
            self.write({'todo_activity_id': mail_activity.id})
            self.message_post(
                body=f"Scheduled activity created for {schedule_date}: {self.name or ''}",
                message_type='notification',
            )
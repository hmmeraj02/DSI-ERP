from odoo import api, fields, models
from datetime import date


class ProjectTask(models.Model):
    _inherit = "project.task"

    # ── Contact type selector ──────────────────────────────────────────────
    contact_type = fields.Selection([
        ('student', 'Student'),
        ('agent', 'Agent'),
    ], string='Task For')

    task_student_ids = fields.Many2many(
        comodel_name='dsl.study.student',
        relation='project_task_dsl_task_student_rel',
        column1='task_id',
        column2='student_id',
        string='Students',
    )

    task_agent_ids = fields.Many2many(
        comodel_name='dsl.study.agent',
        relation='project_task_dsl_task_agent_rel',
        column1='task_id',
        column2='agent_id',
        string='Agents',
    )

    # ── Priority (Many2one → project.tags) ────────────────────────────────
    priority_id = fields.Many2one(
        comodel_name='project.tags',
        string='Priority',
        domain=[('name', 'in', ['High', 'Medium', 'Low'])],
    )

    # ── Deadline activity tracking ────────────────────────────────────────
    deadline_activity_id = fields.Many2one(
        comodel_name='mail.activity',
        string='Deadline Activity',
        ondelete='set null',
    )

    # ── ORM overrides ─────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        for task in tasks:
            if task.date_deadline:
                task._create_or_update_deadline_activity()
        return tasks

    def write(self, vals):
        res = super().write(vals)
        if 'date_deadline' in vals or 'user_ids' in vals:
            for task in self:
                task._create_or_update_deadline_activity()
        return res

    # ── Deadline activity helper ──────────────────────────────────────────
    def _create_or_update_deadline_activity(self):
        self.ensure_one()
        deadline = self.date_deadline
        assigned_user = self.user_ids[0] if self.user_ids else self.env.user

        if self.deadline_activity_id:
            try:
                self.deadline_activity_id.write({
                    'date_deadline': deadline,
                    'summary': self.name or '',
                    'user_id': assigned_user.id,
                })
            except Exception:
                self.deadline_activity_id = False
                self._create_or_update_deadline_activity()
            return

        if not deadline or deadline.date() < date.today():
            return

        activity_type = self.env['mail.activity.type'].search(
            [('name', 'in', ['To-Do', 'Reminder', 'todo'])], limit=1
        )
        if not activity_type:
            activity_type = self.env['mail.activity.type'].search([], limit=1)
        if not activity_type:
            return

        model_id = self.env['ir.model']._get('project.task').id
        mail_activity = self.env['mail.activity'].create({
            'activity_type_id': activity_type.id,
            'res_model_id': model_id,
            'res_id': self.id,
            'user_id': assigned_user.id,
            'date_deadline': deadline,
            'summary': self.name or '',
        })
        if mail_activity:
            self.write({'deadline_activity_id': mail_activity.id})
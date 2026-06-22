from odoo import api, fields, models

class TodoCalendarFilter(models.Model):
    _name = 'todo.calendar.filter'
    _description = 'Todo Calendar Filters'

    user_id = fields.Many2one('res.users', 'Me', required=True, default=lambda self: self.env.user, index=True, ondelete='cascade')
    user_ids = fields.Many2one('res.users', 'Assignee', required=True, index=True)
    active = fields.Boolean('Active', default=True)
    user_checked = fields.Boolean('Checked', default=True)

    _sql_constraints = [
        ('user_id_user_ids_unique', 'UNIQUE(user_id, user_ids)', 'A user cannot have the same assignee twice.')
    ]

    @api.model
    def unlink_from_user_ids(self, user_ids):
        return self.search([('user_ids', '=', user_ids)]).unlink()

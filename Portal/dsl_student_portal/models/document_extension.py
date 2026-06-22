# -*- coding: utf-8 -*-
from odoo import api, fields, models


class DslStudyStudentDocumentLineExtension(models.Model):
    """Extends the document line model with portal-specific fields"""
    _inherit = 'dsl.study.student.document.line'
    
    # Portal Enhancement Fields
    attachment_id = fields.Many2one('ir.attachment', string='Attachment', ondelete='cascade', 
                                   help='Uploaded document file')
    sponsor_name = fields.Char(related='sponsor_id.name', string='Sponsor Name', 
                              readonly=True, store=True)
    student_name = fields.Char(related='student_id.name', string='Student Name', 
                              readonly=True, store=True)
    has_attachment = fields.Boolean(string='Has Attachment', compute='_compute_has_attachment', 
                                   store=True)
    file_name = fields.Char(string='File Name', compute='_compute_file_info', store=True)
    file_size = fields.Integer(string='File Size', compute='_compute_file_info', store=True)
    is_overdue = fields.Boolean(string='Is Overdue', compute='_compute_is_overdue')

    @api.depends('attachment_id')
    def _compute_has_attachment(self):
        for record in self:
            record.has_attachment = bool(record.attachment_id)

    @api.depends('attachment_id')
    def _compute_file_info(self):
        for record in self:
            if record.attachment_id:
                record.file_name = record.attachment_id.name
                record.file_size = record.attachment_id.file_size
            else:
                record.file_name = False
                record.file_size = 0

    @api.depends('due_date', 'state')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.due_date and record.state in ['not_received', 'received']:
                record.is_overdue = record.due_date < today
            else:
                record.is_overdue = False

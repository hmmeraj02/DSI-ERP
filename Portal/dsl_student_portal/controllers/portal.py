# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal
import logging

_logger = logging.getLogger(__name__)

class DslStudentPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        return values

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        
        # Get current user's partner
        partner = request.env.user.partner_id
        
        # Logic to fetch notices available for the current user
        domain = [
            ('state', '=', 'publish'),
            ('active', '=', True),
            '|',
            ('target', '=', 'all'),
            '&',
            ('target', '=', 'portal'),
            '|',
            ('portal_ids', '=', False),
            ('portal_ids', 'in', request.env.user.id)
        ]
        
        _logger.info(f"DEBUG NOTICES - User ID: {request.env.user.id}, Partner ID: {partner.id}")
        _logger.info(f"DEBUG NOTICES - Domain: {domain}")
        
        # Count unread notices
        unread_notices_count = request.env['dsl.study.notice'].sudo().search_count(domain + [('read_partner_ids', 'not in', partner.id)])
         
        # Fetch top 5 recent notices
        recent_notices = request.env['dsl.study.notice'].sudo().search(domain, order='create_date desc', limit=5)
        _logger.info(f"DEBUG NOTICES - Found {len(recent_notices)} notices: {recent_notices.mapped('name')}")
        
        # Single student lookup for consistent filtering throughout
        student = request.env["dsl.study.student"].sudo().search([("partner_id", "=", partner.id)], limit=1)
        
        # Initialize empty recordsets
        overdue_documents = request.env["dsl.study.student.document.line"].sudo()
        due_soon_documents = request.env["dsl.study.student.document.line"].sudo()
        unpaid_invoices = request.env['account.move'].sudo()
        due_soon_invoices = request.env['account.move'].sudo()
        overdue_count = 0
        unpaid_invoice_count = 0

        # Initialize dates globally for the method
        from datetime import date, timedelta
        today = date.today()
        due_soon_threshold = today + timedelta(days=2)
        
        # Only fetch student-specific data if user is a student
        if student:
            # Get all documents for this specific student (own documents + sponsor documents)
            all_documents = student.document_line_ids | request.env["dsl.study.student.document.line"].sudo().search([("sponsor_id", "in", student.sponsor_ids.ids)])
            
            # Filter overdue documents
            overdue_documents = all_documents.filtered(lambda d: d.is_overdue)
            overdue_count = len(overdue_documents)
            
            # Filter due soon documents
            due_soon_documents = all_documents.filtered(
                lambda d: d.due_date and today <= d.due_date <= due_soon_threshold and d.state in ['not_received', 'received']
            )
            
            # Get invoices for this specific student's partner
            # Use student.partner_id to ensure we get the correct partner linked to the student
            invoice_partner_id = student.partner_id.id if student.partner_id else partner.id
            
            invoice_domain = [
                ('partner_id', '=', invoice_partner_id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('payment_state', 'in', ['not_paid', 'partial'])
            ]
            unpaid_invoices = request.env['account.move'].sudo().search(invoice_domain, order='invoice_date_due asc')
            unpaid_invoice_count = len(unpaid_invoices)
            
            # Filter due soon invoices
            due_soon_invoices = unpaid_invoices.filtered(
                lambda i: i.invoice_date_due and today <= i.invoice_date_due <= due_soon_threshold
            )
            
            _logger.info(f"User {partner.name} (Student {student.name}): {unpaid_invoice_count} invoices, {overdue_count} overdue docs")
        
        # Agent Logic
        agent = request.env['dsl.study.agent'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)
        if agent:
            # Get all students linked to this agent
            agent_students = request.env['dsl.study.student'].sudo().search([('agent_ids', 'in', agent.id)])
            
            # Aggregate documents for all students
            all_agent_docs = request.env["dsl.study.student.document.line"].sudo().search([
                ('student_id', 'in', agent_students.ids)
            ])
            
            # Filter overdue documents
            # Overdue: due_date < today AND state in ['not_received', 'received']
            overdue_agent_docs = all_agent_docs.filtered(lambda d: d.is_overdue)
            overdue_documents |= overdue_agent_docs
            overdue_count = len(overdue_documents)
            
            # Filter due soon documents
            due_soon_agent_docs = all_agent_docs.filtered(
                lambda d: d.due_date and today <= d.due_date <= due_soon_threshold and d.state in ['not_received', 'received']
            )
            due_soon_documents |= due_soon_agent_docs
            
            # Aggregate invoices for all students
            # We need invoices where the partner is one of the student's partners
            student_partners = agent_students.mapped('partner_id')
            if student_partners:
                agent_invoice_domain = [
                    ('partner_id', 'in', student_partners.ids),
                    ('move_type', '=', 'out_invoice'),
                    ('state', '=', 'posted'),
                    ('payment_state', 'in', ['not_paid', 'partial'])
                ]
                agent_unpaid_invoices = request.env['account.move'].sudo().search(agent_invoice_domain, order='invoice_date_due asc')
                unpaid_invoices |= agent_unpaid_invoices
                unpaid_invoice_count = len(unpaid_invoices)
                
                # Filter due soon invoices
                agent_due_soon_inv = agent_unpaid_invoices.filtered(
                    lambda i: i.invoice_date_due and today <= i.invoice_date_due <= due_soon_threshold
                )
                due_soon_invoices |= agent_due_soon_inv

            _logger.info(f"Agent {agent.name}: {len(agent_students)} students, {overdue_count} overdue docs (agg)")

        if not student and not agent:
            # For non-student users (agents, etc.), return empty recordsets
            _logger.info(f"User {partner.name} is not a student - no invoice/document notifications")
            from datetime import date
            today = date.today()

        # --- Sidebar status flags (students only) ---
        invoice_status = ''
        program_status = ''
        document_status = ''
        pending_programs_count = 0
        missing_docs_count = 0

        if student:
            # Invoice status
            invoice_status = 'danger' if unpaid_invoice_count > 0 else 'success'

            # Program status: red = any active program not yet at 'done' stage
            active_programs = student.program_ids.filtered(lambda p: p.active)
            pending_programs = active_programs.filtered(lambda p: p.stage_code != 'done')
            pending_programs_count = len(pending_programs)
            all_done = bool(active_programs) and pending_programs_count == 0
            program_status = 'success' if all_done else 'danger'

            # Document status: red = any required doc still 'not_received'
            all_docs = student.document_line_ids | request.env[
                "dsl.study.student.document.line"
            ].sudo().search([("sponsor_id", "in", student.sponsor_ids.ids)])
            missing_docs = all_docs.filtered(
                lambda d: d.priority == 'required' and d.state == 'not_received'
            )
            missing_docs_count = len(missing_docs)
            document_status = 'danger' if missing_docs_count > 0 else 'success'

        # --- Sidebar status flags (agents only) ---
        agent_invoice_status = ''
        agent_document_status = ''
        agent_missing_docs_count = 0

        if agent:
            # Agent invoice status: red = any unpaid invoices across all students
            agent_invoice_status = 'danger' if unpaid_invoice_count > 0 else 'success'

            # Agent document status: red = any required doc 'not_received' across all students
            agent_students_all = request.env['dsl.study.student'].sudo().search([('agent_ids', 'in', agent.id)])
            all_agent_docs_check = request.env["dsl.study.student.document.line"].sudo().search([
                ('student_id', 'in', agent_students_all.ids)
            ])
            agent_missing_docs = all_agent_docs_check.filtered(
                lambda d: d.priority == 'required' and d.state == 'not_received'
            )
            agent_missing_docs_count = len(agent_missing_docs)
            agent_document_status = 'danger' if agent_missing_docs_count > 0 else 'success'

        values.update({
            'recent_notices': recent_notices,
            'unread_notices_count': unread_notices_count,
            'overdue_count': overdue_count,
            'overdue_documents': overdue_documents,
            'unpaid_invoice_count': unpaid_invoice_count,
            'unpaid_invoices': unpaid_invoices,
            'due_soon_invoices': due_soon_invoices,
            'due_soon_documents': due_soon_documents,
            'today': today,
            'date': date,
            'invoice_status': invoice_status,
            'program_status': program_status,
            'document_status': document_status,
            'pending_programs_count': pending_programs_count,
            'missing_docs_count': missing_docs_count,
            'agent_invoice_status': agent_invoice_status,
            'agent_document_status': agent_document_status,
            'agent_missing_docs_count': agent_missing_docs_count,
        })
        return values

    @http.route(['/my/notification/read/<int:notice_id>'], type='http', auth="user", website=True)
    def portal_mark_notice_read(self, notice_id, **kw):
        notice = request.env['dsl.study.notice'].sudo().browse(notice_id)
        if notice.exists():
            notice.write({'read_partner_ids': [(4, request.env.user.partner_id.id)]})
        
        return request.redirect(f'/my/notifications?id={notice_id}')

    @http.route(['/my/notification/mark_all_read'], type='http', auth="user", website=True)
    def portal_mark_all_read(self, **kw):
        partner = request.env.user.partner_id
        
        # Re-construct domain to match specific unread notices
        domain = [
            ('state', '=', 'publish'),
            ('active', '=', True),
            '|',
            ('target', '=', 'all'),
            '&',
            ('target', '=', 'portal'),
            '|',
            ('portal_ids', '=', False),
            ('portal_ids', 'in', request.env.user.id),
        ]
        
        # Fetch all candidate notices first
        all_candidate_notices = request.env['dsl.study.notice'].sudo().search(domain)
        
        # Filter in python to ensure we only get ones strictly not read by this partner
        unread_notices = all_candidate_notices.filtered(lambda n: partner.id not in n.read_partner_ids.ids)
        
        if unread_notices:
            unread_notices.write({'read_partner_ids': [(4, partner.id)]})
        
        return request.redirect(request.httprequest.referrer or '/my/home')
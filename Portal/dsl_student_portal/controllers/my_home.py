# -*- coding: utf-8 -*-
from odoo import http
from markupsafe import Markup
from odoo.http import request
from odoo.exceptions import UserError
from .portal import DslStudentPortal
import logging
import base64

_logger = logging.getLogger(__name__)


class DslStudyPortalController(DslStudentPortal):

    def _get_student(self):
        partner = request.env.user.partner_id

        student = (
            request.env["dsl.study.student"]
            .sudo()
            .search([("partner_id", "=", partner.id)], limit=1)
        )
        _logger.info(
            f"Retrieved student for partner {partner.id}: {student.id if student else 'None'}"
        )
        return student

    def _get_agent(self):
        partner = request.env.user.partner_id
        return (
            request.env["dsl.study.agent"]
            .sudo()
            .search([("partner_id", "=", partner.id)], limit=1)
        )
    
    def _get_program_score(self, p):
        """Return a numeric score for a program line based on stage + sub-state.
        Higher score = more advanced progress. Used to pick the best program."""
        base = (
            100 if (p.stage_code == 'visa_processing' and p.visa_state in ['approve', 'reject']) else
            100 if p.stage_code == 'done' else
            80  if (p.stage_code == 'visa_processing' and p.visa_state == 'apply') else
            70  if (p.stage_code == 'final_offer' and p.final_offer_state == 'received') else
            65  if p.stage_code == 'visa_documentation' else
            60  if p.stage_code in ['final_offer', 'tuition_fee', 'gs_state', 'sponsor_document'] else
            50  if p.stage_code == 'offer_letter' else
            30  if (p.stage_code == 'applied' and p.apply_state == 'submit') else
            20  if p.stage_code in ['applied', 'confirmed'] else
            0
        )
        sub = (
            90 if p.stage_code == 'gs_state' and p.gs_state == 'approve' else
            80 if p.stage_code == 'gs_state' and p.gs_state == 'revised' else
            70 if p.stage_code == 'gs_state' and p.gs_state == 'in_progress' else
            60 if p.stage_code == 'gs_state' and p.gs_state == 'submit' else
            90 if p.stage_code == 'offer_letter' and p.offer_letter_state == 'accepted' else
            70 if p.stage_code == 'offer_letter' and p.offer_letter_state == 'issued' else
            90 if p.stage_code == 'tuition_fee' and p.tuition_fee_state == 'paid' else
            50 if p.stage_code == 'tuition_fee' and p.tuition_fee_state == 'unpaid' else
            90 if p.stage_code == 'applied' and p.apply_state == 'submit' else
            50 if p.stage_code == 'applied' and p.apply_state == 'in_progress' else
            0
        )
        return base * 100 + sub

    def _get_sidebar_status_flags(self, student):
        """
        Returns a dict with status flags for the sidebar menu items:
          - invoice_status: 'danger' if unpaid invoices exist, else 'success'
          - program_status: 'danger' if no programs exist, else 'success'
          - document_status: 'danger' if any required docs are not_received, else 'success'
        """
        # --- Invoices ---
        unpaid_invoices = request.env['account.move'].sudo().search([
            ('partner_id', '=', student.partner_id.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'not in', ['paid', 'in_payment']),
        ])
        invoice_status = 'danger' if unpaid_invoices else 'success'
 
        # --- Programs ---
        # Red = any active program has NOT reached 'done' stage yet
        # Green = all active programs are at 'done' stage
        active_programs = student.program_ids.filtered(lambda p: p.active)
        all_done = bool(active_programs) and all(p.stage_code == 'done' for p in active_programs)
        program_status = 'success' if all_done else 'danger'
 
        # --- Documents ---
        all_documents = student.document_line_ids | request.env[
            "dsl.study.student.document.line"
        ].sudo().search([("sponsor_id", "in", student.sponsor_ids.ids)])
 
        has_missing_required_docs = any(
            d.priority == 'required' and d.state == 'not_received'
            for d in all_documents
        )
        document_status = 'danger' if has_missing_required_docs else 'success'
 
        return {
            'invoice_status': invoice_status,
            'program_status': program_status,
            'document_status': document_status,
        }

    @http.route(['/my', '/my/home'], type='http', auth='user', website=True)
    def home(self, **kw):
        _logger.info("=" * 80)
        _logger.info("CUSTOM HOME METHOD CALLED - DslStudyPortalController.home()")
        _logger.info("=" * 80)
        partner = request.env.user.partner_id
        identity_type = partner.identity_type
        _logger.info(f"Partner: {partner.name}, Identity Type: {identity_type}")

        if identity_type == "student":
            student = self._get_student()
            if not student:
                return request.render(
                    "dsl_student_portal.student_not_found",
                    {"partner": partner},
                )
            
            # Get standard portal values (including notifications)
            values = self._prepare_portal_layout_values()
            
            recent_programs = student.program_ids.sorted(key=lambda r: r.create_date, reverse=True)

            # Best program by progress score
            _sorted_progs = sorted(recent_programs, key=lambda p: self._get_program_score(p), reverse=True)
            best_program = _sorted_progs[0] if _sorted_progs else False

            # Dashboard specific notices (limited to 3)
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
            notices = request.env['dsl.study.notice'].sudo().search(domain, order='create_date desc', limit=3)
            
            # Get overdue documents
            all_documents = student.document_line_ids | request.env["dsl.study.student.document.line"].sudo().search([("sponsor_id", "in", student.sponsor_ids.ids)])
            overdue_documents = all_documents.filtered(lambda d: d.is_overdue)

            # Dashboard summary card counts (new 6-card layout)
            missing_docs = all_documents.filtered(lambda d: d.priority == 'required' and d.state == 'not_received')
            applied_programs = student.program_ids.filtered(lambda p: p.stage_code == 'applied')
            offer_programs = student.program_ids.filtered(lambda p: p.stage_code == 'final_offer' and p.final_offer_state == 'received')
            visa_applied_programs = student.program_ids.filtered(lambda p: p.stage_code == 'visa_processing' and p.visa_state == 'apply')
            visa_outcome_programs = student.program_ids.filtered(lambda p: p.stage_code == 'visa_processing' and p.visa_state in ['approve', 'reject'])

            values.update({
                "student": student,
                "recent_programs": recent_programs,
                "best_program": best_program,
                "notices": notices,
                "overdue_documents": overdue_documents,
                "priority_programs": student.program_ids.filtered(lambda p: p.priority == 1),
                "page_name": "dashboard",
                # New summary card counts
                "missing_docs_count": len(missing_docs),
                "applied_programs_count": len(applied_programs),
                "offer_programs_count": len(offer_programs),
                "visa_applied_count": len(visa_applied_programs),
                "visa_outcome_count": len(visa_outcome_programs),
            })

            return request.render(
                "dsl_student_portal.student_dashboard",
                values,
            )

        elif identity_type == "agent":
            agent = self._get_agent()
            if not agent:
                return request.redirect("/my/home?error=Agent record not found")

            # All students under this agent (for stats cards — always unfiltered)
            agent_students = request.env['dsl.study.student'].sudo().search(
                [('agent_ids', 'in', agent.id), ('active', 'in', [True, False])]
            )

            # Build best-program map for each student
            student_best_program = {}
            for s in agent_students:
                active_progs = s.program_ids.filtered(lambda p: p.active)
                if active_progs:
                    student_best_program[s.id] = sorted(active_progs, key=lambda p: self._get_program_score(p), reverse=True)[0]
                else:
                    student_best_program[s.id] = False

            # --- Country filter for My Students table ---
            # Collect unique dsl.study.country from all active programs across agent's students
            all_agent_programs = request.env['dsl.study.student.program.line'].sudo().search(
                [('student_id', 'in', agent_students.ids)]
            )
            seen_country_ids = set()
            student_countries = []
            for prog in all_agent_programs:
                if prog.country_id and prog.country_id.id not in seen_country_ids:
                    seen_country_ids.add(prog.country_id.id)
                    student_countries.append(prog.country_id)
            student_countries.sort(key=lambda c: c.name)

            # Apply filter — My Students table only; stats cards stay unfiltered
            active_country_filter = kw.get('country', '').strip()
            if active_country_filter:
                try:
                    cid = int(active_country_filter)
                    filtered_students = agent_students.filtered(
                        lambda s: any(p.country_id.id == cid for p in s.program_ids)
                    )
                except (ValueError, TypeError):
                    filtered_students = agent_students
            else:
                filtered_students = agent_students

            values = self._prepare_portal_layout_values()
            values.update({
                "agent": agent,
                "student_best_program": student_best_program,
                "student_countries": student_countries,
                "active_country_filter": active_country_filter,
                "filtered_students": filtered_students,
                "page_name": "dashboard",
            })
            return request.render(
                "dsl_student_portal.agent_dashboard",
                values,
            )

        else:
            return request.render(
                "dsl_student_portal.default_portal_home",
                {"page_name": "home"},
            )

    @http.route(['/my/programs/active'], type='http', auth='user', website=True)
    def student_active_programs(self, **kw):
        student = self._get_student()
        if not student:
            return request.redirect('/my/home')

        values = self._prepare_portal_layout_values()
        sidebar_flags = self._get_sidebar_status_flags(student)

        active_programs = student.program_ids.filtered(
            lambda p: p.stage_code not in ['cancelled', 'done']
        ).sorted(key=lambda r: r.create_date, reverse=True)

        values.update({
            'student': student,
            'programs': active_programs,
            'page_name': 'programs',
            'page_title': 'Active Programs',
            **sidebar_flags,
        })
        return request.render('dsl_student_portal.student_program_list', values)

    @http.route(['/my/programs/completed'], type='http', auth='user', website=True)
    def student_completed_programs(self, **kw):
        student = self._get_student()
        if not student:
            return request.redirect('/my/home')

        values = self._prepare_portal_layout_values()
        sidebar_flags = self._get_sidebar_status_flags(student)

        completed_programs = student.program_ids.filtered(
            lambda p: p.stage_code == 'done'
        ).sorted(key=lambda r: r.create_date, reverse=True)

        values.update({
            'student': student,
            'programs': completed_programs,
            'page_name': 'programs',
            'page_title': 'Completed Programs',
            **sidebar_flags,
        })
        return request.render('dsl_student_portal.student_program_list', values)

    @http.route(['/my/language-tests'], type='http', auth='user', website=True)
    def student_language_tests(self, **kw):
        student = self._get_student()
        if not student:
            return request.redirect('/my/home')

        values = self._prepare_portal_layout_values()
        sidebar_flags = self._get_sidebar_status_flags(student)

        language_tests = student.language_test_line_ids.sorted(
            key=lambda r: r.id, reverse=True
        )

        values.update({
            'student': student,
            'language_tests': language_tests,
            'page_name': 'language_tests',
            **sidebar_flags,
        })
        return request.render('dsl_student_portal.student_language_tests', values)

    @http.route(['/my/programs/priority'], type='http', auth='user', website=True)
    def student_priority_programs(self, **kw):
        student = self._get_student()
        if not student:
            return request.redirect('/my/home')

        values = self._prepare_portal_layout_values()
        sidebar_flags = self._get_sidebar_status_flags(student)

        priority_programs = student.program_ids.filtered(
            lambda p: p.priority == 1
        ).sorted(key=lambda r: r.create_date, reverse=True)

        values.update({
            'student': student,
            'programs': priority_programs,
            'page_name': 'programs',
            'page_title': '1st Priority Programs',
            **sidebar_flags,
        })
        return request.render('dsl_student_portal.student_program_list', values)

    @http.route(["/my/profile"], type="http", auth="user", website=True)
    def portal_profile(self, **kw):
        partner = request.env.user.partner_id
        identity_type = partner.identity_type
        success_msg = kw.get("success", "")
        error_msg = kw.get("error", "")

        if identity_type == "student":
            student = self._get_student()
            if not student:
                return request.redirect("/my/home?error=Student record not found")

            # Get standard portal layout values including notifications
            values = self._prepare_portal_layout_values()
            
            recent_programs = student.program_ids.sorted(key=lambda r: r.create_date, reverse=True)

            # Profile specific notices (limited to 3)
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
            notices = request.env['dsl.study.notice'].sudo().search(domain, order='create_date desc', limit=3)

            countries = request.env["res.country"].sudo().search([])

            states = request.env["res.country.state"].sudo().search([])
            relationships = request.env["dsl.study.relationship"].sudo().search([])
            professions = request.env["dsl.study.profession"].sudo().search([])

            institutes = request.env["dsl.study.country.institute"].sudo().search([('institute_type', '=', 'local')])
            programs = request.env["dsl.study.country.institute.program"].sudo().search([])

            # Check which officers are currently on leave
            from datetime import date as _date
            today = _date.today()
            on_leave_ids = set()
            all_officers = student.admission_officer_ids | student.document_officer_ids
            for officer in all_officers:
                leave = request.env['hr.leave'].sudo().search([
                    ('employee_id.user_id', '=', officer.id),
                    ('state', 'in', ['confirm', 'validate1', 'validate']),
                    ('date_from', '<=', today),
                    ('date_to', '>=', today),
                ], limit=1)
                if leave:
                    on_leave_ids.add(officer.id)

            values.update({
                "student": student,
                "countries": countries,
                "states": states,
                "relationships": relationships,
                "professions": professions,
                "recent_programs": recent_programs,
                "notices": notices,
                "page_name": "profile",
                "success": success_msg,
                "error": error_msg,
                "institutes": institutes,
                "programs": programs,
                "on_leave_ids": on_leave_ids,
            })

            return request.render(
                "dsl_student_portal.student_profile",
                values,
            )


        elif identity_type == "agent":
            agent = self._get_agent()
            if not agent:
                return request.redirect("/my/home?error=Agent record not found")

            countries = request.env["res.country"].sudo().search([])
            states = request.env["res.country.state"].sudo().search([])
            study_countries = request.env["dsl.study.country"].sudo().search([])

            values = self._prepare_portal_layout_values()
            values.update({
                "agent": agent,
                "countries": countries,
                "states": states,
                "study_countries": study_countries,
                "page_name": "profile",
                "success": success_msg,
                "error": error_msg,
            })
            return request.render(
                "dsl_student_portal.agent_profile",
                values,
            )
        
        else:
            _logger.warning(f"Access denied to /my/profile: Unknown identity type '{identity_type}' for partner {partner.name} (ID: {partner.id})")
            return request.redirect("/my/home?error=Access Denied: You do not have a valid Student or Agent profile.")

    @http.route(
        ["/my/profile/update"],
        type="http",
        auth="user",
        website=True,
        csrf=True,
        methods=["POST"],
    )
    def portal_profile_update(self, **post):
        partner = request.env.user.partner_id
        identity_type = partner.identity_type
        try:
            if identity_type == "student":
                student = self._get_student()
                if not student:
                    return request.redirect(
                        "/my/profile?error=Student record not found"
                    )

                update_vals = {
                    "first_name": post.get("first_name"),
                    "middle_name": post.get("middle_name", ""),
                    "last_name": post.get("last_name"),
                    "email": post.get("email"),
                    "mobile": post.get("mobile"),
                    "phone": post.get("phone", ""),
                    "date_of_birth": post.get("date_of_birth") or False,
                    "gender": post.get("gender") or False,
                    "blood_group": post.get("blood_group") or False,
                    "passport_number": post.get("passport_number", ""),
                    "passport_expire_date": post.get("passport_expire_date") or False,
                    "current_profession": post.get("current_profession") or False,
                    "current_institution": post.get("current_institution", ""),
                    "street": post.get("street", ""),
                    "street2": post.get("street2", ""),
                    "city": post.get("city", ""),
                    "zip": post.get("zip", ""),
                    "social_media_link": post.get("social_media_link", ""),
                    # "fax": post.get("fax", ""),
                }

                if post.get("nationality"):
                    update_vals["nationality"] = int(post.get("nationality"))
                if post.get("state_id"):
                    update_vals["state_id"] = int(post.get("state_id"))
                if post.get("country_id"):
                    update_vals["country_id"] = int(post.get("country_id"))
                if post.get("residence_country_id"):
                    update_vals["residence_country_id"] = int(
                        post.get("residence_country_id")
                    )

                student.sudo().write(update_vals)
                _logger.info(f"Student profile updated: {student.name}")
                return request.redirect(
                    "/my/profile?success=Profile updated successfully"
                )

            elif identity_type == "agent":
                agent = self._get_agent()
                if not agent:
                    return request.redirect("/my/profile?error=Agent record not found")

                update_vals = {
                    "first_name": post.get("first_name"),
                    "middle_name": post.get("middle_name", ""),
                    "last_name": post.get("last_name"),
                    "email": post.get("email"),
                    "mobile": post.get("mobile"),
                    "phone": post.get("phone", ""),
                    "gender": post.get("gender") or False,
                    "blood_group": post.get("blood_group") or False,
                    "passport_no": post.get("passport_no", ""),
                    "nid_no": post.get("nid_no", ""),
                    "designation": post.get("designation", ""),
                    "website": post.get("website", ""),
                    "street": post.get("street", ""),
                    "street2": post.get("street2", ""),
                    "city": post.get("city", ""),
                    "zip": post.get("zip", ""),
                    "fax": post.get("fax", ""),
                    "facebook": post.get("facebook", ""),
                    "instagram": post.get("instagram", ""),
                    "linkedin": post.get("linkedin", ""),
                    "twitter": post.get("twitter", ""),
                    "skype_id": post.get("skype_id", ""),
                    "whatsapp_id": post.get("whatsapp_id", ""),
                }

                if post.get("nationality"):
                    update_vals["nationality"] = int(post.get("nationality"))
                if post.get("state_id"):
                    update_vals["state_id"] = int(post.get("state_id"))
                if post.get("country_id"):
                    update_vals["country_id"] = int(post.get("country_id"))
                if post.get("from_country_id"):
                    update_vals["from_country_id"] = int(post.get("from_country_id"))

                agent.sudo().write(update_vals)
                _logger.info(f"Agent profile updated: {agent.name}")
                return request.redirect(
                    "/my/profile?success=Profile updated successfully"
                )

        except Exception as e:
            _logger.error(f"Error updating profile: {str(e)}")
            return request.redirect(f"/my/profile?error={str(e)}")

    @http.route(["/my/programs"], type="http", auth="user", website=True)
    def student_programs(self, **kw):
        student = self._get_student()
        if not student:
            return request.redirect("/my/home?error=Student record not found")

        values = self._prepare_portal_layout_values()
        all_programs = student.program_ids.sorted(key=lambda p: p.id, reverse=True)

        filter_type = kw.get('filter', None)
        filter_titles = {
            'applied':        'Applied Programs',
            'offer_received': 'Offer Received Programs',
            'visa_applied':   'Visa Applied Programs',
            'visa_outcome':   'Visa Outcome Programs',
        }
        filter_fns = {
            'applied':        lambda p: p.stage_code == 'applied',
            'offer_received': lambda p: p.stage_code == 'final_offer' and p.final_offer_state == 'received',
            'visa_applied':   lambda p: p.stage_code == 'visa_processing' and p.visa_state == 'apply',
            'visa_outcome':   lambda p: p.stage_code == 'visa_processing' and p.visa_state in ['approve', 'reject'],
        }

        if filter_type in filter_fns:
            programs = all_programs.filtered(filter_fns[filter_type])
            page_title = filter_titles[filter_type]
        else:
            programs = all_programs
            page_title = 'All Programs'

        response_options = request.env["dsl.study.program.response.option"].sudo().search(
            [("active", "=", True)], order="sequence, id"
        )
        values.update({
            "student": student,
            "programs": programs,
            "response_options": response_options,
            "page_name": "programs",
            "page_title": page_title,
            "active_filter": filter_type,
        })
        return request.render("dsl_student_portal.student_programs", values)


    @http.route(
        ["/my/program/respond"],
        type="http",
        auth="user",
        website=True,
        csrf=True,
        methods=["POST"],
    )
    def portal_program_respond(self, **post):
        """
        Handle student response for a program from the portal.
        - option_id: ID of the chosen dsl.study.program.response.option
        - comment:   Student's comment/reason text
        Saves student_portal_status (only for yes/no type options) and
        posts a chatter message for all types.
        """
        student = self._get_student()
        if not student:
            return request.redirect("/my/programs?error=Student record not found")

        try:
            from datetime import date as _date

            program_id = int(post.get("program_id", 0))
            option_id  = int(post.get("option_id", 0))
            comment    = (post.get("comment") or "").strip()

            if not program_id or not option_id:
                return request.redirect("/my/programs?error=Invalid submission. Please try again.")

            # Load and validate the chosen response option
            option = request.env["dsl.study.program.response.option"].sudo().browse(option_id)
            if not option.exists() or not option.active:
                return request.redirect("/my/programs?error=Invalid response option.")

            # Security: ensure program belongs to this student
            program = request.env["dsl.study.student.program.line"].sudo().search(
                [("id", "=", program_id), ("student_id", "=", student.id)], limit=1
            )
            if not program:
                return request.redirect("/my/programs?error=Program not found.")

            # Validate required comment
            if option.require_comment and not comment:
                return request.redirect(
                    "/my/programs?error=Please provide a comment before submitting."
                )

            student_name = student.name or request.env.user.name
            program_name = program.program_id.name or "N/A"

            # ── Write to DB ──────────────────────────────────────────────
            write_vals = {
                "student_disagree_reason": comment or False,
            }
            # Only yes/no types update student_portal_status
            if option.type in ("yes", "no"):
                write_vals["student_portal_status"] = option.type

            program.write(write_vals)

            # ── Post chatter message ─────────────────────────────────────
            if option.type == "yes":
                icon = "&#x2705;"
                decision_color = "green"
                decision_text  = "Yes &#x2013; I agree to proceed with this program."
            elif option.type == "no":
                icon = "&#x274C;"
                decision_color = "red"
                decision_text  = "No &#x2013; I do not wish to proceed with this program."
            else:
                icon = "&#x1F4AC;"
                decision_color = "#555"
                decision_text  = option.name

            comment_line = (
                Markup("<p><strong>Comment:</strong> {comment}</p>").format(comment=comment)
                if comment else Markup("")
            )

            body = Markup(
                "<p><strong>{icon} Student Response: {label}</strong></p>"
                "<p><strong>Student:</strong> {student_name}</p>"
                "<p><strong>Program:</strong> {program_name}</p>"
                "<p><strong>Decision:</strong> "
                "<span style='color:{color};'>{decision_text}</span></p>"
                "{comment_line}"
                "<p><em>Responded on: {date}</em></p>"
            ).format(
                icon=Markup(icon),
                label=option.name,
                student_name=student_name,
                program_name=program_name,
                color=decision_color,
                decision_text=Markup(decision_text),
                comment_line=comment_line,
                date=_date.today().strftime("%d %B, %Y"),
            )

            program.message_post(
                body=body,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
                author_id=request.env.user.partner_id.id,
            )

            _logger.info(
                f"Student {student_name} chose option '{option.name}' ({option.type}) "
                f"for program {program_name} (ID: {program_id})"
            )
            return request.redirect("/my/programs?success=Your response has been recorded successfully.")

        except Exception as e:
            _logger.error(f"Error in portal_program_respond: {str(e)}")
            return request.redirect(f"/my/programs?error=An error occurred: {str(e)}")

    @http.route(["/my/complaints"], type="http", auth="user", website=True)
    def student_complaints(self, **kw):
        identity_type = request.env.user.partner_id.identity_type
 
        if identity_type == "agent":
            agent = self._get_agent()
            if not agent:
                return request.redirect("/my/home?error=Agent record not found")
 
            complaints = (
                request.env["dsl.study.complain"]
                .sudo()
                .search([("agent_id", "=", agent.id)], order="id desc")
            )
            agent_students = (
                request.env["dsl.study.student"]
                .sudo()
                .search([("agent_ids", "in", agent.id)])
            )
            values = self._prepare_portal_layout_values()
            values.update({
                "agent": agent,
                "complaints": complaints,
                "agent_students": agent_students,
                "page_name": "complaints",
            })
            return request.render("dsl_student_portal.agent_complaints", values)
 
        else:  # default: student
            student = self._get_student()
            if not student:
                return request.redirect("/my/home?error=Student record not found")
 
            complaints = (
                request.env["dsl.study.complain"]
                .sudo()
                .search([("student_id", "=", student.id)], order="id desc")
            )
            values = self._prepare_portal_layout_values()
            values.update({
                "student": student,
                "complaints": complaints,
                "page_name": "complaints",
            })
            return request.render("dsl_student_portal.student_complaints", values)
 
 
    @http.route(
        ["/my/complaint/create"], type="http", auth="user", website=True, csrf=True
    )
    def student_complaint_create(self, **post):
        identity_type = request.env.user.partner_id.identity_type
 
        if identity_type == "agent":
            agent = self._get_agent()
            if not agent:
                return request.redirect("/my/home?error=Agent record not found")
            try:
                subject         = post.get("subject", "").strip()
                type_id         = int(post.get("type_id")) if post.get("type_id") else False
                student_id      = int(post.get("student_id")) if post.get("student_id") else False
                program_line_id = int(post.get("program_line_id")) if post.get("program_line_id") else False
                country_id      = int(post.get("country_id")) if post.get("country_id") else False
                description     = post.get("description", "").strip()
 
                if not subject or not description or not type_id:
                    return request.redirect(
                        "/my/complaints?error=Please fill all required fields."
                    )
 
                # Security: student must belong to this agent
                if student_id:
                    valid_student_ids = (
                        request.env["dsl.study.student"]
                        .sudo()
                        .search([("agent_ids", "in", agent.id)])
                        .ids
                    )
                    if student_id not in valid_student_ids:
                        return request.redirect(
                            "/my/complaints?error=Invalid student selected."
                        )
 
                # Security: program must belong to the selected student
                if program_line_id and student_id:
                    student_rec = request.env["dsl.study.student"].sudo().browse(student_id)
                    if program_line_id not in student_rec.program_ids.ids:
                        return request.redirect(
                            "/my/complaints?error=Invalid program selected."
                        )
 
                complaint_vals = {
                    "name": subject,
                    "agent_id": agent.id,
                    "student_id": student_id or False,
                    "type_id": type_id,
                    "country_id": country_id or False,
                    "program_line_id": program_line_id or False,
                    "note": description,
                    "state": "submit",
                }
                complaint = request.env["dsl.study.complain"].sudo().create(complaint_vals)
 
                # FIX 1: use sudo() so the portal user can read res.users
                # admin_user = request.env.ref("base.user_admin").sudo()
                # complaint.sudo().message_post(
                #     body=f"New complaint submitted by agent <b>{agent.name}</b>.",
                #     subtype_xmlid="mail.mt_note",
                #     partner_ids=[admin_user.partner_id.id],
                # )
 
                return request.redirect(
                    "/my/complaints?success=Complaint submitted successfully"
                )
 
            except Exception as e:
                _logger.error(f"Error creating agent complaint: {str(e)}")
                # FIX 2: strip newlines from the error so Werkzeug doesn't crash
                # on the redirect Location header
                safe_error = str(e).replace("\n", " ").replace("\r", " ")
                return request.redirect(f"/my/complaints?error={safe_error}")
 
        else:  # default: student
            student = self._get_student()
            if not student:
                return request.redirect("/my/home?error=Student record not found")
            try:
                subject              = post.get("subject")
                type_id              = int(post.get("type_id")) if post.get("type_id") else False
                program_line_id      = int(post.get("program_line_id")) if post.get("program_line_id") else False
                admission_officer_id = int(post.get("admission_officer_id")) if post.get("admission_officer_id") else False
                description          = post.get("description")
 
                if not subject or not description or not type_id:
                    return request.redirect(
                        "/my/complaints?error=Please fill all required fields."
                    )
 
                if program_line_id and program_line_id not in student.program_ids.ids:
                    return request.redirect(
                        "/my/complaints?error=Invalid program selected."
                    )
 
                if (
                    admission_officer_id
                    and admission_officer_id not in student.admission_officer_ids.ids
                ):
                    return request.redirect(
                        "/my/complaints?error=Invalid admission officer selected."
                    )
 
                complaint_vals = {
                    "name": subject,
                    "student_id": student.id,
                    "type_id": type_id or False,
                    "program_line_id": program_line_id or False,
                    "admission_officer_id": admission_officer_id or False,
                    "note": description,
                    "state": "submit",
                }
                request.env["dsl.study.complain"].sudo().create(complaint_vals)
                return request.redirect(
                    "/my/complaints?success=Complaint created successfully"
                )
 
            except Exception as e:
                _logger.error(f"Error creating complaint: {str(e)}")
                safe_error = str(e).replace("\n", " ").replace("\r", " ")
                return request.redirect(f"/my/complaints?error={safe_error}")
 
 
    @http.route(
        ["/my/complaint/student_programs/<int:student_id>"],
        type="http", auth="user", website=True
    )
    def agent_complaint_student_programs(self, student_id, **kw):
        """
        JSON endpoint — returns program lines for a given student,
        but only if that student belongs to the current agent.
        """
        import json as _json
        from odoo.http import Response
 
        agent = self._get_agent()
        if not agent:
            return Response(_json.dumps({"programs": []}), content_type="application/json")
 
        student = (
            request.env["dsl.study.student"]
            .sudo()
            .search([("id", "=", student_id), ("agent_ids", "in", agent.id)], limit=1)
        )
        if not student:
            return Response(_json.dumps({"programs": []}), content_type="application/json")
 
        programs = []
        for prog in student.program_ids:
            label = prog.program_id.name or "Program"
            if prog.institute_id:
                label = f"{label} — {prog.institute_id.name}"
            programs.append({"id": prog.id, "name": label})
 
        return Response(_json.dumps({"programs": programs}), content_type="application/json")


    @http.route(
        ["/my/complaint/student_countries/<int:student_id>"],
        type="http", auth="user", website=True
    )
    def agent_complaint_student_countries(self, student_id, **kw):
        """
        JSON endpoint: returns unique countries from a student's program lines,
        only if that student belongs to the current agent.
        """
        import json as _json
        from odoo.http import Response

        agent = self._get_agent()
        if not agent:
            return Response(_json.dumps({"countries": []}), content_type="application/json")

        student = (
            request.env["dsl.study.student"]
            .sudo()
            .search([("id", "=", student_id), ("agent_ids", "in", agent.id)], limit=1)
        )
        if not student:
            return Response(_json.dumps({"countries": []}), content_type="application/json")

        seen = set()
        countries = []
        for prog in student.program_ids:
            if prog.country_id and prog.country_id.id not in seen:
                seen.add(prog.country_id.id)
                countries.append({"id": prog.country_id.id, "name": prog.country_id.name})

        return Response(_json.dumps({"countries": countries}), content_type="application/json")

    # @http.route(
    #     ["/my/education/create"],
    #     type="http",
    #     auth="user",
    #     website=True,
    #     csrf=True,
    #     methods=["POST"],
    # )
    # def portal_add_education(self, **post):
    #     student = self._get_student()

    #     if not student:
    #         return request.redirect("/my/home?error=Student record not found")
    #     try:
    #         vals = {
    #             "student_id": student.id,
    #             "exam_type": post.get("exam_type"),
    #             "institution_name": post.get("institution_name"),
    #             "group_or_major": post.get("group_or_major"),
    #             "passing_year": post.get("passing_year"),
    #             "grade": post.get("grade") or False,
    #             "grade_point": (
    #                 float(post.get("grade_point")) if post.get("grade_point") else False
    #             ),
    #         }
    #         if not vals["exam_type"]:
    #             return request.redirect("/my/profile?error=Exam Type is required")
    #         request.env["dsl.study.student.result"].sudo().create(vals)
    #         return request.redirect("/my/profile?success=Education added")
    #     except Exception as e:
    #         _logger.exception("Error adding education")
    #         return request.redirect(f"/my/profile?error={str(e)}")
    @http.route(
    ["/my/education/create"],
    type="http",
    auth="user",
    website=True,
    csrf=True,
    methods=["POST"],
    )
    def portal_add_education(self, **post):
        student = self._get_student()
        if not student:
            return request.redirect("/my/home?error=Student record not found")
        try:
            exam_type = post.get("exam_type", "").strip()
            if not exam_type:
                return request.redirect("/my/profile?error=Exam Type is required")

            GPA_TYPES = ['ssc', 'hsc', 'dakhil', 'alim']
            PCT_TYPES = ['o_level', 'a_level']
            SCHOOL_TYPES = GPA_TYPES + PCT_TYPES

            vals = {
                "student_id": student.id,
                "exam_type": exam_type,
                "passing_year": post.get("passing_year", "").strip() or False,
            }

            # Institution — ID from dropdown
            if post.get("institution_id"):
                try:
                    vals["institution_id"] = int(post.get("institution_id"))
                except (ValueError, TypeError):
                    pass

            if exam_type in SCHOOL_TYPES:
                # Group (all school types)
                group = post.get("group", "").strip()
                if group:
                    vals["group"] = group

                if exam_type in GPA_TYPES:
                    # SSC / HSC / Dakhil / Alim → GPA
                    try:
                        gpa = float(post.get("gpa") or 0)
                        if gpa:
                            vals["gpa"] = gpa
                    except (ValueError, TypeError):
                        pass

                else:
                    # O-level / A-level → Percentage
                    try:
                        pct = float(post.get("percentage") or 0)
                        if pct:
                            vals["percentage"] = pct
                    except (ValueError, TypeError):
                        pass

            else:
                # Bachelor / Masters / Diploma / Others → Program ID + CGPA
                if post.get("program_id"):
                    try:
                        vals["program_id"] = int(post.get("program_id"))
                    except (ValueError, TypeError):
                        pass
                try:
                    cgpa = float(post.get("cgpa") or 0)
                    if cgpa:
                        vals["cgpa"] = cgpa
                except (ValueError, TypeError):
                    pass

            request.env["dsl.study.student.result"].sudo().create(vals)
            return request.redirect("/my/profile?success=Education added successfully")
        except Exception as e:
            _logger.exception("Error adding education")
            return request.redirect(f"/my/profile?error={str(e)}")

    @http.route(
        ["/my/parent/create"],
        type="http",
        auth="user",
        website=True,
        csrf=True,
        methods=["POST"],
    )
    def portal_add_parent(self, **post):
        _logger.info("+++++++++++++++++++++++=dasdf++++++++++++++++++")
        student = self._get_student()
        if not student:
            return request.redirect("/my/home?error=Student record not found")
        try:
            name = post.get("name")
            relation = post.get("relation")
            if not name or not relation:
                return request.redirect(
                    "/my/profile?error=Parent name & relation required"
                )
            vals = {
                "student_id": student.id,
                "name": name,
                "relation": relation,
                "phone": post.get("phone"),
                "email": post.get("email"),
                "occupation": post.get("occupation"),
            }
            request.env["dsl.study.parent"].sudo().create(vals)
            return request.redirect("/my/profile?success=Parent added")
        except Exception as e:
            _logger.exception("Error adding parent")
            return request.redirect(f"/my/profile?error={str(e)}")

    @http.route(
        ["/my/sponsor/create"],
        type="http",
        auth="user",
        website=True,
        csrf=True,
        methods=["POST"],
    )
    def portal_add_sponsor(self, **post):
        student = self._get_student()
        if not student:
            return request.redirect("/my/home?error=Student record not found")
        try:
            name = post.get("name")
            relation_id = post.get("relationship_id")
            profession_id = post.get("profession_id")
            
            if not name or not relation_id:
                return request.redirect(
                    "/my/profile?error=Sponsor name & relation required"
                )
            
            vals = {
                "student_id": student.id,
                "name": name,
                "relationship_id": int(relation_id),
                "profession_id": int(profession_id) if profession_id else False,
                "phone": post.get("phone"),
                "email": post.get("email"),
            }
            request.env["dsl.study.sponsor"].sudo().create(vals)
            return request.redirect("/my/profile?success=Sponsor added")
        except Exception as e:
            _logger.exception("Error adding sponsor")
            return request.redirect(f"/my/profile?error={str(e)}")

    @http.route(
        ["/my/agent/student/<int:student_id>"], type="http", auth="user", website=True
    )
    def agent_view_student(self, student_id, **kw):
        """Agent can view detailed information about their students"""
        agent = self._get_agent()
        if not agent:
            return request.redirect("/my/home?error=Agent record not found")

        # Verify the student belongs to this agent
        student = (
            request.env["dsl.study.student"]
            .sudo()
            .search([("id", "=", student_id), ("agent_ids", "in", agent.id)], limit=1)
        )

        if not student:
            return request.redirect(
                "/my/home?error=Student not found or unauthorized access"
            )

        values = self._prepare_portal_layout_values()
        values.update({
            "agent": agent,
            "student": student,
            "page_name": "student_detail",
        })

        return request.render(
            "dsl_student_portal.agent_student_detail",
            values,
        )

    @http.route(["/my/communication"], type="http", auth="user", website=True)
    def portal_student_communication(self, **kw):
        partner = request.env.user.partner_id

        student = (
            request.env["dsl.study.student"]
            .sudo()
            .search([("partner_id", "=", partner.id)], limit=1)
        )

        if not student:
            # Check if agent
            agent = self._get_agent()
            if agent:
                # Fetch all students assigned to this agent
                agent_students = request.env["dsl.study.student"].sudo().search(
                    [("agent_ids", "in", agent.id)],
                    order="name asc"
                )
                values = self._prepare_portal_layout_values()
                values.update({
                    "agent": agent,
                    "agent_students": agent_students,
                    "selected_student": None,
                    "page_name": "communication",
                })
                return request.render("dsl_student_portal.agent_communication", values)

            return request.render(
                "dsl_student_portal.student_not_found",
                {
                    "partner": partner,
                    "page_name": "communication",
                },
            )

        values = self._prepare_portal_layout_values()
        values.update({
            "student": student,
            "token": student.access_token,
            "page_name": "communication",
        })

        return request.render("dsl_student_portal.student_communication", values)

    @http.route(["/my/communication/student/<int:student_id>"], type="http", auth="user", website=True)
    def portal_agent_student_communication(self, student_id, **kw):
        """
        Agent selects a specific student to communicate with.
        Shows the student's chatter so agent can message the Admission Officer.
        """
        partner = request.env.user.partner_id
        agent = self._get_agent()

        if not agent:
            return request.redirect("/my/communication")

        # Verify this student is actually assigned to this agent
        student = request.env["dsl.study.student"].sudo().search([
            ("id", "=", student_id),
            ("agent_ids", "in", agent.id),
        ], limit=1)

        if not student:
            return request.redirect("/my/communication?error=Student not found or not assigned to you")

        # Ensure agent is a follower on this student record so messages work
        if agent.partner_id and agent.partner_id.id not in student.message_follower_ids.mapped('partner_id').ids:
            student.message_subscribe(partner_ids=[agent.partner_id.id])

        # Fetch all students for the sidebar list (so agent can switch)
        agent_students = request.env["dsl.study.student"].sudo().search(
            [("agent_ids", "in", agent.id)],
            order="name asc"
        )

        values = self._prepare_portal_layout_values()
        values.update({
            "agent": agent,
            "agent_students": agent_students,
            "selected_student": student,
            "token": student.access_token,
            "page_name": "communication",
        })
        return request.render("dsl_student_portal.agent_communication", values)
    
    @http.route(["/my/communication/attachment/add"], type="http", auth="user", website=True, methods=["POST"], csrf=False)
    def portal_communication_attachment_add(self, name, file, res_model, res_id, access_token=None, **kw):
        """
        Secure attachment upload for the portal chatter on dsl.study.student and dsl.study.agent.
        Validates ownership via partner match or access_token, then creates the attachment with sudo
        (bypassing the ACL that blocks portal users from reading these models directly).
        """
        ALLOWED_MODELS = {
            "dsl.study.student": "partner_id",
            "dsl.study.agent": "partner_id",
        }
        try:
            partner = request.env.user.partner_id

            if res_model not in ALLOWED_MODELS:
                return request.make_response(
                    '{"error": "Model not allowed"}',
                    headers=[('Content-Type', 'application/json')],
                    status=403
                )

            record = request.env[res_model].sudo().browse(int(res_id))
            if not record.exists():
                return request.make_response(
                    '{"error": "Record not found"}',
                    headers=[('Content-Type', 'application/json')],
                    status=404
                )

            # Validate ownership: partner match OR valid access_token OR agent assigned to student
            partner_field = ALLOWED_MODELS[res_model]
            record_partner_id = record[partner_field].id if record[partner_field] else False
            token_on_record = getattr(record, 'access_token', None)

            if record_partner_id != partner.id:
                # Check access_token first
                if access_token and token_on_record and token_on_record == access_token:
                    pass  # valid token — allow
                else:
                    # Check if current user is an agent assigned to this student
                    is_agent_allowed = False
                    if res_model == "dsl.study.student":
                        agent = request.env["dsl.study.agent"].sudo().search(
                            [("partner_id", "=", partner.id)], limit=1
                        )
                        if agent:
                            is_agent_allowed = request.env["dsl.study.student"].sudo().search_count([
                                ("id", "=", int(res_id)),
                                ("agent_ids", "in", agent.id),
                            ]) > 0
                    if not is_agent_allowed:
                        return request.make_response(
                            '{"error": "Access denied"}',
                            headers=[('Content-Type', 'application/json')],
                            status=403
                        )

            file_content = file.read()
            attachment = request.env["ir.attachment"].sudo().create({
                "name": name,
                "datas": base64.b64encode(file_content).decode(),
                "res_model": res_model,
                "res_id": int(res_id),
                "type": "binary",
            })
            return request.make_response(
                f'{{"id": {attachment.id}, "name": "{attachment.name}", "mimetype": "{attachment.mimetype}"}}',
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            _logger.error(f"Error in portal_communication_attachment_add: {str(e)}")
            return request.make_response(
                f'{{"error": "{str(e)}"}}',
                headers=[('Content-Type', 'application/json')],
                status=500
            )

    @http.route(["/my/documents"], type="http", auth="user", website=True)
    def portal_student_documents(self, **kw):
        partner = request.env.user.partner_id
        identity_type = partner.identity_type

        if identity_type == "student":
            student = (
                request.env["dsl.study.student"]
                .sudo()
                .search([("partner_id", "=", partner.id)], limit=1)
            )

            if not student:
                return request.render(
                    "dsl_student_portal.student_not_found",
                    {
                        "partner": partner,
                        "page_name": "documents",
                    },
                )

            # Get filter parameters
            state_filter = kw.get("state", "all")
            priority_filter = kw.get("priority", "all")
            
            # Get all student documents
            domain = [("student_id", "=", student.id)]
            
            # Get sponsor documents
            sponsor_domain = [("sponsor_id", "in", student.sponsor_ids.ids)]
            
            student_documents = request.env["dsl.study.student.document.line"].sudo().search(domain)
            sponsor_documents = request.env["dsl.study.student.document.line"].sudo().search(sponsor_domain)
            
            # Combine all documents
            all_documents = student_documents | sponsor_documents
            
            # Apply filters
            if state_filter != "all":
                all_documents = all_documents.filtered(lambda d: d.state == state_filter)
            
            if priority_filter != "all":
                all_documents = all_documents.filtered(lambda d: d.priority == priority_filter)
            
            # Sort by date
            documents = all_documents.sorted(key=lambda d: d.id, reverse=True)

            # Calculate statistics for all states
            not_received_count = len(all_documents.filtered(lambda d: d.state == "not_received"))
            received_count = len(all_documents.filtered(lambda d: d.state == "received"))
            ready_count = len(all_documents.filtered(lambda d: d.state == "ready"))
            submit_count = len(all_documents.filtered(lambda d: d.state == "submit"))
            
            required_count = len(all_documents.filtered(lambda d: d.priority == "required"))
            optional_count = len(all_documents.filtered(lambda d: d.priority == "optional"))
            
            overdue_count = len(all_documents.filtered(lambda d: d.is_overdue))

            values = self._prepare_portal_layout_values()
            values.update({
                "student": student,
                "documents": documents,
                "not_received_count": not_received_count,
                "received_count": received_count,
                "ready_count": ready_count,
                "submit_count": submit_count,
                "required_count": required_count,
                "optional_count": optional_count,
                "overdue_count": overdue_count,
                "state_filter": state_filter,
                "priority_filter": priority_filter,
                "page_name": "documents",
                "success": kw.get("success", ""),
                "error": kw.get("error", ""),
            })

            return request.render("dsl_student_portal.student_documents", values)
        
        elif identity_type == "agent":
            # Agent view - show documents for all assigned students
            agent = self._get_agent()
            if not agent:
                return request.redirect("/my/home?error=Agent record not found")
            
            # Get filter parameters
            state_filter = kw.get("state", "all")
            priority_filter = kw.get("priority", "all")
            student_filter = kw.get("student_id", "all")
            
            # Get all students assigned to this agent
            students = request.env["dsl.study.student"].sudo().search([("agent_ids", "in", agent.id)])
            
            # Build domain for documents
            domain = [
                "|",
                ("student_id", "in", students.ids),
                ("sponsor_id.student_id", "in", students.ids)
            ]
            
            documents = request.env["dsl.study.student.document.line"].sudo().search(domain)
            
            # Apply filters
            if state_filter != "all":
                documents = documents.filtered(lambda d: d.state == state_filter)
            
            if priority_filter != "all":
                documents = documents.filtered(lambda d: d.priority == priority_filter)
                
            if student_filter != "all":
                student_filter_id = int(student_filter)
                documents = documents.filtered(
                    lambda d: d.student_id.id == student_filter_id or 
                    (d.sponsor_id and d.sponsor_id.student_id.id == student_filter_id)
                )
            
            # Sort by date
            documents = documents.sorted(key=lambda d: d.id, reverse=True)
            
            # Calculate statistics
            not_received_count = len(documents.filtered(lambda d: d.state == "not_received"))
            received_count = len(documents.filtered(lambda d: d.state == "received"))
            ready_count = len(documents.filtered(lambda d: d.state == "ready"))
            submit_count = len(documents.filtered(lambda d: d.state == "submit"))
            
            required_count = len(documents.filtered(lambda d: d.priority == "required"))
            optional_count = len(documents.filtered(lambda d: d.priority == "optional"))
            
            overdue_count = len(documents.filtered(lambda d: d.is_overdue))
            
            
            overdue_count = len(documents.filtered(lambda d: d.is_overdue))
            
            values = self._prepare_portal_layout_values()
            values.update({
                "agent": agent,
                "students": students,
                "documents": documents,
                "not_received_count": not_received_count,
                "received_count": received_count,
                "ready_count": ready_count,
                "submit_count": submit_count,
                "required_count": required_count,
                "optional_count": optional_count,
                "overdue_count": overdue_count,
                "state_filter": state_filter,
                "priority_filter": priority_filter,
                "student_filter": student_filter,
                "page_name": "documents",
                "success": kw.get("success", ""),
                "error": kw.get("error", ""),
            })
            
            return request.render("dsl_student_portal.agent_documents", values)
        
        else:
            return request.redirect("/my/home?error=Access Denied")
    
    @http.route(["/my/document/upload"], type="http", auth="user", website=True, csrf=True, methods=["POST"])
    def portal_upload_document(self, **post):
        """Handle document upload for students"""
        try:
            partner = request.env.user.partner_id
            
            # Check if user is a student
            student = request.env["dsl.study.student"].sudo().search([("partner_id", "=", partner.id)], limit=1)
            if not student:
                return request.redirect("/my/documents?error=Student record not found")
            
            document_id = post.get("document_id")
            uploaded_file = request.httprequest.files.get("file")
            
            if not document_id or not uploaded_file:
                return request.redirect("/my/documents?error=Missing document ID or file")
            
            # Get the document line
            document = request.env["dsl.study.student.document.line"].sudo().browse(int(document_id))
            
            # Verify the document belongs to this student or their sponsor
            if document.student_id.id != student.id and (not document.sponsor_id or document.sponsor_id.student_id.id != student.id):
                return request.redirect("/my/documents?error=Unauthorized access to document")
            
            # Validate file size (max 10MB)
            file_content = uploaded_file.read()
            if len(file_content) > 10 * 1024 * 1024:
                return request.redirect("/my/documents?error=File size exceeds 10MB limit")
            
            # Validate file type
            allowed_extensions = ['.pdf', '.jpg', '.jpeg', '.png', '.doc', '.docx']
            file_ext = uploaded_file.filename.lower()[uploaded_file.filename.rfind('.'):]
            if file_ext not in allowed_extensions:
                return request.redirect(f"/my/documents?error=Invalid file type. Allowed: {', '.join(allowed_extensions)}")
            
            # Delete old attachment if exists
            if document.attachment_id:
                document.attachment_id.unlink()
            
            # Create new attachment
            attachment = request.env["ir.attachment"].sudo().create({
                "name": uploaded_file.filename,
                "datas": base64.b64encode(file_content),
                "res_model": "dsl.study.student.document.line",
                "res_id": document.id,
                "type": "binary",
            })
            
            # Update document
            document.write({
                "attachment_id": attachment.id,
                "state": "received",
                "date": request.env["ir.fields"].Date.context_today(document),
            })
            
            _logger.info(f"Document uploaded successfully: {uploaded_file.filename} for document {document.id}")
            return request.redirect(f"/my/documents?success=Document uploaded successfully: {uploaded_file.filename}")
            
        except Exception as e:
            _logger.error(f"Error uploading document: {str(e)}")
            return request.redirect(f"/my/documents?error=Upload failed: {str(e)}")
    
    @http.route(["/my/document/download/<int:document_id>"], type="http", auth="user", website=True)
    def portal_download_document(self, document_id, **kw):
        """Download document attachment"""
        try:
            partner = request.env.user.partner_id
            identity_type = partner.identity_type
            
            # Get the document
            document = request.env["dsl.study.student.document.line"].sudo().browse(document_id)
            if not document or not document.attachment_id:
                return request.redirect("/my/documents?error=Document not found or no attachment")
            
            # Verify access rights
            if identity_type == "student":
                student = request.env["dsl.study.student"].sudo().search([("partner_id", "=", partner.id)], limit=1)
                if not student or (document.student_id.id != student.id and 
                                  (not document.sponsor_id or document.sponsor_id.student_id.id != student.id)):
                    return request.redirect("/my/documents?error=Unauthorized access")
            
            elif identity_type == "agent":
                agent = self._get_agent()
                if not agent:
                    return request.redirect("/my/documents?error=Agent not found")
                
                # Check if document belongs to one of agent's students
                student_ids = request.env["dsl.study.student"].sudo().search([("agent_ids", "in", agent.id)]).ids
                if document.student_id.id not in student_ids and \
                   (not document.sponsor_id or document.sponsor_id.student_id.id not in student_ids):
                    return request.redirect("/my/documents?error=Unauthorized access")
            else:
                return request.redirect("/my/documents?error=Access denied")
            
            # Return the attachment
            return request.env["ir.binary"]._get_stream_from(document.attachment_id).get_response(as_attachment=True)
            
        except Exception as e:
            _logger.error(f"Error downloading document: {str(e)}")
            return request.redirect(f"/my/documents?error=Download failed: {str(e)}")
    
    @http.route(["/my/notifications"], type="http", auth="user", website=True)
    def portal_student_notifications(self, **kw):
        # Get standard portal layout values including notifications
        values = self._prepare_portal_layout_values()
        
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
        notices = request.env['dsl.study.notice'].sudo().search(domain, order='create_date desc')
        
        values.update({
            "notices": notices,
            "page_name": "notifications"
        })
        
        return request.render("dsl_student_portal.student_notifications", values)

    @http.route(['/my/invoices', '/my/invoices/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_invoices(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, **kw):
        """Override Odoo's portal_my_invoices to inject student sidebar."""
        partner = request.env.user.partner_id
        identity_type = partner.identity_type

        if identity_type == 'student':
            student = self._get_student()
            if not student:
                return request.redirect('/my/home?error=Student record not found')

            values = self._prepare_portal_layout_values()

            # Fetch all posted invoices for this student
            invoices = request.env['account.move'].sudo().search([
                ('partner_id', '=', student.partner_id.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
            ], order='invoice_date desc')

            values.update({
                'student': student,
                'invoices': invoices,
                'page_name': 'invoices',
            })
            return request.render('dsl_student_portal.student_invoices', values)

        # Agent: custom invoice page with agent sidebar
        if identity_type == 'agent':
            agent = self._get_agent()
            if not agent:
                return request.redirect('/my/home?error=Agent record not found')

            values = self._prepare_portal_layout_values()

            # ------------------------------------------------------------------
            # OPTION A: Agent's own (commission) invoices — billed to the agent
            # ------------------------------------------------------------------
            # invoices = request.env['account.move'].sudo().search([
            #     ('partner_id', '=', agent.partner_id.id),
            #     ('move_type', '=', 'out_invoice'),
            #     ('state', '=', 'posted'),
            # ], order='invoice_date desc')

            # ------------------------------------------------------------------
            # OPTION B: All students' invoices under this agent
            # This matches the sidebar count calculated in portal.py
            # ------------------------------------------------------------------
            agent_students = request.env['dsl.study.student'].sudo().search([
                ('agent_ids', 'in', agent.id)
            ])
            student_partners = agent_students.mapped('partner_id')

            # Build a partner_id → student map for displaying student name/ID in the list
            partner_to_student = {s.partner_id.id: s for s in agent_students}

            invoices = request.env['account.move'].sudo().search([
                ('partner_id', 'in', student_partners.ids),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
            ], order='invoice_date desc')

            values.update({
                'agent': agent,
                'invoices': invoices,
                'partner_to_student': partner_to_student,
                'page_name': 'invoices',
            })
            return request.render('dsl_student_portal.agent_invoices', values)

        # Fallback for other identity types
        return request.redirect('/my/home')

    @http.route(['/my/sponsor'], type='http', auth='user', website=True)
    def student_sponsor(self, **kw):
        student = self._get_student()
        if not student:
            return request.redirect('/my/home?error=Student record not found')
        values = self._prepare_portal_layout_values()
        sponsors = student.sponsor_ids
        values.update({
            'student': student,
            'sponsors': sponsors,
            'page_name': 'sponsor',
        })
        return request.render('dsl_student_portal.student_sponsor', values)

    @http.route(['/my/security'], type='http', auth='user', website=True)
    def portal_my_security(self, **kw):
        """Override Odoo's portal_my_security to inject student sidebar."""
        partner = request.env.user.partner_id
        identity_type = partner.identity_type

        if identity_type == 'student':
            student = self._get_student()
            if not student:
                return request.redirect('/my/home?error=Student record not found')

            values = self._prepare_portal_layout_values()

            user = request.env.user
            two_factor_state = 'enabled' if user.totp_enabled else 'disabled'

            values.update({
                'student': student,
                'page_name': 'security',
                'two_factor_state': two_factor_state,
                'get_error': kw.get('error', ''),
                'get_success': kw.get('success', ''),
            })
            return request.render('dsl_student_portal.student_security', values)

        # Agent: custom security page with agent sidebar
        if identity_type == 'agent':
            agent = self._get_agent()
            if not agent:
                return request.redirect('/my/home?error=Agent record not found')

            values = self._prepare_portal_layout_values()
            user = request.env.user
            two_factor_state = 'enabled' if user.totp_enabled else 'disabled'
            values.update({
                'agent': agent,
                'page_name': 'security',
                'two_factor_state': two_factor_state,
                'get_error': kw.get('error', ''),
                'get_success': kw.get('success', ''),
            })
            return request.render('dsl_student_portal.agent_security', values)

        # Fallback for other identity types
        return request.redirect('/my/home')

    @http.route(['/my/commission'], type='http', auth='user', website=True)
    def agent_commission(self, **kw):
        agent = self._get_agent()
        if not agent:
            return request.redirect('/my/home?error=Agent record not found')
        values = self._prepare_portal_layout_values()
        values.update({'agent': agent, 'page_name': 'commission'})
        return request.render('dsl_student_portal.agent_commission', values)

    @http.route(['/my/contract'], type='http', auth='user', website=True)
    def agent_contract(self, **kw):
        agent = self._get_agent()
        if not agent:
            return request.redirect('/my/home?error=Agent record not found')
        values = self._prepare_portal_layout_values()
        values.update({'agent': agent, 'page_name': 'contract'})
        return request.render('dsl_student_portal.agent_contract', values)
    
    # ── ROW-LEVEL upload/delete — commented out for now ──────────────────────
    #
    # @http.route(
    #     ['/my/contract/line/<int:line_id>/upload'],
    #     type='http', auth='user', website=True, methods=['POST'], csrf=True,
    # )
    # def contract_line_upload(self, line_id, **kw):
    #     """Agent uploads / replaces a document on a single commission line."""
    #     agent = self._get_agent()
    #     if not agent:
    #         return request.redirect('/my/home?error=Agent record not found')
    #
    #     # Security: the line must belong to this agent
    #     line = request.env['dsl.study.agent.line'].sudo().search(
    #         [('id', '=', line_id), ('parent_id', '=', agent.id)], limit=1
    #     )
    #     if not line:
    #         return request.redirect('/my/contract?error=Line not found')
    #
    #     upload = kw.get('document')
    #     if not upload or not hasattr(upload, 'read'):
    #         return request.redirect('/my/contract?error=No file selected')
    #
    #     file_data = upload.read()
    #     if not file_data:
    #         return request.redirect('/my/contract?error=Empty file')
    #
    #     line.sudo().write({
    #         'document': base64.b64encode(file_data),
    #         'document_filename': upload.filename,
    #     })
    #     return request.redirect('/my/contract?success=Document uploaded successfully')
    #
    # @http.route(
    #     ['/my/contract/line/<int:line_id>/delete-doc'],
    #     type='http', auth='user', website=True, methods=['POST'], csrf=True,
    # )
    # def contract_line_delete_doc(self, line_id, **kw):
    #     """Agent removes the document from a commission line."""
    #     agent = self._get_agent()
    #     if not agent:
    #         return request.redirect('/my/home?error=Agent record not found')
    #
    #     line = request.env['dsl.study.agent.line'].sudo().search(
    #         [('id', '=', line_id), ('parent_id', '=', agent.id)], limit=1
    #     )
    #     if not line:
    #         return request.redirect('/my/contract?error=Line not found')
    #
    #     line.sudo().write({'document': False, 'document_filename': False})
    #     return request.redirect('/my/contract?success=Document removed')
    # ── end ROW-LEVEL ─────────────────────────────────────────────────────────
 
    @http.route(
        ['/my/contract/upload'],
        type='http', auth='user', website=True, methods=['POST'], csrf=True,
    )
    def contract_page_upload(self, **kw):
        """Agent uploads / replaces the page-level contract document
        (stored on dsl.study.agent → business_certificate)."""
        agent = self._get_agent()
        if not agent:
            return request.redirect('/my/home?error=Agent record not found')
 
        upload = kw.get('document')
        if not upload or not hasattr(upload, 'read'):
            return request.redirect('/my/contract?error=No file selected')
 
        file_data = upload.read()
        if not file_data:
            return request.redirect('/my/contract?error=Empty file')
 
        agent.sudo().write({
            'contract_document': base64.b64encode(file_data),
            'contract_document_filename': upload.filename,
        })
        return request.redirect('/my/contract?success=Contract document uploaded successfully')
 
    @http.route(
        ['/my/contract/delete-doc'],
        type='http', auth='user', website=True, methods=['POST'], csrf=True,
    )
    def contract_page_delete_doc(self, **kw):
        """Agent removes the page-level contract document."""
        agent = self._get_agent()
        if not agent:
            return request.redirect('/my/home?error=Agent record not found')
 
        agent.sudo().write({'contract_document': False, 'contract_document_filename': False})
        return request.redirect('/my/contract?success=Contract document removed')
 

    # ─────────────────────────────────────────────────────────────────────────
    # Agent Dashboard Card — Detail Pages
    # ─────────────────────────────────────────────────────────────────────────

    def _get_agent_or_redirect(self):
        """Helper: return agent or redirect if not found."""
        agent = self._get_agent()
        if not agent:
            return None, request.redirect('/my/home?error=Agent record not found')
        return agent, None

    def _agent_base_values(self, agent, page_name):
        """Helper: build base values dict for agent detail pages."""
        values = self._prepare_portal_layout_values()
        values.update({'agent': agent, 'page_name': page_name})
        return values

    # ── 1. My Students ────────────────────────────────────────────────────────
    @http.route(['/my/agent/students'], type='http', auth='user', website=True)
    def agent_my_students(self, **kw):
        agent, redirect = self._get_agent_or_redirect()
        if redirect:
            return redirect

        agent_students = request.env['dsl.study.student'].sudo().search(
            [('agent_ids', 'in', agent.id)]
        )
        values = self._agent_base_values(agent, 'dashboard')
        values.update({
            'page_title': 'My Students',
            'card_type': 'students',
            'students': agent_students,
            'program_lines': request.env['dsl.study.student.program.line'].sudo(),
            'active_filter': None,
        })
        return request.render('dsl_student_portal.agent_card_detail', values)

    # ── 2. Total Applications ─────────────────────────────────────────────────
    @http.route(['/my/agent/students/applications'], type='http', auth='user', website=True)
    def agent_total_applications(self, **kw):
        agent, redirect = self._get_agent_or_redirect()
        if redirect:
            return redirect

        agent_students = request.env['dsl.study.student'].sudo().search(
            [('agent_ids', 'in', agent.id)]
        )
        all_programs = request.env['dsl.study.student.program.line'].sudo().search(
            [('student_id', 'in', agent_students.ids)]
        )
        values = self._agent_base_values(agent, 'dashboard')
        values.update({
            'page_title': 'Total Applications',
            'card_type': 'applications',
            'students': agent_students,
            'program_lines': all_programs,
            'active_filter': None,
            'filter_tabs': [],
        })
        return request.render('dsl_student_portal.agent_card_detail', values)

    # ── 3. Application Submitted ──────────────────────────────────────────────
    @http.route(['/my/agent/students/apply'], type='http', auth='user', website=True)
    def agent_submitted(self, state=None, **kw):
        agent, redirect = self._get_agent_or_redirect()
        if redirect:
            return redirect

        # state comes directly as method param from query string (?state=submit etc.)
        agent_students = request.env['dsl.study.student'].sudo().search(
            [('agent_ids', 'in', agent.id)]
        )
        programs = request.env['dsl.study.student.program.line'].sudo().search(
            [('student_id', 'in', agent_students.ids), ('stage_code', '=', 'applied')]
        )
        if state:
            programs = programs.filtered(lambda p: p.apply_state == state)
        else:
            # Default: show only 'submit' state (matching the dashboard card count)
            programs = programs.filtered(lambda p: p.apply_state == 'submit')

        values = self._agent_base_values(agent, 'dashboard')
        values.update({
            'page_title': 'Application Submitted',
            'card_type': 'submitted',
            'students': agent_students,
            'program_lines': programs,
            'active_filter': state,
            'filter_tabs': [
                {'key': None,          'label': 'All',         'color': 'secondary'},
                {'key': 'submit',      'label': 'Submit',      'color': 'primary'},
                {'key': 'in_progress', 'label': 'In Progress', 'color': 'warning'},
                {'key': 'pending',     'label': 'Pending',     'color': 'dark'},
            ],
            'state_field': 'apply_state',
            'state_display': {
                'submit':      ('Submit',      'primary'),
                'in_progress': ('In Progress', 'warning'),
                'pending':     ('Pending',     'secondary'),
            },
        })
        return request.render('dsl_student_portal.agent_card_detail', values)

    # ── 4. Offer Received ─────────────────────────────────────────────────────
    @http.route(['/my/agent/students/offer'], type='http', auth='user', website=True)
    def agent_offer_received(self, **kw):
        agent, redirect = self._get_agent_or_redirect()
        if redirect:
            return redirect

        # Offer Received = Final Offer stage where final_offer_state == 'received'
        state = kw.get('state')  # received | not_received | None (all)
        agent_students = request.env['dsl.study.student'].sudo().search(
            [('agent_ids', 'in', agent.id)]
        )
        programs = request.env['dsl.study.student.program.line'].sudo().search(
            [('student_id', 'in', agent_students.ids), ('stage_code', '=', 'final_offer')]
        )
        if state:
            programs = programs.filtered(lambda p: p.final_offer_state == state)

        values = self._agent_base_values(agent, 'dashboard')
        values.update({
            'page_title': 'Offer Received',
            'card_type': 'offer',
            'students': agent_students,
            'program_lines': programs,
            'active_filter': state,
            'filter_tabs': [
                {'key': None,           'label': 'All',          'color': 'secondary'},
                {'key': 'received',     'label': 'Received',     'color': 'success'},
                {'key': 'not_received', 'label': 'Not Received', 'color': 'warning'},
            ],
            'state_field': 'final_offer_state',
            'state_display': {
                'received':     ('Received',     'success'),
                'not_received': ('Not Received', 'warning'),
            },
        })
        return request.render('dsl_student_portal.agent_card_detail', values)

    # ── 5. Documentation ──────────────────────────────────────────────────────
    @http.route(['/my/agent/students/documentation'], type='http', auth='user', website=True)
    def agent_documentation(self, **kw):
        agent, redirect = self._get_agent_or_redirect()
        if redirect:
            return redirect

        state = kw.get('state')  # file_ready | in_progress | None
        agent_students = request.env['dsl.study.student'].sudo().search(
            [('agent_ids', 'in', agent.id)]
        )
        programs = request.env['dsl.study.student.program.line'].sudo().search(
            [('student_id', 'in', agent_students.ids), ('stage_code', '=', 'sponsor_document')]
        )
        if state:
            programs = programs.filtered(lambda p: p.sponsor_and_document_state == state)

        values = self._agent_base_values(agent, 'dashboard')
        values.update({
            'page_title': 'Documentation',
            'card_type': 'documentation',
            'students': agent_students,
            'program_lines': programs,
            'active_filter': state,
            'filter_tabs': [
                {'key': None,         'label': 'All',         'color': 'secondary'},
                {'key': 'file_ready', 'label': 'File Ready',  'color': 'success'},
                {'key': 'in_progress','label': 'In Progress', 'color': 'warning'},
            ],
            'state_field': 'sponsor_and_document_state',
            'state_display': {
                'file_ready':  ('File Ready',  'success'),
                'in_progress': ('In Progress', 'warning'),
            },
        })
        return request.render('dsl_student_portal.agent_card_detail', values)

    # ── 6. Visa Status ────────────────────────────────────────────────────────
    @http.route(['/my/agent/students/visa'], type='http', auth='user', website=True)
    def agent_visa_status(self, **kw):
        agent, redirect = self._get_agent_or_redirect()
        if redirect:
            return redirect

        state = kw.get('state')  # apply | approve | reject | None
        agent_students = request.env['dsl.study.student'].sudo().search(
            [('agent_ids', 'in', agent.id)]
        )
        programs = request.env['dsl.study.student.program.line'].sudo().search(
            [('student_id', 'in', agent_students.ids), ('stage_code', '=', 'visa_processing')]
        )
        if state:
            programs = programs.filtered(lambda p: p.visa_state == state)

        values = self._agent_base_values(agent, 'dashboard')
        values.update({
            'page_title': 'Visa Status',
            'card_type': 'visa',
            'students': agent_students,
            'program_lines': programs,
            'active_filter': state,
            'filter_tabs': [
                {'key': None,      'label': 'All',      'color': 'secondary'},
                {'key': 'apply',   'label': 'Applied',  'color': 'primary'},
                {'key': 'approve', 'label': 'Approved', 'color': 'success'},
                {'key': 'reject',  'label': 'Rejected', 'color': 'danger'},
            ],
            'state_field': 'visa_state',
            'state_display': {
                'apply':   ('Applied',  'primary'),
                'approve': ('Approved', 'success'),
                'reject':  ('Rejected', 'danger'),
            },
        })
        return request.render('dsl_student_portal.agent_card_detail', values)

    # ── 7. Tuition Fees Paid ──────────────────────────────────────────────────
    @http.route(['/my/agent/students/tuition'], type='http', auth='user', website=True)
    def agent_tuition_paid(self, **kw):
        agent, redirect = self._get_agent_or_redirect()
        if redirect:
            return redirect

        state = kw.get('state')  # paid | unpaid | None (all)
        agent_students = request.env['dsl.study.student'].sudo().search(
            [('agent_ids', 'in', agent.id)]
        )
        # Only programs currently in 'tuition_fee' stage
        programs = request.env['dsl.study.student.program.line'].sudo().search(
            [('student_id', 'in', agent_students.ids), ('stage_code', '=', 'tuition_fee')]
        )
        if state:
            programs = programs.filtered(lambda p: p.tuition_fee_state == state)
        else:
            # Default: show only paid (matching the dashboard card count)
            programs = programs.filtered(lambda p: p.tuition_fee_state == 'paid')

        values = self._agent_base_values(agent, 'dashboard')
        values.update({
            'page_title': 'Tuition Fees',
            'card_type': 'tuition',
            'students': agent_students,
            'program_lines': programs,
            'active_filter': state,
            'filter_tabs': [
                {'key': None,    'label': 'All',    'color': 'secondary'},
                {'key': 'paid',  'label': 'Paid',   'color': 'success'},
                {'key': 'unpaid','label': 'Unpaid', 'color': 'danger'},
            ],
        })
        return request.render('dsl_student_portal.agent_card_detail', values)

    # ── 8. In-Active Students ─────────────────────────────────────────────────
    @http.route(['/my/agent/students/inactive'], type='http', auth='user', website=True)
    def agent_inactive_students(self, **kw):
        agent, redirect = self._get_agent_or_redirect()
        if redirect:
            return redirect
 
        # In-Active = students whose state == 'cancelled' under this agent
        inactive_students = request.env['dsl.study.student'].sudo().search([
            ('agent_ids', 'in', agent.id),
            ('state', '=', 'cancelled'),
            ('active', 'in', [True, False]),
        ])
 
        values = self._agent_base_values(agent, 'dashboard')
        values.update({
            'page_title': 'In-Active Students',
            'card_type': 'inactive',
            'students': inactive_students,
            'program_lines': request.env['dsl.study.student.program.line'].sudo(),
            'active_filter': None,
            'filter_tabs': [],
        })
        return request.render('dsl_student_portal.agent_card_detail', values)

    # ─────────────────────────────────────────────────────────────────────────
    # Agent Contact Persons — Add (create new), Link (existing), Delete, Search
    # ─────────────────────────────────────────────────────────────────────────

    @http.route(
        ['/my/agent/contact/add'],
        type='http', auth='user', website=True, csrf=True, methods=['POST'],
    )
    def agent_contact_add(self, **post):
        """Create a new res.partner (individual) and link to agent's contact_ids."""
        agent = self._get_agent()
        if not agent:
            return request.redirect('/my/home?error=Agent record not found')

        try:
            name = post.get('contact_name', '').strip()
            if not name:
                return request.redirect('/my/profile?error=Please provide a contact name')

            partner = request.env['res.partner'].sudo().create({
                'name': name,
                'x_designation': post.get('contact_xdesignation', '').strip() or False,
                'email': post.get('contact_email', '').strip() or False,
                'mobile': post.get('contact_mobile', '').strip() or False,
                'is_company': False,
            })
            agent.sudo().write({
                'contact_ids': [(4, partner.id)],
            })
            return request.redirect('/my/profile?success=Contact person added successfully')

        except Exception as e:
            _logger.error(f'Error creating agent contact: {str(e)}')
            return request.redirect(f'/my/profile?error={str(e)}')

    @http.route(
        ['/my/agent/contact/link'],
        type='http', auth='user', website=True, csrf=True, methods=['POST'],
    )
    def agent_contact_link(self, **post):
        """Link an existing res.partner to agent's contact_ids."""
        agent = self._get_agent()
        if not agent:
            return request.redirect('/my/home?error=Agent record not found')

        try:
            partner_id = int(post.get('partner_id', 0))
            if not partner_id:
                return request.redirect('/my/profile?error=Please select a partner')

            partner = request.env['res.partner'].sudo().browse(partner_id)
            if not partner.exists() or partner.is_company:
                return request.redirect('/my/profile?error=Invalid partner selected')

            # Check not already linked
            if partner.id in agent.contact_ids.ids:
                return request.redirect('/my/profile?error=This contact is already linked')

            agent.sudo().write({
                'contact_ids': [(4, partner.id)],
            })
            return request.redirect('/my/profile?success=Contact person linked successfully')

        except Exception as e:
            _logger.error(f'Error linking agent contact: {str(e)}')
            return request.redirect(f'/my/profile?error={str(e)}')

    @http.route(
        ['/my/agent/contact/delete/<int:contact_id>'],
        type='http', auth='user', website=True, csrf=True, methods=['POST'],
    )
    def agent_contact_delete(self, contact_id, **kw):
        """Unlink a contact partner from agent's contact_ids (does NOT delete res.partner)."""
        agent = self._get_agent()
        if not agent:
            return request.redirect('/my/home?error=Agent record not found')

        try:
            if contact_id in agent.contact_ids.ids:
                agent.sudo().write({
                    'contact_ids': [(3, contact_id)],  # (3, id) = unlink, don't delete
                })
                return request.redirect('/my/profile?success=Contact person removed')
            else:
                return request.redirect('/my/profile?error=Contact not found or unauthorized')

        except Exception as e:
            _logger.error(f'Error removing agent contact: {str(e)}')
            return request.redirect(f'/my/profile?error={str(e)}')

    @http.route(
        ['/my/agent/contact/search'],
        type='http', auth='user', website=True, csrf=False, methods=['GET'],
    )
    def agent_contact_search(self, q='', **kw):
        """Autocomplete search for individual res.partner records."""
        import json as _json
        try:
            if not q or len(q) < 2:
                return request.make_response(
                    _json.dumps([]),
                    headers=[('Content-Type', 'application/json')]
                )
            partners = request.env['res.partner'].sudo().search([
                ('is_company', '=', False),
                ('name', 'ilike', q),
            ], limit=10)
            result = [{
                'id': p.id,
                'name': p.name,
                'email': p.email or '',
                'mobile': p.mobile or p.phone or '',
            } for p in partners]
            return request.make_response(
                _json.dumps(result),
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            _logger.error(f'Error searching partners: {str(e)}')
            return request.make_response(
                _json.dumps([]),
                headers=[('Content-Type', 'application/json')]
            )
from odoo import models, fields, api
from datetime import date, timedelta
import logging

_logger = logging.getLogger(__name__)


class AttendanceSummaryReport(models.AbstractModel):
    _name = "report.auto_leave_deduction.attendance_summary_template"
    _description = "Attendance Summary Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data:
            data = {}

        date_from = fields.Date.from_string(data.get("date_from"))
        date_to = fields.Date.from_string(data.get("date_to"))
        employee_ids = data.get("employee_ids", [])
        department_id = data.get("department_id", False)

        # ── Resolve employees ────────────────────────────────────────────────
        Employee = self.env["hr.employee"]
        domain = [("active", "=", True)]
        if employee_ids:
            domain.append(("id", "in", employee_ids))
        if department_id:
            domain.append(("department_id", "=", department_id))

        employees = Employee.search(domain, order="name asc")

        rows = []
        for emp in employees:
            rows.append(self._compute_employee_summary(emp, date_from, date_to))

        return {
            "date_from": date_from,
            "date_to": date_to,
            "rows": rows,
            "company": self.env.company,
        }

    def _get_leave_balance(self, employee):
        """Current year er approved allocation theke leave balance ber kora."""
        current_year = date.today().year
        year_start = date(current_year, 1, 1)
        year_end = date(current_year, 12, 31)

        allocation = self.env["hr.leave.allocation"].search([
            ("employee_id", "=", employee.id),
            ("state", "=", "validate"),
            ("date_from", ">=", fields.Date.to_string(year_start)),
            ("date_from", "<=", fields.Date.to_string(year_end)),
        ], limit=1)

        if not allocation:
            return "—"

        total = int(allocation.number_of_days)
        remaining = int(allocation.number_of_days - allocation.leaves_taken)
        return f"{remaining}/{total}"

    def _compute_employee_summary(self, employee, date_from, date_to):
        """Compute attendance summary counts for one employee."""
        Attendance = self.env["hr.attendance"]

        # All attendance records in range (including auto-generated)
        attendances = Attendance.search([
            ("employee_id", "=", employee.id),
            ("check_in", ">=", fields.Datetime.to_datetime(f"{date_from} 00:00:00")),
            ("check_in", "<=", fields.Datetime.to_datetime(f"{date_to} 23:59:59")),
        ])

        late_count = 0
        early_checkout_count = 0
        absent_count = 0
        leave_count = 0
        post_noon_count = 0
        on_time_count = 0
        missed_checkout_count = 0
        sat_off_count = 0
        total_working_days = 0

        covered_dates = set()

        for att in attendances:
            status = att.status_type
            check_date = att.check_in.date() if att.check_in else None

            if not check_date:
                continue

            if att.auto_generated:
                if status == "absent":
                    absent_count += 1
                    total_working_days += 1
                    covered_dates.add(check_date)
                elif status == "leave":
                    leave_count += 1
                    total_working_days += 1
                    covered_dates.add(check_date)
                elif status == "sat_off":
                    sat_off_count += 1
                    covered_dates.add(check_date)
                continue

            covered_dates.add(check_date)
            total_working_days += 1

            if status == "late":
                late_count += 1
            elif status == "early_checkout":
                early_checkout_count += 1
            elif status == "late_early":
                late_count += 1
                early_checkout_count += 1
            elif status == "post_noon":
                post_noon_count += 1
            elif status == "missed_checkout":
                missed_checkout_count += 1
            elif status == "ok":
                on_time_count += 1

        return {
            "employee": employee,
            "department": employee.department_id.name or "—",
            "late_count": late_count,
            "early_checkout_count": early_checkout_count,
            "absent_count": absent_count,
            "leave_count": leave_count,
            "post_noon_count": post_noon_count,
            "on_time_count": on_time_count,
            "missed_checkout_count": missed_checkout_count,
            "sat_off_count": sat_off_count,
            "total_working_days": total_working_days,
            "leave_balance": self._get_leave_balance(employee),
        }
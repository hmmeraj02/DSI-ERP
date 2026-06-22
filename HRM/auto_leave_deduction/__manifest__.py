{
    "name": "Auto Half-Day Leave Deduction",
    "version": "17.0.1.0.0",
    "category": "Human Resources/Attendances",
    "summary": "Automatic half-day leave deduction based on late check-in and early check-out",
    "description": """
        Auto Half-Day Leave Deduction System
        =====================================
        * Deduct 1 day leave for 3 late check-ins (15+ minutes)
        * Deduct 0.5 day leave for post-noon arrival (after 12:00 PM)
        * Deduct 0.5 day leave for early check-out (configurable time range)
        * Comprehensive logging and tracking
        * Configurable rules per company
        * Attendance list view with Late / Post-Noon / Early-Checkout columns
    """,
    "author": "Daffodil Software Limited",
    "website": "https://daffodilsoft.com/",
    "license": "LGPL-3",
    "depends": ["hr_attendance", "hr_attendance_auto_checkout", "hr_holidays"],
    "data": [
        "security/ir.model.access.csv",
        "security/leave_deduction_security.xml",
        "data/ir_cron.xml",
        "views/leave_deduction_config_views.xml",
        "views/leave_deduction_log_views.xml",
        "views/hr_employee_views.xml",
        "views/hr_attendance_views.xml",
        # "views/hr_leave_views.xml",
        "views/attendance_summary_wizard_views.xml",
        "report/attendance_summary_report_template.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}

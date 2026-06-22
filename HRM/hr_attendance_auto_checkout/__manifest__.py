# -*- coding: utf-8 -*-
{
    'name': 'HR Attendance Auto Checkout',
    'version': '17.0.1.0.0',
    'category': 'Human Resources/Attendances',
    'summary': 'Automatically checks out employees who forgot to check out',
    'description': """
        This module adds an automatic check-out feature for HR Attendance.
        A scheduled action (cron job) runs at 8:00 PM (Asia/Dhaka) every day.
        If any employee has checked in but not checked out on that day,
        the system will automatically set their check-out time to 8:00 PM.
    """,
    'author': 'Dream Study International',
    'depends': ['hr_attendance'],
    'data': [
        'data/cron_data.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

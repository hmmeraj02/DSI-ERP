# -*- coding: utf-8 -*-
{
    'name': 'HR Attendance IP Address Capture',
    'version': '17.0.1.0.0',
    'category': 'Human Resources/Attendances',
    'summary': 'Automatically captures IP address on attendance check-in and check-out',
    'description': """
        This module automatically captures the IP address of the user
        when an attendance record is created or updated (check-in/check-out).
        Works with manual attendance entries made from any custom dashboard.
    """,
    'author': 'Custom',
    'depends': ['hr_attendance'],
    'data': [
        'views/hr_attendance_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'sequence': 1,
}

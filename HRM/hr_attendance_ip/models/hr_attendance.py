# -*- coding: utf-8 -*-
from odoo import models, api
try:
    from odoo.http import request
except ImportError:
    request = None


def _get_ip_address():
    """
    Extract real IP address from the current HTTP request.
    Priority: X-Forwarded-For → X-Real-IP → REMOTE_ADDR
    Returns empty string if no HTTP request context is available.
    """
    if not request:
        return ''
    try:
        environ = request.httprequest.environ

        # Priority 1: X-Forwarded-For (proxy / load balancer)
        x_forwarded_for = environ.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()

        # Priority 2: X-Real-IP (nginx reverse proxy)
        x_real_ip = environ.get('HTTP_X_REAL_IP')
        if x_real_ip:
            return x_real_ip.strip()

        # Priority 3: Direct connection
        return environ.get('REMOTE_ADDR', '')
    except Exception:
        return ''


class HrAttendanceIP(models.Model):
    _inherit = 'hr.attendance'

    @api.model_create_multi
    def create(self, vals_list):
        """
        Capture IP address on check-in.
        """
        ip = _get_ip_address()
        if ip:
            if isinstance(vals_list, dict):
                # Called from an older module passing a single dict
                if not vals_list.get('in_ip_address'):
                    vals_list['in_ip_address'] = ip
            elif isinstance(vals_list, list):
                for vals in vals_list:
                    if isinstance(vals, dict) and not vals.get('in_ip_address'):
                        vals['in_ip_address'] = ip
        return super().create(vals_list)

    def write(self, vals):
        """
        Capture IP address on check-out.
        Only sets out_ip_address when check_out is being written for the first time.
        """
        if isinstance(vals, dict):
            ip = _get_ip_address()
            if ip and vals.get('check_out') and not vals.get('out_ip_address'):
                vals['out_ip_address'] = ip
        return super().write(vals)
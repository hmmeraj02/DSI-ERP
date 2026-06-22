from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class LeaveDeductionConfig(models.Model):
    _name = "leave.deduction.config"
    _description = "Leave Deduction Configuration"
    _rec_name = "company_id"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )

    # Rule 1: 15-min Late
    office_start_time = fields.Float(
        string="Office Start Time",
        default=10.0,
        help="Office start time in 24-hour format (e.g., 10.0 for 10:00 AM)",
    )
    office_end_time = fields.Float(
        string="Office End Time",
        default=19.0,
        help="Official office end time in 24-hour format (e.g., 19.0 for 7:00 PM). "
             "Used to calculate how early an employee left during early checkout.",
    )
    late_threshold_minutes = fields.Integer(
        string="Late Threshold (Minutes)",
        default=15,
        help="Minutes after start time to consider as late",
    )
    late_days_for_deduction = fields.Integer(
        string="Late Days Count for Deduction",
        default=3,
        help="Number of late days to trigger half-day deduction",
    )

    # Rule 2: Post-noon arrival
    noon_threshold_time = fields.Float(
        string="Post-Noon Threshold",
        default=12.0,
        help="Time after which arrival triggers immediate half-day deduction",
    )

    # Rule 3: Early checkout
    early_checkout_start_time = fields.Float(
        string="Early Checkout Start Time",
        default=14.0,
        help="Start of early checkout detection window",
    )
    early_checkout_end_time = fields.Float(
        string="Early Checkout End Time",
        default=16.0,
        help="End of early checkout detection window",
    )

    # NEW: Leave Type Selection
    leave_type_id = fields.Many2one(
        "hr.leave.type",
        string="Time-Off Type for Deduction",
        required=True,
        help="Select which time-off type to deduct from when violations occur",
    )

    # NEW: Auto-create allocation option
    auto_create_allocation = fields.Boolean(
        string="Auto-Create Allocation",
        default=False,
        help="If enabled, will automatically create allocation if employee does not have one",
    )

    initial_allocation_days = fields.Float(
        string="Initial Allocation Days",
        default=20.0,
        help="Number of days to allocate when auto-creating (only if Auto-Create is enabled)",
    )

    active = fields.Boolean(string="Active", default=True)

    _sql_constraints = [
        (
            "company_unique",
            "unique(company_id)",
            "Only one configuration per company is allowed!",
        )
    ]

    @api.constrains(
        "office_start_time",
        "noon_threshold_time",
        "early_checkout_start_time",
        "early_checkout_end_time",
    )
    def _check_time_values(self):
        for record in self:
            if not (0 <= record.office_start_time < 24):
                raise ValidationError("Office start time must be between 0 and 24")
            if not (0 <= record.noon_threshold_time < 24):
                raise ValidationError("Noon threshold must be between 0 and 24")
            if not (0 <= record.early_checkout_start_time < 24):
                raise ValidationError(
                    "Early checkout start time must be between 0 and 24"
                )
            if not (0 <= record.early_checkout_end_time < 24):
                raise ValidationError(
                    "Early checkout end time must be between 0 and 24"
                )
            if not (0 <= record.office_end_time < 24):
                raise ValidationError("Office end time must be between 0 and 24")
            if record.office_end_time <= record.early_checkout_end_time:
                raise ValidationError(
                    "Office end time must be after early checkout end time"
                )
            if record.early_checkout_start_time >= record.early_checkout_end_time:
                raise ValidationError(
                    "Early checkout start time must be before end time"
                )

    @api.model
    def get_config(self, company_id=None):
        """Get active configuration for company"""
        if not company_id:
            company_id = self.env.company.id
            
        config = self.search(
            [("company_id", "=", company_id), ("active", "=", True)], limit=1
        )
        
        if not config:
            # Check if we're in module installation mode
            if self.env.context.get('module') == 'auto_leave_deduction':
                _logger.info('Module installation in progress, returning None instead of error')
                return None
            
            # Try auto-create
            _logger.warning(f'No configuration found for company {company_id}. Attempting auto-create...')
            
            try:
                # Get default leave type
                leave_type = self.env['hr.leave.type'].search([
                    ('requires_allocation', '=', 'yes'),
                    '|', ('company_id', '=', company_id), ('company_id', '=', False)
                ], limit=1)
                
                config_vals = {
                    'company_id': company_id,
                    'office_start_time': 10.0,
                    'late_threshold_minutes': 15,
                    'late_days_for_deduction': 3,
                    'noon_threshold_time': 12.0,
                    'early_checkout_start_time': 14.0,
                    'early_checkout_end_time': 17.0,
                    'auto_create_allocation': False,
                    'initial_allocation_days': 20.0,
                    'active': True,
                }
                
                if leave_type:
                    config_vals['leave_type_id'] = leave_type.id
                
                config = self.sudo().create(config_vals)
                _logger.info(f'Auto-created default configuration for company {company_id}')
                
            except Exception as e:
                _logger.error(f'Failed to create configuration: {str(e)}')
                # Return None instead of raising error during installation
                return None
        
        return config
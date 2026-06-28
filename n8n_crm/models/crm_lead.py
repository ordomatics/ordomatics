from odoo import models


class CrmLead(models.Model):
    _name = "crm.lead"
    _inherit = ["crm.lead", "n8n.mixin"]

    def write(self, vals):
        # Capture which leads are being qualified (lead → opportunity)
        qualifying_ids = set()
        if vals.get("type") == "opportunity":
            qualifying_ids = {r.id for r in self if r.type == "lead"}

        result = super().write(vals)

        for lead in self.filtered(lambda r: r.id in qualifying_ids):
            lead._n8n_trigger(
                "crm-lead-qualified",
                {
                    "id": lead.id,
                    "name": lead.name,
                    "partner_name": lead.partner_name
                    or (lead.partner_id.name if lead.partner_id else None),
                    "email": lead.email_from,
                    "phone": lead.phone,
                    "expected_revenue": lead.expected_revenue,
                    "stage": lead.stage_id.name if lead.stage_id else None,
                    "salesperson": lead.user_id.name if lead.user_id else None,
                    "company": lead.company_id.name if lead.company_id else None,
                },
            )

        return result

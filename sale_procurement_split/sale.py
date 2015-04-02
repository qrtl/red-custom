# -*- coding: utf-8 -*-
#    OpenERP, Open Source Management Solution
#    Copyright (c) Rooms For (Hong Kong) Limited T/A OSCG. All Rights Reserved
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

from openerp.osv import fields, osv


class sale_order(osv.osv):
    _inherit = "sale.order"

    # override standard method to capture picking ids based on procurement group name
    def _get_picking_ids(self, cr, uid, ids, name, args, context=None):
        res = {}
        for sale in self.browse(cr, uid, ids, context=context):
            # >>> oscg
#             if not sale.procurement_group_id:
#                 res[sale.id] = []
#                 continue
#             res[sale.id] = self.pool.get('stock.picking').search(cr, uid, [('group_id', '=', sale.procurement_group_id.id)], context=context)
            group_ids = self.pool.get('procurement.group').search(cr, uid, [('name','=',sale.name)], context=context)
            res[sale.id] = self.pool.get('stock.picking').search(cr, uid, [('group_id','in',group_ids)], context=context)
            # <<< oscg
        return res

    _columns = {
        'picking_ids': fields.function(_get_picking_ids, method=True, type='one2many', relation='stock.picking', string='Picking associated to this sale'),
    }

    # override standard method to split procurements in such way that qty becomes 1
    def action_ship_create(self, cr, uid, ids, context=None):
        """Create the required procurements to supply sales order lines, also connecting
        the procurements to appropriate stock moves in order to bring the goods to the
        sales order's requested location.

        :return: True
        """
        context = context or {}
        context['lang'] = self.pool['res.users'].browse(cr, uid, uid).lang
        procurement_obj = self.pool.get('procurement.order')
        sale_line_obj = self.pool.get('sale.order.line')
        for order in self.browse(cr, uid, ids, context=context):
            proc_ids = []
            
            # >>> oscg
#             vals = self._prepare_procurement_group(cr, uid, order, context=context)
#             if not order.procurement_group_id:
#                 group_id = self.pool.get("procurement.group").create(cr, uid, vals, context=context)
#                 order.write({'procurement_group_id': group_id})
            # <<< oscg
            
            for line in order.order_line:
                #Try to fix exception procurement (possible when after a shipping exception the user choose to recreate)
                if line.procurement_ids:
                    #first check them to see if they are in exception or not (one of the related moves is cancelled)
                    procurement_obj.check(cr, uid, [x.id for x in line.procurement_ids if x.state not in ['cancel', 'done']])
                    line.refresh()
                    #run again procurement that are in exception in order to trigger another move
                    except_proc_ids = [x.id for x in line.procurement_ids if x.state in ('exception', 'cancel')]
                    procurement_obj.reset_to_confirmed(cr, uid, except_proc_ids, context=context)
                    proc_ids += except_proc_ids
                elif sale_line_obj.need_procurement(cr, uid, [line.id], context=context):
                    if (line.state == 'done') or not line.product_id:
                        continue
                    # >>> oscg
                    if line.product_uom_qty > 1.0:
                        line_qty = int(line.product_uom_qty)
                        for _ in xrange(line_qty):
                            line.product_uom_qty = 1
                            group_vals = self._prepare_procurement_group(cr, uid, order, context=context)
                            group_id = self.pool.get("procurement.group").create(cr, uid, group_vals, context=context)
                            vals = self._prepare_order_line_procurement(cr, uid, order, line, group_id=group_id, context=context)
                            ctx = context.copy()
                            ctx['procurement_autorun_defer'] = True
                            proc_id = procurement_obj.create(cr, uid, vals, context=ctx)
                            proc_ids.append(proc_id)
                    # <<< oscg
            #Confirm procurement order such that rules will be applied on it
            #note that the workflow normally ensure proc_ids isn't an empty list
            procurement_obj.run(cr, uid, proc_ids, context=context)

            #if shipping was in exception and the user choose to recreate the delivery order, write the new status of SO
            if order.state == 'shipping_except':
                val = {'state': 'progress', 'shipped': False}

                if (order.order_policy == 'manual'):
                    for line in order.order_line:
                        if (not line.invoiced) and (line.state not in ('cancel', 'draft')):
                            val['state'] = 'manual'
                            break
                order.write(val)
        return True

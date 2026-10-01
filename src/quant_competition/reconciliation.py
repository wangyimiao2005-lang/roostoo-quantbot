from dataclasses import dataclass
@dataclass(frozen=True)
class Reconciliation: target_tracking_error:float; unexpected_position:bool; unknown_pending_order:bool; gross_exposure:float; net_exposure:float; status:str
def reconcile(target,positions,prices,equity,pending_orders,known_order_ids,tolerance=.01):
 actual={s:positions.get(s,0)*prices.get(s,0)/equity for s in set(target)|set(positions)}; err=sum(abs(target.get(s,0)-actual.get(s,0)) for s in set(target)|set(actual)); gross=sum(abs(x) for x in actual.values()); unknown=any(str(x.get('OrderID','')) not in known_order_ids for x in pending_orders); return Reconciliation(err,err>tolerance,unknown,gross,sum(actual.values()),'HALT_NEW_RISK' if err>tolerance or unknown else 'OK')

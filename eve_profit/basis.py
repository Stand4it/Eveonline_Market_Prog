"""Cost basis from your wallet transactions (what you actually paid), so we never sell at a loss by accident.
Average buy price per item type; units you already sold reduce how many of your current units count as 'bought'.
Items with no buy record (mined, looted, built, gifted, or older than the history ESI returns) have NO basis:
they are treated as free, so selling them can't be a loss."""


def cost_basis(con):
    """-> {type_id: (avg_buy_price, units_bought_net_of_sales)}"""
    out = {}
    for r in con.execute("SELECT type_id, SUM(CASE WHEN is_buy=1 THEN quantity ELSE 0 END) AS bq, "
                         "SUM(CASE WHEN is_buy=1 THEN quantity*unit_price ELSE 0 END) AS bv, "
                         "SUM(CASE WHEN is_buy=0 THEN quantity ELSE 0 END) AS sq FROM transactions GROUP BY type_id"):
        if r["bq"] > 0:
            out[r["type_id"]] = (r["bv"] / r["bq"], max(0, r["bq"] - r["sq"]))
    return out


def stack_basis(basis, tid, qty):
    """-> (total_cost_of_units_with_a_known_price, units_covered)."""
    if tid not in basis:
        return 0.0, 0
    avg, owned = basis[tid]
    covered = min(qty, owned)
    return avg * covered, covered

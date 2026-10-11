from typing import List, Dict, Any
from services.forecast_engine import ForecastEngine

class RecommendationEngine:
    def __init__(self, forecast_engine: ForecastEngine):
        self.forecast_engine = forecast_engine
        
    
    def get_recommendations(self, state: str = None, district: str = None) -> List[Dict[str, Any]]:
        df = self.forecast_engine.df.copy()

        if state:
            df = df[df["state"].str.lower() == state.lower()]
        if district:
            df = df[df["district"].str.lower() == district.lower()]

        location = district or state or "National"
        skills = df["skill"].dropna().unique()

        shortage_trades = []
        surplus_trades = []

        # Step 1: 24-month forecast ke basis par trades classify karo
        for skill in skills:
            result = self.forecast_engine.get_forecast(skill, state, district)
            if not result:
                continue

            forecast_24 = next(
                (item for item in result.get("forecasts", [])
                 if item.get("months") == 24),
                None
            )
            if not forecast_24:
                continue

            demand = float(forecast_24.get("demand", 0))
            supply = float(forecast_24.get("supply", 0))
            gap = demand - supply

            trade = {
                "skill": skill,
                "location": location,
                "demand_24_months": demand,
                "supply_24_months": supply,
                "gap_24_months": gap,
                "growth_rate": result.get("growth_rate", 0),
            }

            if gap > 500:
                shortage_trades.append(trade)
            elif gap < -500:
                surplus_trades.append(trade)

        # Highest shortage aur largest surplus ko pehle consider karo
        shortage_trades.sort(key=lambda item: item["gap_24_months"], reverse=True)
        surplus_trades.sort(key=lambda item: item["gap_24_months"])

        recommendations = []

        # Step 2: Existing increase / freeze recommendations maintain karo
        for trade in shortage_trades:
            gap = trade["gap_24_months"]
            recommendations.append({
                **trade,
                "recommendation": (
                    f"Increase {trade['skill']} training capacity; "
                    f"projected shortage is {int(gap)} workers."
                ),
                "reasons": [
                    f"Projected annual demand growth: "
                    f"{float(trade['growth_rate']) * 100:.1f}%.",
                    "Projected 24-month demand exceeds supply.",
                ],
            })

        for trade in surplus_trades:
            surplus = abs(trade["gap_24_months"])
            recommendations.append({
                **trade,
                "recommendation": (
                    f"Review or divert new seat allocations for {trade['skill']}; "
                    f"projected surplus is {int(surplus)} workers."
                ),
                "reasons": [
                    "Projected 24-month supply exceeds demand.",
                    "Consider retraining before reducing existing training capacity.",
                ],
            })

        # Step 3: Pair surplus trades with shortage trades
        remaining_surplus = {
            trade["skill"]: abs(trade["gap_24_months"])
            for trade in surplus_trades
        }

        for target in shortage_trades:
            remaining_shortage = target["gap_24_months"]
            transfer_options = []

            for source in surplus_trades:
                available = remaining_surplus.get(source["skill"], 0)
                if available <= 0 or remaining_shortage <= 0:
                    continue

                # Upper-bound estimate, not a claim of globally optimal allocation
                seats = int(min(available, remaining_shortage))
                if seats <= 0:
                    continue

                transfer_options.append({
                    "source_skill": source["skill"],
                    "target_skill": target["skill"],
                    "suggested_seats_to_shift": seats,
                    "source_projected_surplus": int(available),
                    "target_projected_shortage": int(
                        target["gap_24_months"]
                    ),
                    "location": location,
                    "basis": "24-month demand-supply forecast",
                    "note": (
                        "Model-based planning estimate. Validate training "
                        "eligibility, costs, and local capacity before approval."
                    ),
                })

                remaining_surplus[source["skill"]] -= seats
                remaining_shortage -= seats

            target["seat_transfer_options"] = transfer_options

        return recommendations


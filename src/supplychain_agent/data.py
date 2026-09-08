"""Small, explicitly synthetic business datasets, safe to share with a model provider."""

from .schemas import SKU, Scenario


def demo_scenario() -> Scenario:
    return Scenario(
        scenario_id="factory-demo",
        name="华东工厂 · 周度物料补货",
        budget=12000,
        horizon_days=7,
        min_service_level=0,
        provenance="synthetic: illustrative quantities and CNY costs; not ABB data",
        skus=[
            SKU(
                sku_id="MOTOR",
                name="伺服电机",
                initial_stock=8,
                demand=30,
                unit_cost=220,
                holding_cost=8,
                shortage_penalty=1500,
                min_order_qty=5,
                max_order_qty=40,
                lead_time_days=3,
                critical=True,
            ),
            SKU(
                sku_id="SENSOR",
                name="光电传感器",
                initial_stock=20,
                demand=65,
                unit_cost=65,
                holding_cost=2,
                shortage_penalty=450,
                min_order_qty=10,
                max_order_qty=80,
                lead_time_days=2,
                critical=True,
            ),
            SKU(
                sku_id="BELT",
                name="同步带",
                initial_stock=15,
                demand=90,
                unit_cost=28,
                holding_cost=1,
                shortage_penalty=100,
                min_order_qty=20,
                max_order_qty=100,
                lead_time_days=5,
            ),
            SKU(
                sku_id="BEARING",
                name="轴承",
                initial_stock=40,
                demand=150,
                unit_cost=16,
                holding_cost=0.5,
                shortage_penalty=75,
                min_order_qty=30,
                max_order_qty=180,
                lead_time_days=4,
            ),
            SKU(
                sku_id="PLC",
                name="控制器",
                initial_stock=4,
                demand=10,
                unit_cost=460,
                holding_cost=12,
                shortage_penalty=1800,
                min_order_qty=2,
                max_order_qty=12,
                lead_time_days=10,
                critical=True,
            ),
        ],
    )


def get_scenario(scenario_id: str) -> Scenario:
    if scenario_id != "factory-demo":
        raise KeyError(f"Unknown scenario: {scenario_id}")
    return demo_scenario()

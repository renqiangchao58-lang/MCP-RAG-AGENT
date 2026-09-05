from support_pilot.repository import SupportRepository


def test_seeded_business_data(app_settings):
    repository = SupportRepository(app_settings.support_db_path)

    assert repository.counts() == {"customers": 20, "orders": 30, "tickets": 10}
    order = repository.get_order("a1024")
    assert order["found"] is True
    assert order["delay_days"] == 5
    assert order["customer_tier"] == "gold"


def test_create_ticket_validates_order_and_persists(app_settings):
    repository = SupportRepository(app_settings.support_db_path)

    missing = repository.create_ticket("A9999", "售后咨询", "测试")
    assert missing == {"created": False, "order_id": "A9999", "error": "订单不存在"}
    assert repository.counts()["tickets"] == 10

    created = repository.create_ticket("A1024", "配送延迟补偿", "延迟五天")
    assert created["created"] is True
    assert created["ticket_id"].startswith("T-")
    assert repository.counts()["tickets"] == 11
    assert repository.list_tickets("A1024")[0]["id"] == created["ticket_id"]


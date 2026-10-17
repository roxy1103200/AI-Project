"""Website financial facts must stay consistent across order state transitions."""

import unittest

from app.order_answers import order_answer, valid_order_contract


def sample(**changes):
    return {
        "contract_version": "cinema-order-v2",
        "status": "REFUNDING",
        "payment_status": "SUCCESS",
        "refund_status": "UNKNOWN",
        "refund_reason_type": "CUSTOMER",
        "can_refund": False,
        "refund_reason": "退款结果仍在核对，电影票暂不可使用",
        "server_time": "2026-10-17T12:00:00",
        **changes,
    }


class OrderAnswersTest(unittest.TestCase):
    def test_unknown_refund_does_not_claim_success(self):
        value = sample()
        self.assertTrue(valid_order_contract(value))
        answer = order_answer(value)
        self.assertIn("仍在核对", answer)
        self.assertIn("暂不可使用", answer)
        self.assertNotIn("已退款", answer)

    def test_missing_unknown_or_contradictory_states_are_rejected(self):
        self.assertFalse(valid_order_contract({"status": "ISSUED"}))
        self.assertFalse(valid_order_contract(sample(status="UNRECOGNIZED")))
        self.assertFalse(valid_order_contract(sample(can_refund=True)))
        self.assertFalse(valid_order_contract(sample(refund_status="REFUNDED")))
        self.assertFalse(valid_order_contract(sample(payment_status="CLOSING")))
        self.assertFalse(valid_order_contract(sample(status={})))
        self.assertFalse(valid_order_contract(sample(refund_status=[])))
        self.assertFalse(
            valid_order_contract(
                sample(status="ISSUED", refund_status=None, refund_reason_type=None, payment_status="INIT")
            )
        )
        self.assertFalse(valid_order_contract(sample(status="ISSUED", refund_status="REFUNDED")))
        self.assertFalse(valid_order_contract(sample(refund_reason_type=None)))

    def test_late_payment_is_a_cancelled_order_with_refund_facts(self):
        value = sample(status="CANCELLED", refund_reason_type="LATE_PAYMENT")
        self.assertTrue(valid_order_contract(value))
        self.assertIn("已取消", order_answer(value))
        value["refund_status"] = "REFUNDED"
        value["refund_reason"] = "订单已取消，迟到付款的补偿退款已确认"
        self.assertTrue(valid_order_contract(value))
        self.assertIn("补偿退款已确认", order_answer(value))

"""Operations API regression tests; use fake database calls, never production SQL."""
import sys
import types
import unittest
from datetime import date
from unittest.mock import patch
from types import SimpleNamespace

# operations_api imports db before tests; replace it with a non-connecting module.
db_stub = types.ModuleType("db")
db_stub.query = lambda *a, **k: []
db_stub.execute = lambda *a, **k: None
sys.modules["db"] = db_stub
import operations_api as ops
from fastapi import HTTPException


def req(role="admin"):
    return SimpleNamespace(state=SimpleNamespace(user={"role":role, "username":"tester"}))


class OperationsTests(unittest.TestCase):
    def test_authentication_and_write_access(self):
        with self.assertRaises(HTTPException) as context:
            ops.permitted(req("viewer"), ("admin",))
        self.assertEqual(context.exception.status_code,403)
        self.assertEqual(ops.permitted(req("hr"), ("admin","hr"))["username"], "tester")

    def test_empty_daily_roster(self):
        with patch.object(ops,"query",return_value=[]):
            report=ops.daily_report(req("viewer"),date(2026,11,13))
        self.assertEqual(report["rows"],[])
        self.assertEqual(report["summary"]["present"],0)

    def test_day_shift_late_and_missing_punches(self):
        rows=[
            {"employee_id":"E1","person_name":"Ada","base_location":"HO","shift_start":"09:00","shift_end":"18:00",
             "grace_minutes":15,"first_check_in":"2026-11-13 09:17:00","last_check_out":None,"shift_name":"Day"},
            {"employee_id":"E2","person_name":"Ben","base_location":"HO","shift_start":"09:00","shift_end":"18:00",
             "grace_minutes":15,"first_check_in":"2026-11-13 09:14:00","last_check_out":None,"shift_name":"Day"},
            {"employee_id":"E3","person_name":"Cy","base_location":"HO","shift_start":"09:00","shift_end":"18:00",
             "grace_minutes":15,"first_check_in":None,"last_check_out":None,"shift_name":"Day"},
        ]
        with patch.object(ops,"query",return_value=rows):
            report=ops.daily_report(req("viewer"),date(2026,11,13))
        self.assertEqual([x["attendance_status"] for x in report["rows"]],["LATE","ON_TIME","NO_PUNCH_SCHEDULED"])
        self.assertEqual(report["summary"]["late"],1)
        self.assertEqual(report["summary"]["not_recorded"],1)

    def test_overnight_not_misclassified(self):
        row={"employee_id":"E1","person_name":"Ada","base_location":"HO","shift_start":"20:00","shift_end":"05:00",
             "grace_minutes":5,"first_check_in":"2026-11-13 20:30:00","last_check_out":None,"shift_name":"Night"}
        with patch.object(ops,"query",return_value=[row]):
            report=ops.daily_report(req("viewer"),date(2026,11,13))
        self.assertEqual(report["rows"][0]["attendance_status"],"PRESENT_OVERNIGHT_REVIEW")

    def test_shift_assignment_rejects_missing_employee(self):
        with patch.object(ops,"exists",side_effect=[False,True]), patch.object(ops,"execute") as execute:
            with self.assertRaises(HTTPException) as context:
                ops.assign_shift(ops.ShiftAssignment(employee_id="NOPE",shift_id=1),req("hr"))
            self.assertEqual(context.exception.status_code,404)
            execute.assert_not_called()

    def test_camera_area_write_requires_admin(self):
        with patch.object(ops,"execute") as execute:
            with self.assertRaises(HTTPException) as context:
                ops.assign_camera_area(ops.CameraAreaAssignment(camera_id="HO_IN",area_id=1),req("viewer"))
            self.assertEqual(context.exception.status_code,403)
            execute.assert_not_called()

    def test_overview_without_leave_tables(self):
        samples=[
            [{"present":3}],[{"total":5}],[{"total":2}],
        ]
        with patch.object(ops,"query",side_effect=samples):
            data=ops.overview(req("viewer"),date(2026,11,13))
        self.assertEqual(data,{"staff":5,"present":3,"visitors":2,"not_recorded":2})

    def test_report_locations(self):
        with patch.object(ops,"query",return_value=[{"base_location":"HO"},{"base_location":"ICD"}]):
            self.assertEqual(ops.report_locations(req("viewer")),["HO","ICD"])

    def test_analytics_does_not_pretend_to_count_people(self):
        with patch.object(ops,"query",side_effect=[[],[]]):
            data=ops.attendance_activity(req("viewer"),date(2026,11,13))
        self.assertEqual(data["metric"],"verified_attendance_events")
        self.assertFalse(data["is_people_count"])


if __name__=="__main__":
    unittest.main()

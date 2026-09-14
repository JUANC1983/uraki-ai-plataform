import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DashboardAppSmokeTests(unittest.TestCase):
    def test_decision_service_accepts_api_rule_trace_lists(self):
        code = """
import sys
sys.path.insert(0, 'dashboard')
from services.decision_service import _risk_factor_rows, _rule_count
from components.decision_card import _render_consistency_violations
from core.consistency import ConsistencyResult
assert _rule_count([{'matched': True}, {'matched': False}]) == 2
assert _rule_count([]) == 0
assert _rule_count(3) == 3
rows = _risk_factor_rows({
    'component_scores': {'overdue_days': 100.0},
    'weights_used': {'overdue_days': 0.4},
    'component_reasons': {'overdue_days': '95d -> band >90d'},
})
assert rows == [{
    'factor': 'Overdue Days',
    'value': '95d -> band >90d',
    'weight': 'Peso 40%',
    'contribution': 0.4,
}]
_render_consistency_violations(ConsistencyResult(ok=True, violations=[]), {})
print('DASHBOARD_RULE_COUNT_OK')
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=ROOT,
            env={**os.environ, "DEBUG": "false", "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DASHBOARD_RULE_COUNT_OK", result.stdout)

    def test_streamlit_login_surface_renders_without_exceptions(self):
        code = """
from streamlit.testing.v1 import AppTest
app = AppTest.from_file('dashboard/app.py', default_timeout=15).run()
if app.exception:
    raise AssertionError([item.value for item in app.exception])
labels = [item.label for item in app.text_input]
if labels != ['Tenant', 'Correo electrónico', 'Contraseña']:
    raise AssertionError(labels)
if [item.label for item in app.button] != ['Iniciar sesión']:
    raise AssertionError([item.label for item in app.button])
print('DASHBOARD_APP_OK')
"""
        environment = dict(os.environ)
        environment.update({
            "DEBUG": "false",
            "PYTHONDONTWRITEBYTECODE": "1",
            "URAKI_API_URL": "http://127.0.0.1:8000",
        })
        result = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DASHBOARD_APP_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()

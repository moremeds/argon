import inspect

from app import streamlit_app
from uw_scan.config import UwScanConfig


def test_streamlit_app_uses_pipeline_boundary():
    source = inspect.getsource(streamlit_app)
    assert "dashboard_for_mode" in source
    assert "demo_dashboard()" not in source


def test_streamlit_app_renders_analysis_sections():
    source = inspect.getsource(streamlit_app)
    assert "Analysis Board" in source
    assert "Market Structure" in source
    assert "VRP Assessment" in source
    assert "Trade Plan" in source
    assert "Executive Summary" in source
    assert "Request Plan" in source


def test_streamlit_app_wires_snapshot_actions_to_repository():
    source = inspect.getsource(streamlit_app)
    assert "save_dashboard_snapshot" in source
    assert "load_dashboard_snapshot" in source
    assert "apply_migrations" in source
    assert "connect_db" in source


def test_streamlit_defaults_to_live_when_api_key_is_configured():
    assert streamlit_app._default_mode_index(UwScanConfig(api_key="configured")) == 1
    assert streamlit_app._default_mode_index(UwScanConfig(api_key=None)) == 0

import importlib


def test_streamlit_app_imports_without_running_server():
    module = importlib.import_module("app.streamlit_app")

    assert hasattr(module, "render_app")

"""Streamlit Community Cloud entrypoint. Runs the existing Ver.3.1 application."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).with_name("26_app.py")), run_name="__main__")

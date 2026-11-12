"""
Unit tests for Phase 1: Environment & Skeleton.
Verifies project structure, configuration parameters, and code syntax.
"""

import os
import py_compile
import pytest
import config

def test_config_constants():
    """Verify essential config variables are loaded."""
    assert config.APP_TITLE == "BioFlex Lab"
    assert len(config.PRIORITY_MATERIALS) >= 3
    assert "sugarcane" in config.PRIORITY_MATERIALS
    assert "banana peel" in config.PRIORITY_MATERIALS
    assert config.GEMINI_MODEL_NAME is not None
    assert len(config.AI_ASSISTANT_SYSTEM_PROMPT) > 50

def test_required_files_exist():
    """Verify that all Phase 1 skeleton files are present."""
    required_files = [
        "app.py",
        "config.py",
        "requirements.txt",
        ".gitignore",
        ".env.example",
        "PROJECT_BRIEF.md",
        os.path.join("pages", "1_Material_Explorer.py"),
        os.path.join("pages", "2_AI_Assistant.py"),
        os.path.join("pages", "3_About.py"),
    ]
    for filepath in required_files:
        assert os.path.exists(filepath), f"Expected file {filepath} to exist."

def test_python_syntax():
    """Ensure all created python files have valid syntax without compiling errors."""
    python_files = [
        "config.py",
        "app.py",
        os.path.join("pages", "1_Material_Explorer.py"),
        os.path.join("pages", "2_AI_Assistant.py"),
        os.path.join("pages", "3_About.py"),
    ]
    for py_file in python_files:
        # py_compile.compile raises an exception if syntax is invalid
        compiled = py_compile.compile(py_file, doraise=True)
        assert compiled is not None


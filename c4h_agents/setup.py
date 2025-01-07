"""
Setup configuration for c4h_agents package.
Path: c4h_agents/setup.py
"""

from setuptools import setup, find_packages

setup(
    name="c4h_agents",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "litellm",
        "structlog",
        "pydantic",
        "PyYAML"
    ],
    python_requires=">=3.11",
)
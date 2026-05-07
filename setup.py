from setuptools import setup, find_packages

setup(
    name="seasonic",
    version="0.1.0",
    description="S7K sonar file viewer",
    py_modules=["viewer", "s7k_parser"],
    python_requires=">=3.10",
    install_requires=[
        "PySide6>=6.7",
        "numpy>=1.26",
        "matplotlib>=3.8",
    ],
    entry_points={
        "console_scripts": [
            "seasonic=viewer:main",
        ],
    },
)

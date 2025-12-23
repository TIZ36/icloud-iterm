from setuptools import setup, find_packages

setup(
    name="icloud-cli",
    version="0.1.0",
    description="iCloud CLI tool similar to Perforce",
    author="",
    packages=find_packages(),
    install_requires=[
        "pyicloud>=0.10.0",
        "click>=8.0.0",
        "requests>=2.28.0",
        "filelock>=3.9.0",
    ],
    entry_points={
        "console_scripts": [
            "icloud=icloud.cli:main",
        ],
    },
    python_requires=">=3.8",
)


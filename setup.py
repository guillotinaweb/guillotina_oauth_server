# -*- coding: utf-8 -*-
from setuptools import find_packages
from setuptools import setup


test_requires = [
    "async_asgi_testclient",
    "pytest>=5.0",
    "pytest-asyncio==0.18.3",
    "coverage",
    "pytest-cov",
    "pytest-docker-fixtures[pg]>=1.3.0",
    "docker",
    # guillotina.tests.fixtures imports aiohttp at module level; it lives in
    # guillotina's own [test] extra, so declare it here to keep CI self-contained.
    "aiohttp>=3.0.0,<4.0.0",
]


setup(
    name="guillotina_oauth_server",
    description="OAuth 2.0 authorization server for guillotina",
    keywords="async guillotina oauth oauth2 authentication authorization",
    author="Roger Boixader Güell",
    author_email="rboixaderg@gmail.com",
    version=open("VERSION").read().strip(),
    long_description=(open("README.rst").read() + "\n" + open("CHANGELOG.rst").read()),
    long_description_content_type="text/x-rst",
    classifiers=[
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    url="https://github.com/guillotinaweb/guillotina_oauth_server",
    license="GPL version 3",
    python_requires=">=3.10",
    setup_requires=["pytest-runner"],
    zip_safe=True,
    include_package_data=True,
    package_data={
        "": ["*.txt", "*.rst"],
        "guillotina_oauth_server": [
            "py.typed",
            "api/templates/*.html",
            "api/templates/*.css",
            "api/static/*.svg",
        ],
    },
    packages=find_packages(exclude=["ez_setup"]),
    install_requires=[
        "guillotina>=7.1.0",
        "pyjwt",
        "asyncpg",
    ],
    tests_require=test_requires,
    extras_require={
        "test": test_requires,
        "mcp": ["mcp>=1.0.0"],
        "redis": ["redis>=4.3.0"],
    },
)

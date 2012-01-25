from __future__ import with_statement
from setuptools import setup

from txjsonrpc import __version__


with open("README.rst") as readme:
    long_description = readme.read()


classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
    "Programming Language :: Python",
    "Programming Language :: Python :: 2",
    "Programming Language :: Python :: 2 :: Only",
    "Programming Language :: Python :: 2.5",
    "Programming Language :: Python :: 2.6",
    "Programming Language :: Python :: 2.7",
    "Programming Language :: Python :: Implementation :: CPython",
    "Programming Language :: Python :: Implementation :: PyPy",
]


setup(
    name="txjsonrpc-tcp",
    version=__version__,
    packages=["txjsonrpc"],
    author="Julian Berman",
    author_email="Julian@GrayVines.com",
    classifiers=classifiers,
    description="A TCP implementation of JSON RPC for Twisted",
    license="MIT/X",
    long_description=long_description,
    url="http://github.com/Julian/txjsonrpc-tcp",
    install_requires=["Twisted"],
)

#!/usr/bin/env python

import os
from setuptools import setup

README = open(os.path.join(os.path.dirname(__file__), 'README.md')).read()

# allow setup.py to be run from any path
os.chdir(os.path.normpath(os.path.join(os.path.abspath(__file__), os.pardir)))

setup(
    name='canvas-event-consumer',
    version='1.0',
    packages=['events'],
    include_package_data=True,
    install_requires = [
        'setuptools',
        'django',
    ],
    dependency_links = [
        'http://github.com/uw-it-aca/django-aws-message#egg=django_aws_message',
        'http://github.com/uw-it-aca/uw-restclients#egg=RestClients'
    ],
    license='Apache License, Version 2.0',  # example license
    description='Consume student enrollment and group membership events for updating Canvas courses',
    long_description=README,
    url='https://github.com/uw-it-aca/canvas-event-consumer',
    author = "UW-IT ACA",
    author_email = "aca-it@uw.edu",
    classifiers=[
        'Environment :: Web Environment',
        'Framework :: Django',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License', # example license
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
    ],
)

# -*- coding: utf-8 -*-
# Generated by Django 1.9 on 2016-10-19 18:46
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0002_instructorlog'),
    ]

    operations = [
        migrations.CreateModel(
            name='PersonLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('minute', models.IntegerField(default=0)),
                ('event_count', models.SmallIntegerField(default=0)),
            ],
        ),
    ]

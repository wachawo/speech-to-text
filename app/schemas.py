#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
from marshmallow import Schema, fields, validates_schema, ValidationError
from marshmallow import validate
from dateutil import parser as dtparser
import pytz

TIMEZONE = pytz.timezone("America/New_York")

class FlexibleDateTime(fields.Field):
    """Поле, принимающее почти любой строковый datetime и возвращающее aware datetime в DEFAULT_TZ."""
    def _deserialize(self, value, attr, data, **kwargs):
        if not isinstance(value, str):
            raise ValidationError("Must be a string with datetime.")
        try:
            dt = dtparser.parse(value)
        except (ValueError, TypeError):
            raise ValidationError("Invalid datetime format.")
        if dt.tzinfo is None:
            dt = TIMEZONE.localize(dt)
        else:
            dt = dt.astimezone(TIMEZONE)
        return dt

class ReportSchema(Schema):
    timestamp = FlexibleDateTime(required=True, data_key="timestamp")
    app = fields.Str(required=True, validate=validate.OneOf(["vuejs", "angularjs"]))
    cluster = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    route = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    username = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    # во входе поле называется "datetime", а внутри мы хотим получить event_dt


    @validates_schema
    def sanity(self, data, **kwargs):
        # можно добавить кросс-поля проверки при необходимости
        pass

def main():
    pass

if __name__ == '__main__':
    main()
